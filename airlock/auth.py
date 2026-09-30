from __future__ import annotations

import hashlib
import hmac
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import delete, select, update
from .common import AirlockError, now
from .storage import Store, principals, rate_limits, sessions

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def add_principal(store: Store, ident: str, kind: str, scope: str, *, username: str | None = None,
                  password: str | None = None, token: str | None = None, tools: list[str] | None = None) -> None:
    if kind not in {"agent", "human"} or (kind == "human" and (not username or not password)):
        raise ValueError("Invalid principal setup")
    with store.transaction() as conn:
        conn.execute(principals.insert().values(id=ident, kind=kind, scope=scope, active=True, version=1,
            tools_json=__import__("json").dumps(tools if tools is not None else ["db.query_rows","db.update_rows","db.delete_rows"]),
            username=username, password_hash=PASSWORDS.hash(password) if password else None,
            token_hash=token_hash(token) if token else None, created_at=store.clock()))


class Auth:
    def __init__(self, store: Store, *, session_ttl: int = 8*3600):
        self.store, self.session_ttl = store, session_ttl

    def agent(self, header: str | None) -> dict:
        if not header or not header.startswith("Bearer ") or len(header) > 300:
            raise AirlockError("AUTH_REQUIRED", "需要有效的 Agent 凭据。", 401)
        with self.store.engine.connect() as conn:
            principal = self.store.row(conn, principals, principals.c.token_hash == token_hash(header[7:]))
        if not principal or principal["kind"] != "agent" or not principal["active"]:
            raise AirlockError("AUTH_REQUIRED", "需要有效的 Agent 凭据。", 401)
        return principal

    def session(self, cookie: str | None, *, csrf: str | None = None, require_csrf: bool = False) -> dict:
        if not cookie or len(cookie) > 200:
            raise AirlockError("LOGIN_REQUIRED", "请先登录审批工作台。", 401)
        hashed = token_hash(cookie)
        with self.store.engine.connect() as conn:
            session = self.store.row(conn, sessions, sessions.c.token_hash == hashed)
            principal = self.store.row(conn, principals, principals.c.id == session["principal_id"]) if session else None
        if (not session or session["expires_at"] <= self.store.clock() or not principal
                or not principal["active"] or principal["kind"] != "human"
                or principal["version"] != session["auth_version"]):
            raise AirlockError("LOGIN_REQUIRED", "会话已失效，请重新登录。", 401)
        if require_csrf and (not csrf or not hmac.compare_digest(csrf.encode("utf-8"), session["csrf"].encode("utf-8"))):
            raise AirlockError("CSRF_REJECTED", "审批请求校验失败。", 403)
        return principal | {"session_hash": hashed, "csrf": session["csrf"], "session_expires_at": session["expires_at"]}

    def rate_limit(self, key: str, *, limit: int, window: float) -> None:
        timestamp = self.store.clock()
        with self.store.transaction() as conn:
            conn.execute(delete(rate_limits).where(rate_limits.c.started_at < timestamp-3600))
            record = self.store.row(conn, rate_limits, rate_limits.c.key == key)
            if not record or timestamp - record["started_at"] >= window:
                conn.execute(delete(rate_limits).where(rate_limits.c.key == key))
                conn.execute(rate_limits.insert().values(key=key, started_at=timestamp, count=1))
            elif record["count"] >= limit:
                raise AirlockError("RATE_LIMITED", "请求过于频繁，请稍后再试。", 429, retryable=True)
            else:
                conn.execute(update(rate_limits).where(rate_limits.c.key == key).values(count=record["count"]+1))

    def login(self, username: str, password: str, ip: str) -> tuple[str, dict]:
        # Separate address and account limits; headers such as X-Forwarded-For are not trusted.
        self.rate_limit("login-ip:"+token_hash(ip), limit=20, window=60)
        self.rate_limit("login-user:"+token_hash(username), limit=10, window=60)
        with self.store.engine.connect() as conn:
            user = self.store.row(conn, principals, principals.c.username == username)
        hashed = user["password_hash"] if user and user["password_hash"] else DUMMY_HASH
        try:
            valid = PASSWORDS.verify(hashed, password)
        except VerificationError:
            valid = False
        if not valid or not user or user["kind"] != "human" or not user["active"]:
            raise AirlockError("LOGIN_FAILED", "账号或密码不正确。", 401)
        cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.transaction() as conn:
            # Re-read after password verification: concurrent revocation cannot create a new session.
            current = self.store.row(conn, principals, principals.c.id == user["id"])
            if not current or not current["active"] or current["version"] != user["version"]:
                raise AirlockError("LOGIN_FAILED", "账号或密码不正确。", 401)
            conn.execute(delete(sessions).where(sessions.c.expires_at <= self.store.clock()))
            conn.execute(sessions.insert().values(token_hash=token_hash(cookie), principal_id=user["id"],
                auth_version=user["version"], csrf=csrf, expires_at=self.store.clock()+self.session_ttl))
        return cookie, {"username": username, "scope": user["scope"], "csrf": csrf}

    def logout(self, cookie: str) -> None:
        with self.store.transaction() as conn:
            conn.execute(delete(sessions).where(sessions.c.token_hash == token_hash(cookie)))
