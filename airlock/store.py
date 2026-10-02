"""Business effect, status and audit share ONE SQLite transaction in this MVP."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from .models import Settings, canonical, digest
from .sql import SCHEMA
from . import audit_keys
from . import telemetry

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
CREATE TABLE IF NOT EXISTS recovery_plans(source_id TEXT PRIMARY KEY, document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS risk_budget(action_id TEXT PRIMARY KEY, scope TEXT NOT NULL, window INTEGER NOT NULL, units INTEGER NOT NULL, state TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS budget_scope ON risk_budget(scope,window,state);
CREATE TABLE IF NOT EXISTS telemetry_outbox(seq INTEGER PRIMARY KEY,payload TEXT NOT NULL);
"""


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        telemetry.endpoint(settings)
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
                if 'key_id' not in {r[1] for r in conn.execute('PRAGMA table_info(audit)')}:
                    conn.execute("ALTER TABLE audit ADD COLUMN key_id TEXT NOT NULL DEFAULT 'legacy'")
                conn.execute("INSERT OR IGNORE INTO meta VALUES('database_instance',?)",(uuid.uuid4().hex,))
                conn.execute("INSERT OR IGNORE INTO meta VALUES('audit_active_key','legacy')")
                audit_keys.register(conn,settings)
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

    def _signature(self, seq: int, action_id: str, previous: str, event: dict,key_id='legacy') -> str:
        value={"seq":seq,"action_id":action_id,"previous_hash":previous,"event":event}
        if key_id!='legacy':value['key_id']=key_id
        key=audit_keys.keyring(self.settings)[key_id]
        return hmac.new(key.encode(),canonical(value).encode(),hashlib.sha256).hexdigest()

    def audit(self, conn, action_id: str, event: dict) -> None:
        keys=audit_keys.register(conn,self.settings)
        key_id=conn.execute("SELECT value FROM meta WHERE key='audit_active_key'").fetchone()[0]
        if key_id not in keys:raise ValueError('active audit key missing')
        tail = conn.execute("SELECT seq,signature FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous, seq = (tail["signature"], tail["seq"] + 1) if tail else ("0" * 64, 1)
        signature = self._signature(seq,action_id,previous,event,key_id)
        conn.execute("INSERT INTO audit(seq,action_id,previous_hash,event,signature,key_id) VALUES(?,?,?,?,?,?)",
                     (seq,action_id,previous,canonical(event),signature,key_id))
        if self.settings.otlp_url:telemetry.enqueue(conn,seq,action_id,event)

    @staticmethod
    def save(conn, action: dict) -> None:
        conn.execute("UPDATE actions SET state=?,document=? WHERE id=?",
                     (action["state"], canonical(action), action["id"]))

    def verify_audit(self,checkpoint=None) -> dict:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM audit ORDER BY seq").fetchall()
        previous = "0" * 64
        valid = True
        for expected,row in enumerate(rows,1):
            try:
                signature = self._signature(row["seq"],row["action_id"],previous,json.loads(row["event"]),row['key_id'])
            except (ValueError,TypeError,KeyError,OSError):
                return {"valid": False, "events": len(rows), "head": previous, "limitation": "Malformed audit event."}
            valid &= row['seq']==expected and row["previous_hash"] == previous and hmac.compare_digest(signature, row["signature"])
            previous = row["signature"]
        anchor_status='not_configured'
        try:
            if checkpoint is None and self.settings.audit_anchor_file:
                raw=self.settings.audit_anchor_file.read_text(encoding='utf-8')
                if len(raw.encode())>4096:raise ValueError('checkpoint size')
                checkpoint=json.loads(raw)
            if checkpoint is not None:
                anchor_status='verified' if self.verify_checkpoint(checkpoint,rows) else 'mismatch'
                valid &= anchor_status=='verified'
        except (ValueError,TypeError,KeyError,OSError):
            anchor_status='unavailable_or_invalid';valid=False
        return {"valid": bool(valid), "events": len(rows), "head": previous,
                'anchor_status':anchor_status,
                "limitation": "Tail truncation after the last independently retained checkpoint remains undetectable. A server with all keys can forge new history; keep checkpoints outside its write authority."}

    def rotate_key(self,key_id,now):
        with self.transaction() as conn:
            keys=audit_keys.register(conn,self.settings)
            if key_id not in keys:raise ValueError('unknown audit key ID')
            old=conn.execute("SELECT value FROM meta WHERE key='audit_active_key'").fetchone()[0]
            if old==key_id:return {'previous':old,'active':key_id,'changed':False}
            self.audit(conn,'governance:audit-keys',{'kind':'audit.key_rotated','at':now,'previous_key_id':old,'next_key_id':key_id})
            conn.execute("UPDATE meta SET value=? WHERE key='audit_active_key'",(key_id,))
            return {'previous':old,'active':key_id,'changed':True}

    def checkpoint(self):
        with self.connection() as conn:
            conn.execute('BEGIN')
            tail=conn.execute('SELECT seq,signature FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
            instance=conn.execute("SELECT value FROM meta WHERE key='database_instance'").fetchone()[0]
            key_id=conn.execute("SELECT value FROM meta WHERE key='audit_active_key'").fetchone()[0]
        body={'version':1,'database_instance':instance,'seq':tail['seq'] if tail else 0,
              'head':tail['signature'] if tail else '0'*64,'key_id':key_id}
        body['signature']=hmac.new(audit_keys.keyring(self.settings)[key_id].encode(),canonical(body).encode(),hashlib.sha256).hexdigest()
        return body

    def verify_checkpoint(self,checkpoint,rows):
        if not isinstance(checkpoint,dict) or set(checkpoint)!={'version','database_instance','seq','head','key_id','signature'}:return False
        if checkpoint['version']!=1 or type(checkpoint['seq']) is not int or not 0<=checkpoint['seq']<=len(rows):return False
        with self.connection() as conn:
            instance=conn.execute("SELECT value FROM meta WHERE key='database_instance'").fetchone()[0]
        body={k:v for k,v in checkpoint.items() if k!='signature'}
        signature=hmac.new(audit_keys.keyring(self.settings)[checkpoint['key_id']].encode(),canonical(body).encode(),hashlib.sha256).hexdigest()
        head=rows[checkpoint['seq']-1]['signature'] if checkpoint['seq'] else '0'*64
        return instance==checkpoint['database_instance'] and head==checkpoint['head'] and hmac.compare_digest(signature,checkpoint['signature'])

    def audit_events(self, action_id: str | None = None, after: int = 0, limit: int = 200) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit WHERE seq>? AND (? IS NULL OR action_id=?) ORDER BY seq LIMIT ?",
                (after, action_id, action_id, limit)).fetchall()
        return [{"seq": r["seq"], "action_id": r["action_id"], "event": json.loads(r["event"]),
                 "previous_hash": r["previous_hash"], "signature": r["signature"],'key_id':r['key_id']} for r in rows]
