"""SQLAlchemy Core schema and short serialized metadata transactions.

There is no distributed transaction with the target. Jobs and authorization events
are committed here before execution; target receipts reconcile the second database.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from sqlalchemy import (Boolean, Column, Float, ForeignKey, Integer, MetaData, String,
                        Table, Text, UniqueConstraint, create_engine, event, select)
from sqlalchemy.engine import Connection
from .common import AirlockError, canonical, digest, now

metadata = MetaData()
schema_version = Table("schema_version", metadata, Column("version", Integer, primary_key=True))
principals = Table("principals", metadata,
    Column("id", String, primary_key=True), Column("kind", String, nullable=False),
    Column("scope", String, nullable=False), Column("active", Boolean, nullable=False, default=True),
    Column("version", Integer, nullable=False, default=1),
    Column("tools_json", Text, nullable=False, default='["db.query_rows","db.update_rows","db.delete_rows"]'), Column("username", String, unique=True),
    Column("password_hash", Text), Column("token_hash", String, unique=True),
    Column("created_at", Float, nullable=False))
sessions = Table("sessions", metadata,
    Column("token_hash", String, primary_key=True),
    Column("principal_id", String, ForeignKey("principals.id"), nullable=False),
    Column("auth_version", Integer, nullable=False), Column("csrf", String, nullable=False),
    Column("expires_at", Float, nullable=False))
rate_limits = Table("rate_limits", metadata,
    Column("key", String, primary_key=True), Column("started_at", Float, nullable=False),
    Column("count", Integer, nullable=False))
operations = Table("operations", metadata,
    Column("id", String, primary_key=True),
    Column("principal_id", String, ForeignKey("principals.id"), nullable=False),
    Column("scope", String, nullable=False), Column("auth_version", Integer, nullable=False), Column("tool", String, nullable=False),
    Column("idempotency_key", String, nullable=False), Column("request_digest", String, nullable=False),
    Column("request_json", Text, nullable=False), Column("state", String, nullable=False),
    Column("decision", String), Column("reason_code", String),
    Column("version", Integer, nullable=False, default=1),
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False), Column("plan_json", Text),
    Column("summary_json", Text), Column("permit_json", Text), Column("result_json", Text),
    Column("error_json", Text), UniqueConstraint("principal_id", "idempotency_key"))
jobs = Table("jobs", metadata,
    Column("id", String, primary_key=True), Column("operation_id", String, ForeignKey("operations.id"), nullable=False),
    Column("kind", String, nullable=False), Column("status", String, nullable=False),
    Column("available_at", Float, nullable=False), Column("lease_owner", String),
    Column("lease_until", Float, nullable=False, default=0),
    Column("revision", Integer, nullable=False, default=0), Column("attempts", Integer, nullable=False, default=0),
    UniqueConstraint("operation_id", "kind"))
approvals = Table("approvals", metadata,
    Column("operation_id", String, ForeignKey("operations.id"), primary_key=True),
    Column("principal_id", String, ForeignKey("principals.id"), nullable=False),
    Column("principal_version", Integer, nullable=False), Column("decision_key", String, nullable=False),
    Column("body_digest", String, nullable=False), Column("decision", String, nullable=False),
    Column("reason", Text, nullable=False), Column("plan_digest", String, nullable=False),
    Column("view_digest", String, nullable=False), Column("view_json", Text, nullable=False),
    Column("created_at", Float, nullable=False))
review_views = Table("review_views", metadata,
    Column("id", String, primary_key=True), Column("operation_id", String, ForeignKey("operations.id"), nullable=False),
    Column("session_hash", String, nullable=False), Column("principal_id", String, nullable=False),
    Column("view_digest", String, nullable=False), Column("created_at", Float, nullable=False),
    UniqueConstraint("operation_id", "session_hash", "view_digest"))
audit_events = Table("audit_events", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("operation_id", String, ForeignKey("operations.id"), nullable=False),
    Column("scope", String, nullable=False), Column("requester", String, nullable=False),
    Column("ordinal", Integer, nullable=False), Column("event_type", String, nullable=False),
    Column("at", Float, nullable=False), Column("data_json", Text, nullable=False),
    Column("prev_hash", String, nullable=False), Column("event_hash", String, nullable=False),
    UniqueConstraint("operation_id", "ordinal"))
telemetry = Table("telemetry", metadata,
    Column("event_id", String, primary_key=True), Column("operation_id", String, ForeignKey("operations.id"), nullable=False),
    Column("principal_id", String, nullable=False), Column("payload_json", Text, nullable=False),
    Column("received_at", Float, nullable=False))


class Store:
    def __init__(self, path: Path, *, clock=now):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.engine = create_engine(f"sqlite:///{self.path}", connect_args={"check_same_thread": False, "timeout": 5})
        @event.listens_for(self.engine, "connect")
        def configure(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")

    def initialize(self) -> None:
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        from alembic.config import Config
        from alembic import command
        from sqlalchemy import inspect
        existing=set(inspect(self.engine).get_table_names())
        if existing and "alembic_version" not in existing:
            raise AirlockError("SCHEMA_VERSION", "未识别的旧元数据库；不能自动覆盖或冒充已迁移。", 503)
        config=Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        with self.engine.begin() as conn:
            config.attributes["connection"]=conn
            command.upgrade(config, "head")
        self.verify_schema()
        self.path.chmod(0o600)

    def verify_schema(self) -> None:
        try:
            with self.engine.connect() as conn:
                versions=list(conn.execute(select(schema_version.c.version)).scalars())
                migration=conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            if versions != [1] or migration != "0001": raise ValueError("unsupported schema")
        except Exception as exc:
            raise AirlockError("SCHEMA_VERSION", "元数据库版本不受支持；停止启动，不能自动覆盖。", 503) from exc

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def row(conn: Connection, table: Table, condition) -> dict | None:
        record = conn.execute(select(table).where(condition)).mappings().first()
        return dict(record) if record else None

    def audit(self, conn: Connection, op: dict, event_type: str, data: dict | None = None) -> None:
        last = conn.execute(select(audit_events.c.ordinal, audit_events.c.event_hash)
                            .where(audit_events.c.operation_id == op["id"])
                            .order_by(audit_events.c.ordinal.desc()).limit(1)).first()
        body = {"operation_id": op["id"], "ordinal": last[0]+1 if last else 1,
                "event_type": event_type, "at": self.clock(), "data": data or {},
                "prev_hash": last[1] if last else "0"*64}
        conn.execute(audit_events.insert().values(
            operation_id=op["id"], scope=op["scope"], requester=op["principal_id"],
            ordinal=body["ordinal"], event_type=event_type, at=body["at"],
            data_json=canonical(body["data"]), prev_hash=body["prev_hash"], event_hash=digest(body)))

    def close(self) -> None:
        self.engine.dispose()
