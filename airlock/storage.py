from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    select,
)
from sqlalchemy.pool import NullPool

from airlock.common import DomainError, canonical, digest, now_ms
from airlock.policy import REASONS

metadata = MetaData()
operations = Table(
    "operations",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("requester", String(80), nullable=False),
    Column("resource_id", String(64), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("request_json", Text, nullable=False),
    Column("state", String(32), nullable=False),
    Column("decision", String(24)),
    Column("reason_code", String(80)),
    Column("ready_source", String(16)),
    Column("version", Integer, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("plan_json", Text),
    Column("result_json", Text),
    Column("error_json", Text),
    UniqueConstraint("requester", "idempotency_key", name="uq_operation_idempotency"),
    CheckConstraint("version >= 1", name="ck_operation_version"),
)
jobs = Table(
    "jobs",
    metadata,
    Column("operation_id", String(32), ForeignKey("operations.id"), primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("state", String(16), nullable=False),
    Column("lease_token", String(32)),
    Column("lease_until", Integer, nullable=False, default=0),
    Column("attempts", Integer, nullable=False, default=0),
    Column("next_at", Integer, nullable=False, default=0),
    CheckConstraint("kind IN ('preview','execute','reconcile')", name="ck_job_kind"),
    CheckConstraint("state IN ('queued','leased','done')", name="ck_job_state"),
)
sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("username", String(64), nullable=False),
    Column("csrf", String(64), nullable=False),
    Column("reviewer_digest", String(64), nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False),
)
views = Table(
    "review_views",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("operation_id", String(32), ForeignKey("operations.id"), nullable=False),
    Column("session_hash", String(64), ForeignKey("sessions.token_hash"), nullable=False),
    Column("plan_digest", String(64), nullable=False),
    Column("view_digest", String(64), nullable=False),
    Column("view_json", Text, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False),
)
approvals = Table(
    "approvals",
    metadata,
    Column("operation_id", String(32), ForeignKey("operations.id"), primary_key=True),
    Column("username", String(64), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("reason", Text, nullable=False),
    Column("plan_digest", String(64), nullable=False),
    Column("view_digest", String(64), nullable=False),
    Column("view_id", String(32), ForeignKey("review_views.id"), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", Integer, nullable=False),
    UniqueConstraint("username", "idempotency_key", name="uq_approval_idempotency"),
    CheckConstraint("decision IN ('approve','reject')", name="ck_approval_decision"),
)
audit_events = Table(
    "audit_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("operation_id", String(32), ForeignKey("operations.id"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("kind", String(48), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("previous_hash", String(64), nullable=False),
    Column("event_hash", String(64), nullable=False),
    UniqueConstraint("operation_id", "seq", name="uq_audit_sequence"),
)
telemetry = Table(
    "telemetry",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("operation_id", String(32), ForeignKey("operations.id"), nullable=False),
    Column("view_id", String(32), ForeignKey("review_views.id"), nullable=False),
    Column("event", String(32), nullable=False),
    Column("visible_ms", Integer, nullable=False),
    Column("hidden", Boolean, nullable=False),
    Column("created_at", Integer, nullable=False),
)
login_limits = Table(
    "login_limits",
    metadata,
    Column("bucket", String(64), primary_key=True),
    Column("failures", Integer, nullable=False),
    Column("reset_at", Integer, nullable=False),
)
Index("ix_operations_queue", operations.c.state, operations.c.created_at)
Index("ix_jobs_ready", jobs.c.state, jobs.c.next_at)
Index("ix_audit_operation", audit_events.c.operation_id, audit_events.c.id)

TERMINAL = {"BLOCKED", "REJECTED", "EXPIRED", "CANCELLED", "SUCCEEDED", "STALE", "FAILED"}
EDGES = {
    "RECEIVED": {"PREVIEWING", "BLOCKED", "EXPIRED", "CANCELLED"},
    "PREVIEWING": {"RECEIVED", "READY", "PENDING_APPROVAL", "BLOCKED", "EXPIRED", "FAILED"},
    "PENDING_APPROVAL": {"READY", "REJECTED", "EXPIRED", "CANCELLED", "STALE"},
    "READY": {"EXECUTING", "EXPIRED", "CANCELLED", "STALE"},
    "EXECUTING": {"SUCCEEDED", "STALE", "FAILED", "UNKNOWN", "EXPIRED"},
    "UNKNOWN": {"SUCCEEDED"},
}


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            poolclass=NullPool,
            connect_args={"timeout": 3, "check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def setup(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
            dbapi_connection.execute("PRAGMA busy_timeout=3000")

    def migrate(self) -> None:
        from alembic import command
        from alembic.config import Config

        root = Path(__file__).resolve().parent.parent
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.path}".replace("%", "%%"))
        command.upgrade(config, "head")

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @contextmanager
    def read(self):
        with self.engine.connect() as conn:
            yield conn

    @staticmethod
    def get(conn, operation_id: str) -> dict:
        row = (
            conn.execute(select(operations).where(operations.c.id == operation_id))
            .mappings()
            .first()
        )
        if row is None:
            raise DomainError("NOT_FOUND", "操作不存在或无权访问。", 404)
        return dict(row)

    @staticmethod
    def transition(conn, operation: dict, state: str, **values) -> dict:
        if state not in EDGES.get(operation["state"], set()):
            raise DomainError("STATE_CONFLICT", "操作状态已变化，请刷新。", 409)
        patch = {
            "state": state,
            "version": operation["version"] + 1,
            "updated_at": now_ms(),
            **values,
        }
        result = conn.execute(
            operations.update()
            .where(
                operations.c.id == operation["id"],
                operations.c.version == operation["version"],
                operations.c.state == operation["state"],
            )
            .values(**patch)
        )
        if result.rowcount != 1:
            raise DomainError("STATE_CONFLICT", "操作状态已变化，请刷新。", 409)
        return {**operation, **patch}

    @staticmethod
    def audit(conn, operation_id: str, kind: str, payload: dict) -> None:
        last = conn.execute(
            select(audit_events.c.seq, audit_events.c.event_hash)
            .where(audit_events.c.operation_id == operation_id)
            .order_by(audit_events.c.seq.desc())
            .limit(1)
        ).first()
        seq, previous = (last[0] + 1, last[1]) if last else (1, "0" * 64)
        created = now_ms()
        envelope = {
            "operation_id": operation_id,
            "seq": seq,
            "kind": kind,
            "payload": payload,
            "created_at": created,
            "previous_hash": previous,
        }
        conn.execute(
            audit_events.insert().values(
                operation_id=operation_id,
                seq=seq,
                kind=kind,
                payload_json=canonical(payload),
                created_at=created,
                previous_hash=previous,
                event_hash=digest(envelope),
            )
        )

    @staticmethod
    def public(operation: dict) -> dict[str, Any]:
        request = json.loads(operation["request_json"])
        plan = json.loads(operation["plan_json"]) if operation["plan_json"] else None
        return {
            "id": operation["id"],
            "requester": operation["requester"],
            "resource_id": operation["resource_id"],
            "intent": request["intent"],
            "tool": request["tool"],
            "run_id": request["run_id"],
            "state": operation["state"],
            "decision": operation["decision"],
            "reason_code": operation["reason_code"],
            "ready_source": operation["ready_source"],
            "version": operation["version"],
            "created_at": operation["created_at"],
            "updated_at": operation["updated_at"],
            "expires_at": operation["expires_at"],
            "impact": plan["payload"]["preview"]["total_changes"] if plan else None,
            "plan_digest": plan["plan_digest"] if plan else None,
            "result": json.loads(operation["result_json"]) if operation["result_json"] else None,
            "error": json.loads(operation["error_json"]) if operation["error_json"] else None,
            "feedback": {
                "code": operation["reason_code"],
                "safe_message": REASONS.get(operation["reason_code"], "请根据操作状态继续处理。"),
                "next_action": {
                    "PENDING_APPROVAL": "wait_for_independent_human",
                    "UNKNOWN": "reconcile_do_not_resubmit",
                    "BLOCKED": "revise_within_permissions",
                    "REJECTED": "review_human_feedback",
                    "STALE": "create_new_plan",
                    "EXPIRED": "create_new_plan",
                    "SUCCEEDED": "use_receipt",
                    "CANCELLED": "stop",
                    "FAILED": "inspect_failure",
                }.get(operation["state"], "poll_existing_operation"),
            },
            "poll_after_ms": 1000 if operation["state"] not in TERMINAL else None,
        }

    def audit_log(self, operation_id: str) -> dict:
        with self.read() as conn:
            rows = (
                conn.execute(
                    select(audit_events)
                    .where(audit_events.c.operation_id == operation_id)
                    .order_by(audit_events.c.seq)
                )
                .mappings()
                .all()
            )
        valid, previous, events = True, "0" * 64, []
        for expected_seq, row in enumerate(rows, 1):
            payload = json.loads(row["payload_json"])
            envelope = {
                "operation_id": operation_id,
                "seq": row["seq"],
                "kind": row["kind"],
                "payload": payload,
                "created_at": row["created_at"],
                "previous_hash": row["previous_hash"],
            }
            valid &= (
                row["seq"] == expected_seq
                and row["previous_hash"] == previous
                and row["event_hash"] == digest(envelope)
            )
            previous = row["event_hash"]
            events.append({**envelope, "id": row["id"], "event_hash": row["event_hash"]})
        return {
            "events": events,
            "chain_valid": valid,
            "limitation": "本地摘要链仅用于一致性检查，不防拥有数据库写权限的管理员重写历史。",
        }
