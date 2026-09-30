"""The only module allowed to mutate the target database.

Preview writes an in-memory backup, never the live database. Execution checks the
approved business snapshot, compares the actual logical diff, and writes a receipt
in the same transaction. Supports only the schema below, not arbitrary SQLite.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import time
from typing import Any

from .common import AirlockError, canonical, digest, now, verify
from .contracts import ToolRequest
from .plans import validate_plan

SCHEMA = """
CREATE TABLE customers (
 id INTEGER PRIMARY KEY,
 project TEXT NOT NULL,
 name TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('active','archived','paused')),
 is_test INTEGER NOT NULL CHECK(is_test IN (0,1)),
 tag TEXT NOT NULL DEFAULT '',
 version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE customer_notes (
 id INTEGER PRIMARY KEY,
 customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
 body TEXT NOT NULL
);
CREATE TABLE execution_receipts (
 operation_id TEXT PRIMARY KEY,
 plan_digest TEXT NOT NULL,
 result_json TEXT NOT NULL,
 committed_at REAL NOT NULL
);
"""
BUSINESS_TABLES = ("customers", "customer_notes")


def schema_rows(conn: sqlite3.Connection) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]


def expected_schema() -> list[tuple]:
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(SCHEMA)
        return schema_rows(conn)


EXPECTED_SCHEMA = expected_schema()


def initialize_target(path: Path, count: int = 1206) -> None:
    """Create-only fixture setup. Never reset a live database through the HTTP API."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise AirlockError("TARGET_EXISTS", "目标数据库已存在；初始化不会覆盖。")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?)", [
            (i, "demo", f"测试客户 {i:04d}" if i <= 12 else f"客户 {i:04d}",
             "active", 1 if i <= 12 else 0, "", 0) for i in range(1, count + 1)])
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?)", [
            (count + i, "other", f"另一项目客户 {i}", "active", 0, "private", 0)
            for i in range(1, 4)])
        conn.executemany("INSERT INTO customer_notes VALUES (?,?,?)", [
            (i * 2 + j, i, f"合成备注 {i}-{j}")
            for i in range(1, min(count, 6) + 1) for j in (0, 1)])
        conn.commit()
    path.chmod(0o600)


