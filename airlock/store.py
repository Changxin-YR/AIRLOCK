"""Business effect, status and audit share ONE SQLite transaction in this MVP."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import contextmanager
from .models import Settings, canonical, digest
from .sql import SCHEMA

DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actions(
 id TEXT PRIMARY KEY, principal TEXT NOT NULL, idem TEXT NOT NULL, request_hash TEXT NOT NULL,
 state TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, document TEXT NOT NULL,
 UNIQUE(principal, idem)
);
CREATE TABLE IF NOT EXISTS audit(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, action_id TEXT NOT NULL,
 previous_hash TEXT NOT NULL, event TEXT NOT NULL, signature TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_action ON audit(action_id, seq);
CREATE INDEX IF NOT EXISTS pending_expiry ON actions(state, expires);
CREATE INDEX IF NOT EXISTS action_admission ON actions(principal, created);
"""


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(settings.database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(DDL)
            conn.execute("BEGIN IMMEDIATE")
            try:
                if not conn.execute("SELECT 1 FROM meta WHERE key='seeded'").fetchone():
                    conn.execute(SCHEMA)
                    conn.executemany("INSERT INTO customers VALUES (?,?,?,?)", [
                        (i, f"Synthetic customer {i:04d}", "premium" if i % 5 == 0 else "standard", 1000)
                        for i in range(1, settings.seed_rows + 1)])
                    conn.execute("INSERT INTO meta VALUES ('seeded','v1')")
                schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='customers' AND type='table'").fetchone()
                if not schema or schema[0] != SCHEMA:
                    raise ValueError("unsupported target schema; migration or a fresh demo database is required")
                key_id = digest(settings.audit_key)
                old = conn.execute("SELECT value FROM meta WHERE key='audit_key_id'").fetchone()
                if old and old[0] != key_id:
                    raise ValueError("audit key changed; explicit migration is required")
                conn.execute("INSERT OR IGNORE INTO meta VALUES ('audit_key_id',?)", (key_id,))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        settings.database.chmod(0o600)

    @contextmanager
    def connection(self):
        # Statement caching is disabled: every untrusted statement gets authorized again.
        conn = sqlite3.connect(self.settings.database, isolation_level=None, timeout=3, cached_statements=0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA trusted_schema=OFF")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _signature(self, seq: int, action_id: str, previous: str, event: dict) -> str:
        envelope = canonical({"seq": seq, "action_id": action_id,
                              "previous_hash": previous, "event": event})
        return hmac.new(self.settings.audit_key.encode(), envelope.encode(), hashlib.sha256).hexdigest()

    def audit(self, conn, action_id: str, event: dict) -> None:
        tail = conn.execute("SELECT seq,signature FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous, seq = (tail["signature"], tail["seq"] + 1) if tail else ("0" * 64, 1)
        signature = self._signature(seq, action_id, previous, event)
        conn.execute("INSERT INTO audit(seq,action_id,previous_hash,event,signature) VALUES(?,?,?,?,?)",
                     (seq, action_id, previous, canonical(event), signature))

    @staticmethod
    def save(conn, action: dict) -> None:
        conn.execute("UPDATE actions SET state=?,document=? WHERE id=?",
                     (action["state"], canonical(action), action["id"]))

    def verify_audit(self) -> dict:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM audit ORDER BY seq").fetchall()
        previous = "0" * 64
        valid = True
        for row in rows:
            try:
                signature = self._signature(row["seq"], row["action_id"], previous, json.loads(row["event"]))
            except (ValueError, TypeError):
                return {"valid": False, "events": len(rows), "head": previous, "limitation": "Malformed audit event."}
            valid &= row["previous_hash"] == previous and hmac.compare_digest(signature, row["signature"])
            previous = row["signature"]
        return {"valid": bool(valid), "events": len(rows), "head": previous,
                "limitation": "No external anchor: tail truncation and a compromised server are not detectable."}

    def audit_events(self, action_id: str | None = None, after: int = 0, limit: int = 200) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit WHERE seq>? AND (? IS NULL OR action_id=?) ORDER BY seq LIMIT ?",
                (after, action_id, action_id, limit)).fetchall()
        return [{"seq": r["seq"], "action_id": r["action_id"], "event": json.loads(r["event"]),
                 "previous_hash": r["previous_hash"], "signature": r["signature"]} for r in rows]
