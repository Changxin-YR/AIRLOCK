from __future__ import annotations

import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select

from airlock.common import DomainError, digest, now_ms, token_hash
from airlock.config import ConfigSource
from airlock.storage import Store, login_limits, sessions

PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
# A fixed valid hash makes unknown-user verification comparable to a normal login.
DUMMY_HASH = PASSWORD_HASHER.hash("not-a-usable-account")
COOKIE = "airlock_session"


class Auth:
    def __init__(self, store: Store, source: ConfigSource):
        self.store, self.source = store, source

    def login(self, username: str, password: str, address: str) -> tuple[str, dict]:
        config, now = self.source.read(), now_ms()
        # Account and peer buckets resist rotating usernames / a single-client burst.
        buckets = [token_hash("account:" + username), token_hash("peer:" + address)]
        # Reserve attempt slots atomically before expensive password verification.
        with self.store.transaction() as conn:
            for bucket in buckets:
                row = (
                    conn.execute(select(login_limits).where(login_limits.c.bucket == bucket))
                    .mappings()
                    .first()
                )
                if row and row["reset_at"] > now and row["failures"] >= 8:
                    raise DomainError("LOGIN_RATE_LIMIT", "登录尝试过多，请稍后再试。", 429)
                values = {
                    "failures": row["failures"] + 1 if row and row["reset_at"] > now else 1,
                    "reset_at": row["reset_at"] if row and row["reset_at"] > now else now + 60000,
                }
                if row:
                    conn.execute(
                        login_limits.update()
                        .where(login_limits.c.bucket == bucket)
                        .values(**values)
                    )
                else:
                    conn.execute(login_limits.insert().values(bucket=bucket, **values))
        reviewer = config.reviewer
        identity_ok = reviewer.active and hmac.compare_digest(
            username.encode(), reviewer.username.encode()
        )
        try:
            verified = PASSWORD_HASHER.verify(
                reviewer.password_hash if identity_ok else DUMMY_HASH, password
            )
        except (VerificationError, InvalidHashError):
            verified = False
        if not (identity_ok and verified):
            raise DomainError("LOGIN_FAILED", "账号或密码无效。", 401)
        token = secrets.token_urlsafe(32)
        session = {
            "token_hash": token_hash(token),
            "username": reviewer.username,
            "csrf": secrets.token_urlsafe(32),
            "reviewer_digest": digest(reviewer.model_dump()),
            "created_at": now,
            "expires_at": now + config.session_seconds * 1000,
        }
        with self.store.transaction() as conn:
            conn.execute(sessions.insert().values(**session))
            # Keep the peer bucket: successful attempts must not reset attack accounting.
            conn.execute(login_limits.delete().where(login_limits.c.bucket == buckets[0]))
        return token, session

    def human(self, token: str | None) -> dict:
        if not token or len(token) > 256:
            raise DomainError("UNAUTHENTICATED", "请使用独立审批账号登录。", 401)
        with self.store.read() as conn:
            row = (
                conn.execute(select(sessions).where(sessions.c.token_hash == token_hash(token)))
                .mappings()
                .first()
            )
        reviewer = self.source.read().reviewer
        if (
            not row
            or row["expires_at"] <= now_ms()
            or not reviewer.active
            or row["reviewer_digest"] != digest(reviewer.model_dump())
        ):
            raise DomainError("UNAUTHENTICATED", "登录已过期或审批权限已变化。", 401)
        return dict(row)

    def csrf(self, session: dict, supplied: str | None) -> None:
        if not supplied or not hmac.compare_digest(session["csrf"].encode(), supplied.encode()):
            raise DomainError("CSRF_FAILED", "请求校验失败，请刷新后重试。", 403)

    def logout(self, session: dict) -> None:
        # Preserve the row so historical view foreign keys remain valid.
        with self.store.transaction() as conn:
            conn.execute(
                sessions.update()
                .where(sessions.c.token_hash == session["token_hash"])
                .values(expires_at=0)
            )