class TargetStore:
    def __init__(self, path: Path, secret: str, *, max_rows: int = 10000,
                 max_bytes: int = 16 * 1024 * 1024, timeout: float = 5.0,
                 lock_timeout: float = 1.0, clock=now):
        self.path = path.resolve()
        self.secret = secret
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.timeout, self.lock_timeout, self.clock = timeout, lock_timeout, clock

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if not self.path.is_file():
            raise AirlockError("TARGET_UNAVAILABLE", "受控目标不可用。", 503)
        mode = "ro" if readonly else "rw"
        conn = sqlite3.connect(self.path.as_uri() + f"?mode={mode}", uri=True,
                               timeout=self.lock_timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        if readonly:
            conn.execute("PRAGMA query_only=ON")
        return conn

    def inspect(self, conn: sqlite3.Connection) -> str:
        rows = schema_rows(conn)
        if rows != EXPECTED_SCHEMA:
            raise AirlockError("UNSUPPORTED_SCHEMA", "检测到不受支持的 Schema、表或触发器，停止操作。", 422)
        return digest(rows)

    def snapshot(self, conn: sqlite3.Connection, deadline: float) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        total = 0
        for table in BUSINESS_TABLES:
            # table names are constants, not request input.
            data = [dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY id LIMIT ?',
                                                 (self.max_rows + 1,))]
            total += len(data)
            if total > self.max_rows:
                raise AirlockError("PREVIEW_LIMIT", "数据超出完整预检范围，不执行截断预览。", 422)
            result[table] = data
            self.check_deadline(deadline)
        try:
            encoded = canonical(result).encode()
        except (TypeError, ValueError) as exc:
            raise AirlockError("UNSUPPORTED_DATA", "目标包含不受支持的数据类型。", 422) from exc
        if len(encoded) > self.max_bytes:
            raise AirlockError("PREVIEW_LIMIT", "数据大小超出预检范围。", 422)
        return result

    @staticmethod
    def changes(before: dict, after: dict, direct_table: str = "customers") -> list[dict]:
        changes: list[dict] = []
        for table in BUSINESS_TABLES:
            a = {row["id"]: row for row in before[table]}
            b = {row["id"]: row for row in after[table]}
            for key in sorted(a.keys() | b.keys()):
                left, right = a.get(key), b.get(key)
                if left != right:
                    changes.append({"table": table, "id": key, "before": left, "after": right,
                                    "kind": "insert" if left is None else "delete" if right is None else "update",
                                    "origin": "direct" if table == direct_table else "cascade"})
        return changes

    @staticmethod
    def where(request: ToolRequest, scope: str) -> tuple[str, list[Any]]:
        parts, params = ['"project" = ?'], [scope]
        operators = {"eq": "=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        for condition in request.filters:
            # Condition.field has a closed Literal schema, values are ALWAYS bound.
            field = f'"{condition.field}"'
            if condition.op == "in":
                values = condition.value
                assert isinstance(values, list)
                parts.append(f'{field} IN ({",".join("?" for _ in values)})')
                params.extend(values)
            else:
                parts.append(f"{field} {operators[condition.op]} ?")
                params.append(condition.value)
        return " AND ".join(parts), params

    def apply(self, conn: sqlite3.Connection, request: ToolRequest, scope: str) -> dict | None:
        if not scope or len(scope) > 80:
            raise AirlockError("SCOPE_REQUIRED", "缺少有效的数据范围。", 403)
        where, params = self.where(request, scope)
        if request.tool == "db.query_rows":
            columns = ",".join(f'"{c}"' for c in request.columns)
            rows = [dict(r) for r in conn.execute(
                f'SELECT {columns} FROM customers WHERE {where} ORDER BY id LIMIT ?',
                (*params, request.limit + 1))]
            return {"rows": rows[:request.limit], "returned": min(len(rows), request.limit),
                    "truncated": len(rows) > request.limit}
        if request.tool == "db.delete_rows":
            conn.execute(f"DELETE FROM customers WHERE {where}", params)
        else:
            fields = sorted(request.values)
            assignments = ",".join(f'"{key}" = ?' for key in fields)
            conn.execute(f"UPDATE customers SET {assignments},version=version+1 WHERE {where}",
                         [request.values[k] for k in fields] + params)
        return None

    @staticmethod
    def check_deadline(deadline: float) -> None:
        if time.monotonic() > deadline:
            raise AirlockError("PREVIEW_TIMEOUT", "完整预检超时，未执行变更。", 503)

    def preview(self, request_data: dict, scope: str) -> dict:
        request = ToolRequest.model_validate(request_data)
        started = time.monotonic()
        deadline = started + self.timeout
        with closing(self.connect(readonly=True)) as source, closing(sqlite3.connect(":memory:", isolation_level=None)) as shadow:
            pages = source.execute("PRAGMA page_count").fetchone()[0]
            page_size = source.execute("PRAGMA page_size").fetchone()[0]
            if pages * page_size > self.max_bytes:
                raise AirlockError("PREVIEW_LIMIT", "目标文件超出受支持大小。", 422)
            def progress(status: int, remaining: int, total: int) -> None:
                self.check_deadline(deadline)
                if total * page_size > self.max_bytes:
                    raise AirlockError("PREVIEW_LIMIT", "备份期间目标增长超出限制。", 422)
            source.backup(shadow, pages=128, progress=progress, sleep=0.01)
            shadow.row_factory = sqlite3.Row
            shadow.execute("PRAGMA foreign_keys=ON")
            shadow.execute("PRAGMA trusted_schema=OFF")
            shadow.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            schema = self.inspect(shadow)
            before = self.snapshot(shadow, deadline)
            shadow.execute("BEGIN")
            result = self.apply(shadow, request, scope)
            after = self.snapshot(shadow, deadline)
            changes = self.changes(before, after)
            shadow.rollback()
        self.check_deadline(deadline)
        return {"coverage": "exact_on_snapshot", "schema_digest": schema,
                "state_digest": digest(before), "changes_digest": digest(changes), "changes": changes,
                "direct_changed": sum(c["origin"] == "direct" for c in changes),
                "cascade_changed": sum(c["origin"] == "cascade" for c in changes),
                "total_changed": len(changes), "query_result": result, "created_at": self.clock(),
                "preview_ms": round((time.monotonic() - started) * 1000, 3),
                "recovery_status": "not_configured", "limitations": [
                    "仅覆盖注册 SQLite Schema；不是任意 SQL 沙箱。",
                    "执行前复核全部受管业务数据；无关数据变化也会使计划失效。",
                    "未验证业务恢复方案；不承诺自动回滚。"]}

    def lookup_receipt(self, operation_id: str, plan_digest: str) -> dict | None:
        with closing(self.connect(readonly=True)) as conn:
            self.inspect(conn)
            row = conn.execute("SELECT plan_digest,result_json FROM execution_receipts WHERE operation_id=?",
                               (operation_id,)).fetchone()
            if row:
                if row["plan_digest"] != plan_digest:
                    raise AirlockError("RECEIPT_CONFLICT", "执行回执与当前计划不匹配。")
                return __import__("json").loads(row["result_json"])
            return None

    def execute_once(self, envelope: dict) -> dict:
        plan, permit, signature = envelope["plan"], envelope["permit"], envelope["signature"]
        validate_plan(plan)
        if (not verify(permit, signature, self.secret)
                or permit.get("plan_digest") != plan["plan_digest"]
                or permit.get("operation_id") != plan["operation_id"]
                or permit.get("not_after", float("inf")) > plan["expires_at"]):
            raise AirlockError("INVALID_PERMIT", "缺少合法执行许可。", 403)
        request = ToolRequest.model_validate(plan["request"])
        deadline = time.monotonic() + self.timeout
        with closing(self.connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT plan_digest,result_json FROM execution_receipts WHERE operation_id=?",
                                   (plan["operation_id"],)).fetchone()
                if row:
                    if row["plan_digest"] != plan["plan_digest"]:
                        raise AirlockError("RECEIPT_CONFLICT", "执行回执冲突。")
                    conn.rollback()
                    return __import__("json").loads(row["result_json"])
                if self.clock() >= min(plan["expires_at"], permit["not_after"]):
                    raise AirlockError("EXPIRED", "执行许可已过期，未产生新的变更。")
                if digest(schema_rows(conn)) != plan["schema_digest"]:
                    raise AirlockError("STALE", "目标 Schema 已改变，请重新预检。")
                self.inspect(conn)
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                before = self.snapshot(conn, deadline)
                if digest(before) != plan["state_digest"]:
                    raise AirlockError("STALE", "目标数据已变化，旧批准不能继续执行。")
                result = self.apply(conn, request, plan["scope"])
                after = self.snapshot(conn, deadline)
                actual = self.changes(before, after)
                if digest(actual) != plan["facts"]["changes_digest"]:
                    raise AirlockError("DIFF_MISMATCH", "实际变更与批准预览不一致，已回滚。")
                receipt = {"operation_id": plan["operation_id"], "plan_digest": plan["plan_digest"],
                           "committed_at": self.clock(), "total_changed": len(actual),
                           "direct_changed": sum(c["origin"] == "direct" for c in actual),
                           "cascade_changed": sum(c["origin"] == "cascade" for c in actual),
                           "state_after": digest(after), "query_result": result}
                conn.execute("INSERT INTO execution_receipts VALUES (?,?,?,?)",
                             (plan["operation_id"], plan["plan_digest"], canonical(receipt), receipt["committed_at"]))
                conn.commit()
                return receipt
            except Exception:
                conn.rollback()
                raise
