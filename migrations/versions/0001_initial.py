"""Frozen initial SQLite metadata schema; deliberately independent of current app models."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
    "\nCREATE TABLE login_limits (\n\tbucket VARCHAR(64) NOT NULL, \n\tfailures INTEGER NOT NULL, \n\treset_at INTEGER NOT NULL, \n\tPRIMARY KEY (bucket)\n)\n\n",
    "\nCREATE TABLE operations (\n\tid VARCHAR(32) NOT NULL, \n\trequester VARCHAR(80) NOT NULL, \n\tresource_id VARCHAR(64) NOT NULL, \n\tidempotency_key VARCHAR(128) NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\trequest_json TEXT NOT NULL, \n\tstate VARCHAR(32) NOT NULL, \n\tdecision VARCHAR(24), \n\treason_code VARCHAR(80), \n\tready_source VARCHAR(16), \n\tversion INTEGER NOT NULL, \n\tcreated_at INTEGER NOT NULL, \n\tupdated_at INTEGER NOT NULL, \n\texpires_at INTEGER NOT NULL, \n\tplan_json TEXT, \n\tresult_json TEXT, \n\terror_json TEXT, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_operation_idempotency UNIQUE (requester, idempotency_key), \n\tCONSTRAINT ck_operation_version CHECK (version >= 1)\n)\n\n",
    "\nCREATE TABLE sessions (\n\ttoken_hash VARCHAR(64) NOT NULL, \n\tusername VARCHAR(64) NOT NULL, \n\tcsrf VARCHAR(64) NOT NULL, \n\treviewer_digest VARCHAR(64) NOT NULL, \n\tcreated_at INTEGER NOT NULL, \n\texpires_at INTEGER NOT NULL, \n\tPRIMARY KEY (token_hash)\n)\n\n",
    "\nCREATE TABLE audit_events (\n\tid INTEGER NOT NULL, \n\toperation_id VARCHAR(32) NOT NULL, \n\tseq INTEGER NOT NULL, \n\tkind VARCHAR(48) NOT NULL, \n\tpayload_json TEXT NOT NULL, \n\tcreated_at INTEGER NOT NULL, \n\tprevious_hash VARCHAR(64) NOT NULL, \n\tevent_hash VARCHAR(64) NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_audit_sequence UNIQUE (operation_id, seq), \n\tFOREIGN KEY(operation_id) REFERENCES operations (id)\n)\n\n",
    "\nCREATE TABLE jobs (\n\toperation_id VARCHAR(32) NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tstate VARCHAR(16) NOT NULL, \n\tlease_token VARCHAR(32), \n\tlease_until INTEGER NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_at INTEGER NOT NULL, \n\tPRIMARY KEY (operation_id), \n\tCONSTRAINT ck_job_kind CHECK (kind IN ('preview','execute','reconcile')), \n\tCONSTRAINT ck_job_state CHECK (state IN ('queued','leased','done')), \n\tFOREIGN KEY(operation_id) REFERENCES operations (id)\n)\n\n",
    "\nCREATE TABLE review_views (\n\tid VARCHAR(32) NOT NULL, \n\toperation_id VARCHAR(32) NOT NULL, \n\tsession_hash VARCHAR(64) NOT NULL, \n\tplan_digest VARCHAR(64) NOT NULL, \n\tview_digest VARCHAR(64) NOT NULL, \n\tview_json TEXT NOT NULL, \n\tcreated_at INTEGER NOT NULL, \n\texpires_at INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(operation_id) REFERENCES operations (id), \n\tFOREIGN KEY(session_hash) REFERENCES sessions (token_hash)\n)\n\n",
    "\nCREATE TABLE approvals (\n\toperation_id VARCHAR(32) NOT NULL, \n\tusername VARCHAR(64) NOT NULL, \n\tdecision VARCHAR(16) NOT NULL, \n\treason TEXT NOT NULL, \n\tplan_digest VARCHAR(64) NOT NULL, \n\tview_digest VARCHAR(64) NOT NULL, \n\tview_id VARCHAR(32) NOT NULL, \n\tidempotency_key VARCHAR(128) NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at INTEGER NOT NULL, \n\tPRIMARY KEY (operation_id), \n\tCONSTRAINT uq_approval_idempotency UNIQUE (username, idempotency_key), \n\tCONSTRAINT ck_approval_decision CHECK (decision IN ('approve','reject')), \n\tFOREIGN KEY(operation_id) REFERENCES operations (id), \n\tFOREIGN KEY(view_id) REFERENCES review_views (id)\n)\n\n",
    "\nCREATE TABLE telemetry (\n\tid INTEGER NOT NULL, \n\toperation_id VARCHAR(32) NOT NULL, \n\tview_id VARCHAR(32) NOT NULL, \n\tevent VARCHAR(32) NOT NULL, \n\tvisible_ms INTEGER NOT NULL, \n\thidden BOOLEAN NOT NULL, \n\tcreated_at INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(operation_id) REFERENCES operations (id), \n\tFOREIGN KEY(view_id) REFERENCES review_views (id)\n)\n\n",
    "CREATE INDEX ix_operations_queue ON operations (state, created_at)",
    "CREATE INDEX ix_audit_operation ON audit_events (operation_id, id)",
    "CREATE INDEX ix_jobs_ready ON jobs (state, next_at)",
]


def upgrade():
    connection = op.get_bind()
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup explicitly.")
