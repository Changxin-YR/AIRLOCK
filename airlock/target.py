"""SQLite-only execution boundary: snapshot preview, final revalidation, atomic receipt."""

from __future__ import annotations

import hmac
import json
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from airlock.common import DomainError, canonical, digest, now_ms, sign
from airlock.config import policy_hash
from airlock.contracts import AgentPrincipal, OperationRequest, Policy, authorize

ADAPTER_VERSION = "sqlite-structured-v1"
BUSINESS_TABLES = ("customers", "customer_notes")
DDL = {
    "customers": """CREATE TABLE customers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        is_test INTEGER NOT NULL CHECK (is_test IN (0,1)),
        status TEXT NOT NULL CHECK (status IN ('active','archived')),
        tag TEXT NOT NULL CHECK (length(tag) <= 128),
        expires_at TEXT NOT NULL
    )""",
    "customer_notes": """CREATE TABLE customer_notes (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
        body TEXT NOT NULL
    )""",
    "execution_receipts": """CREATE TABLE execution_receipts (
        operation_id TEXT PRIMARY KEY,
        plan_digest TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
}


def seed_target(path: Path, customers: int = 1206) -> None:
    if path.exists():
        raise ValueError("target already exists; initialization never overwrites data")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys=ON")
        for sql in DDL.values():
            conn.execute(sql)
        conn.executemany(
            "INSERT INTO customers VALUES (?,?,?,?,?,?,?)",
            [
                (
                    i,
                    f"{'测试' if i <= 12 else '客户'}-{i:04d}",
                    f"fixture-{i}@example.invalid",
                    int(i <= 12),
                    "archived" if i <= 6 else "active",
                    "待整理" if i <= 12 else "正式",
                    "2026-01-01" if i <= 6 else "2030-01-01",
                )
                for i in range(1, customers + 1)
            ],
        )
        conn.executemany(
            "INSERT INTO customer_notes VALUES (?,?,?)",
            [
                (i * 2 - 1 + offset, i, f"合成备注 {i}-{offset + 1}")
                for i in range(1, min(12, customers) + 1)
                for offset in range(2)
            ],
        )


def logical_diff(before: dict, after: dict, direct_table: str) -> list[dict[str, Any]]:
    changes = []
    for table in BUSINESS_TABLES:
        old, new = {r["id"]: r for r in before[table]}, {r["id"]: r for r in after[table]}
        for pk in sorted(old.keys() | new.keys()):
            if old.get(pk) == new.get(pk):
                continue

            def visible(row):
                return {key: value for key, value in row.items() if key != "email"} if row else None

            changes.append(
                {
                    "table": table,
                    "id": pk,
                    "kind": "create" if pk not in old else "delete" if pk not in new else "update",
                    "scope": "direct" if table == direct_table else "cascade",
                    "before": visible(old.get(pk)),
                    "after": visible(new.get(pk)),
                }
            )
    return changes


class SQLiteTarget:
    def __init__(self, path: str | Path, secret: str):
        self.path, self.secret = Path(path).resolve(), secret

    @contextmanager
    def connection(self, writable: bool = False):
        conn = None
        try:
            uri = self.path.as_uri() + ("?mode=rw" if writable else "?mode=ro")
            conn = sqlite3.connect(uri, uri=True, timeout=0.5, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.enable_load_extension(False)
            yield conn
        except sqlite3.OperationalError as exc:
            code = (
                "TARGET_BUSY"
                if "locked" in str(exc) or "busy" in str(exc)
                else "TARGET_UNAVAILABLE"
            )
            raise DomainError(code, "目标暂不可用，请稍后查询状态。", 503, True) from exc
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _schema(conn: sqlite3.Connection) -> str:
        objects = [
            dict(r)
            for r in conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]

        def compact(sql):
            return " ".join((sql or "").split()).strip().rstrip(";")

        if len(objects) != len(DDL) or any(
            item["type"] != "table"
            or item["name"] not in DDL
            or compact(item["sql"]) != compact(DDL[item["name"]])
            for item in objects
        ):
            raise DomainError(
                "SCHEMA_UNSUPPORTED", "目标 Schema 超出已验证范围，禁止预检和执行。", 409
            )
        return digest(objects)

    @staticmethod
    def _state(conn: sqlite3.Connection, policy: Policy) -> dict[str, list[dict]]:
        state: dict[str, list[dict]] = {}
        remaining = policy.max_snapshot_rows
        for table in BUSINESS_TABLES:
            rows = conn.execute(
                f'SELECT * FROM "{table}" ORDER BY id LIMIT ?', (remaining + 1,)
            ).fetchall()
            if len(rows) > remaining:
                raise DomainError("PREVIEW_UNSUPPORTED", "数据量超过完整预检范围。", 413)
            state[table] = [dict(r) for r in rows]
            remaining -= len(rows)
        if len(canonical(state).encode()) > policy.max_snapshot_bytes:
            raise DomainError("PREVIEW_UNSUPPORTED", "数据大小超过完整预检范围。", 413)
        return state

    @staticmethod
    def _where(request: OperationRequest) -> tuple[str, list[Any]]:
        # Identifiers were checked against a static allowlist; values remain bound parameters.
        pieces, values = [], []
        operators = {"eq": "=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        for item in request.where:
            if item.op == "in":
                pieces.append(f'"{item.field}" IN ({",".join("?" for _ in item.value)})')
                values.extend(item.value)
            else:
                pieces.append(f'"{item.field}" {operators[item.op]} ?')
                values.append(item.value)
        return (" AND ".join(pieces) or "1=1"), values

    @classmethod
    def _apply(cls, conn: sqlite3.Connection, request: OperationRequest) -> dict[str, Any]:
        where, values = cls._where(request)
        if request.tool == "db.query_rows":
            columns = ",".join(f'"{c}"' for c in request.normalized()["columns"])
            rows = conn.execute(
                f"SELECT {columns} FROM customers WHERE {where} ORDER BY id LIMIT ?",
                [*values, request.limit],
            ).fetchall()
            return {"rows": [dict(row) for row in rows]}
        if request.tool == "db.delete_rows":
            conn.execute(f"DELETE FROM customers WHERE {where}", values)
        else:
            fields = sorted(request.changes)
            sets = ",".join(f'"{field}"=?' for field in fields)
            conn.execute(
                f"UPDATE customers SET {sets} WHERE {where}",
                [*(request.changes[f] for f in fields), *values],
            )
        return {"rows": []}

    def preview(self, request: OperationRequest, principal: AgentPrincipal, policy: Policy) -> dict:
        authorize(principal, request)
        started = time.monotonic()
        shadow = sqlite3.connect(":memory:", isolation_level=None)
        shadow.row_factory = sqlite3.Row
        try:
            with self.connection() as source:
                page_size = source.execute("PRAGMA page_size").fetchone()[0]

                def progress(_status, _remaining, total):
                    if total * page_size > policy.max_snapshot_bytes:
                        raise DomainError("PREVIEW_UNSUPPORTED", "快照超过大小限制。", 413)
                    if (time.monotonic() - started) * 1000 > policy.preview_timeout_ms:
                        raise DomainError(
                            "PREVIEW_TIMEOUT", "预检超时，未修改目标数据。", 503, True
                        )

                source.backup(shadow, pages=64, progress=progress, sleep=0.01)
            shadow.execute("PRAGMA foreign_keys=ON")
            shadow.execute("PRAGMA trusted_schema=OFF")
            shadow.enable_load_extension(False)
            deadline = started + policy.preview_timeout_ms / 1000
            shadow.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            schema = self._schema(shadow)
            before = self._state(shadow, policy)
            where, values = self._where(request)
            matched = shadow.execute(
                f"SELECT id,is_test FROM customers WHERE {where}", values
            ).fetchall()
            result = self._apply(shadow, request)
            after = self._state(shadow, policy)
            changes = logical_diff(before, after, request.table)
            if time.monotonic() > deadline:
                raise DomainError("PREVIEW_TIMEOUT", "预检超时，未修改目标数据。", 503, True)
            return {
                "coverage": "exact_on_snapshot",
                "adapter_version": ADAPTER_VERSION,
                "schema_digest": schema,
                "before_state_digest": digest(before),
                "after_state_digest": digest(after),
                "diff_digest": digest(changes),
                "changes": changes,
                "matched_records": len(matched),
                "non_test_matches": sum(1 for row in matched if not row["is_test"]),
                "direct_changes": sum(c["scope"] == "direct" for c in changes),
                "cascaded_changes": sum(c["scope"] == "cascade" for c in changes),
                "total_changes": len(changes),
                "query_result": result["rows"],
                "snapshot_at": now_ms(),
                "preview_ms": int((time.monotonic() - started) * 1000),
                "covered_tables": list(BUSINESS_TABLES),
                "redacted_fields": ["customers.email"],
                "recovery_status": "not_configured",
                "limitations": [
                    "仅覆盖当前 SQLite 快照的受管业务表。",
                    "任何受管数据变化都会使计划失效。",
                    "未配置备份恢复；不宣称可自动回滚。",
                ],
            }
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise DomainError(
                    "PREVIEW_TIMEOUT", "预检超时，未修改目标数据。", 503, True
                ) from exc
            raise DomainError("PREVIEW_FAILED", "预检失败，未修改目标数据。", 503) from exc
        finally:
            shadow.close()

    def lookup_receipt(self, operation_id: str, plan_digest: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT plan_digest,payload FROM execution_receipts WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                return None
            if not hmac.compare_digest(row["plan_digest"], plan_digest):
                raise DomainError("RECEIPT_CONFLICT", "操作回执与计划不一致，需要人工核实。", 409)
            return json.loads(row["payload"])

    def execute(self, plan: dict, permit: dict, signature: str, policy: Policy) -> dict:
        from airlock.plans import validate_plan

        payload = validate_plan(plan)
        expected_keys = {"operation_id", "plan_digest", "issued_at", "expires_at"}
        if set(permit) != expected_keys or not hmac.compare_digest(
            sign(permit, self.secret), signature
        ):
            raise DomainError("INVALID_PERMIT", "执行许可无效。", 403)
        if (
            permit["operation_id"] != payload["operation_id"]
            or permit["plan_digest"] != plan["plan_digest"]
        ):
            raise DomainError("INVALID_PERMIT", "执行许可不匹配。", 403)
        if type(permit["expires_at"]) is not int or type(permit["issued_at"]) is not int:
            raise DomainError("INVALID_PERMIT", "执行许可时间无效。", 403)
        if (
            not permit["issued_at"] <= now_ms() + 1000
            or permit["expires_at"] - permit["issued_at"] > 30000
        ):
            raise DomainError("INVALID_PERMIT", "执行许可时间无效。", 403)
        if now_ms() >= min(permit["expires_at"], payload["expires_at"]):
            raise DomainError("PLAN_EXPIRED", "计划或执行许可已过期。", 409)
        if (
            payload["policy_hash"] != policy_hash(policy)
            or payload["adapter_version"] != ADAPTER_VERSION
        ):
            raise DomainError("POLICY_CHANGED", "策略或适配器已变化，需要重新预检。", 409)
        request = OperationRequest.model_validate(payload["request"])
        principal = AgentPrincipal.model_validate(
            {**payload["principal"], "token_sha256": "0" * 64}
        )
        authorize(principal, request)
        from airlock.policy import decide

        decision, _ = decide(request, payload["preview"], policy)
        if decision == "block":
            raise DomainError("EXECUTION_BLOCKED", "禁止执行此计划。", 403)
        with self.connection(writable=True) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT plan_digest,payload FROM execution_receipts WHERE operation_id=?",
                    (payload["operation_id"],),
                ).fetchone()
                if existing:
                    if existing["plan_digest"] != plan["plan_digest"]:
                        raise DomainError("RECEIPT_CONFLICT", "执行回执冲突。", 409)
                    conn.rollback()
                    return json.loads(existing["payload"])
                deadline = time.monotonic() + policy.preview_timeout_ms / 1000
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                schema = self._schema(conn)
                before = self._state(conn, policy)
                expected = payload["preview"]
                if (
                    schema != expected["schema_digest"]
                    or digest(before) != expected["before_state_digest"]
                ):
                    raise DomainError(
                        "TARGET_STALE", "目标数据已变化，旧计划不会执行。请重新预检。", 409
                    )
                if now_ms() >= min(permit["expires_at"], payload["expires_at"]):
                    raise DomainError("PLAN_EXPIRED", "计划已过期，未产生新变更。", 409)
                result = self._apply(conn, request)
                after = self._state(conn, policy)
                changes = logical_diff(before, after, request.table)
                if (
                    digest(after) != expected["after_state_digest"]
                    or digest(changes) != expected["diff_digest"]
                ):
                    raise DomainError(
                        "EFFECT_MISMATCH", "实际影响与批准计划不一致，事务已回滚。", 409
                    )
                if (
                    now_ms() >= min(permit["expires_at"], payload["expires_at"])
                    or time.monotonic() > deadline
                ):
                    raise DomainError("PLAN_EXPIRED", "执行超出有效窗口，事务已回滚。", 409)
                receipt = {
                    "operation_id": payload["operation_id"],
                    "plan_digest": plan["plan_digest"],
                    "committed_at": now_ms(),
                    "tool": request.tool,
                    "rows": result["rows"],
                    "changed_records": len(changes),
                    "business_state_digest": digest(after),
                    "direct_changes": expected["direct_changes"],
                    "cascaded_changes": expected["cascaded_changes"],
                }
                self._insert_receipt(conn, receipt)
                conn.commit()
                return receipt
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _insert_receipt(conn: sqlite3.Connection, receipt: dict) -> None:
        conn.execute(
            "INSERT INTO execution_receipts VALUES (?,?,?,?)",
            (
                receipt["operation_id"],
                receipt["plan_digest"],
                canonical(receipt),
                receipt["committed_at"],
            ),
        )

    def inspect(self, policy: Policy) -> dict:
        with self.connection() as conn:
            schema = self._schema(conn)
            state = self._state(conn, policy)
            return {
                "resource_id": "demo",
                "engine": "SQLite",
                "adapter_version": ADAPTER_VERSION,
                "schema_digest": schema,
                "counts": {k: len(v) for k, v in state.items()},
                "capabilities": [
                    "snapshot_preview",
                    "state_revalidation",
                    "transactional_receipts",
                ],
                "recovery_status": "not_configured",
            }
