"""SQLite's compiler is the enforcement point, not a keyword filter.

Only a fixed synthetic customers table is supported. This is NOT a sandbox for
arbitrary SQL databases, extensions, triggers, stored procedures or shell code.
"""
from __future__ import annotations
import math
import sqlite3
import time
from contextlib import contextmanager
from .models import Invocation, canonical, digest

SCHEMA = """CREATE TABLE customers (
 id INTEGER PRIMARY KEY CHECK(id > 0 AND id <= 9007199254740991),
 name TEXT NOT NULL CHECK(length(name) <= 100),
 tier TEXT NOT NULL CHECK(tier IN ('standard','premium')),
 balance INTEGER NOT NULL CHECK(balance >= 0 AND balance <= 1000000000)
) STRICT"""
MAX_ROWS = 5000
FUNCTIONS = {"count", "sum", "min", "max", "avg", "coalesce", "ifnull", "nullif",
             "lower", "upper", "length", "abs", "round", "like", "glob", "substr", "typeof"}
WRITE_CODES = {sqlite3.SQLITE_INSERT: "insert", sqlite3.SQLITE_UPDATE: "update",
               sqlite3.SQLITE_DELETE: "delete"}


@contextmanager
def restricted(conn: sqlite3.Connection):
    operations: set[str] = set()
    deadline = time.monotonic() + 0.25

    def authorize(code, a, b, database, trigger):
        if database not in (None, "main"):
            return sqlite3.SQLITE_DENY
        if code == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if code == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if (b or "").lower() in FUNCTIONS else sqlite3.SQLITE_DENY
        if code in (sqlite3.SQLITE_READ, *WRITE_CODES):
            if a != "customers":
                return sqlite3.SQLITE_DENY
            if code in WRITE_CODES:
                if code == sqlite3.SQLITE_UPDATE and b == "id":
                    return sqlite3.SQLITE_DENY
                if trigger:
                    return sqlite3.SQLITE_DENY
                operations.add(WRITE_CODES[code])
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    limits = {sqlite3.SQLITE_LIMIT_LENGTH: 100_000, sqlite3.SQLITE_LIMIT_SQL_LENGTH: 5000,
              sqlite3.SQLITE_LIMIT_COLUMN: 32, sqlite3.SQLITE_LIMIT_EXPR_DEPTH: 30,
              sqlite3.SQLITE_LIMIT_COMPOUND_SELECT: 5, sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER: 50}
    previous = {key: conn.setlimit(key, val) for key, val in limits.items()}
    conn.set_authorizer(authorize)
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        yield operations
    finally:
        conn.set_authorizer(None)
        conn.set_progress_handler(None, 0)
        for key, val in previous.items():
            conn.setlimit(key, val)


def classify(conn: sqlite3.Connection, call: Invocation) -> list[str]:
    if call.tool != "sql":
        raise ValueError("unsupported_tool")
    # execute() rejects stacked statements; EXPLAIN compiles without performing the action.
    with restricted(conn) as operations:
        conn.execute("EXPLAIN " + call.sql, call.parameters).fetchall()
    return sorted(operations)


def snapshot(conn: sqlite3.Connection) -> list[dict]:
    rows = [dict(row) for row in conn.execute("SELECT id,name,tier,balance FROM customers ORDER BY id LIMIT ?", (MAX_ROWS + 1,))]
    if len(rows) > MAX_ROWS:
        raise ValueError("demonstration dataset limit exceeded")
    return rows


def fingerprint(rows: list[dict]) -> str:
    return digest({"schema": SCHEMA, "rows": rows})


def json_value(value):
    if isinstance(value, bytes) or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("non-JSON result is unsupported")
    if isinstance(value, int) and abs(value) > 9007199254740991:
        return str(value)  # Preserve exact integers across browser JSON parsing.
    return value


def execute(conn: sqlite3.Connection, call: Invocation) -> dict:
    with restricted(conn) as operations:
        cur = conn.execute(call.sql, call.parameters)
        if cur.description and len({column[0] for column in cur.description}) != len(cur.description):
            cur.close()
            raise ValueError("duplicate result column names are unsupported")
        rows = cur.fetchmany(101) if cur.description else []
        result = {"matched_rows": max(cur.rowcount, 0), "rows": [{key: json_value(r[key]) for key in r.keys()} for r in rows[:100]],
                  "truncated": len(rows) > 100}
        cur.close()
    # RETURNING rowcount may remain -1 until the cursor is finalized.
    if operations:
        result["matched_rows"] = conn.execute("SELECT changes()").fetchone()[0]
    if len(canonical(result).encode()) > 64000:
        raise ValueError("result exceeds the 64KB response budget")
    return result


def preview(conn: sqlite3.Connection, call: Invocation, operations: list[str]) -> dict:
    before = snapshot(conn)
    clone = sqlite3.connect(":memory:", isolation_level=None, cached_statements=0)
    clone.row_factory = sqlite3.Row
    try:
        clone.execute(SCHEMA)
        clone.executemany("INSERT INTO customers VALUES (:id,:name,:tier,:balance)", before)
        clone.execute("BEGIN")
        result = execute(clone, call)
        after = snapshot(clone)
        clone.execute("ROLLBACK")
    finally:
        clone.close()
    a, b = {r["id"]: r for r in before}, {r["id"]: r for r in after}
    ids = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
    return {
        "certainty": "snapshot_exact", "is_estimate": False,
        "before_count": len(before), "after_count": len(after),
        "matched_rows": result["matched_rows"], "changed_rows": len(ids),
        "operations": operations, "before_hash": fingerprint(before), "after_hash": fingerprint(after),
        "sample": [{"id": k, "before": a.get(k), "after": b.get(k)} for k in ids[:5]],
        "sample_truncated": len(ids) > 5,
        "recovery": "No automatic undo after commit. A verified restore or compensating action is required.",
        "backup_age_seconds": None,
    }
