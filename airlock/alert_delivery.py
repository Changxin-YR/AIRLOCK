"""Operator-owned webhook delivery; it grants no action or approval authority.

The endpoint, network pins and dedicated bearer credential belong to the
operator. Only fixed health codes leave this process. SQLite is a separate
notification outbox, not the AIRLOCK business database. Events are persisted
before sending and only 2xx responses acknowledge them. A lost response or a
crash after remote acceptance can cause a retry with the SAME event ID; the
receiver must deduplicate it. This is not network exactly-once delivery.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from contextlib import closing
from pathlib import Path
import sqlite3
from urllib.parse import urlparse
import uuid

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import network
from .sqlite_runtime import require_safe_python_runtime


ALERT_CODES = frozenset({
    'audit_integrity_failed', 'remote_outcome_needs_reconciliation',
    'pending_expiry_backlog', 'telemetry_outbox_pressure', 'telemetry_spans_dropped',
})
CREDENTIAL_ENV = 'AIRLOCK_ALERT_WEBHOOK_TOKEN'
APPLICATION_ID = 0x414F5554  # AOUT: a dedicated notification outbox only.
OUTBOX_DDL = (
    'CREATE TABLE IF NOT EXISTS notification_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS notification_targets (target_id TEXT PRIMARY KEY, status TEXT NOT NULL, codes TEXT NOT NULL)',
    '''CREATE TABLE IF NOT EXISTS notification_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
        target_id TEXT NOT NULL, payload TEXT NOT NULL,
        delivery_state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        response_status INTEGER, failure_code TEXT)''',
)


class AlertConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    endpoint: str = Field(min_length=1, max_length=2048)
    address_pins: list[str] = Field(default_factory=list, max_length=16)
    allow_loopback_fixture: bool = False
    ca_file: str | None = None
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    @model_validator(mode='after')
    def validate_endpoint(self):
        parsed = urlparse(self.endpoint)
        if (any(ord(c) <= 32 or ord(c) >= 127 for c in self.endpoint)
                or parsed.username is not None or parsed.password is not None
                or '?' in self.endpoint or '#' in self.endpoint or '\\' in self.endpoint):
            raise ValueError('fixed webhook endpoint without credentials or query required')
        network.validate_origin(self.origin, self.address_pins, self.allow_loopback_fixture)
        if parsed.scheme != 'https' and not self.allow_loopback_fixture:
            raise ValueError('webhook HTTPS required')
        return self

    @property
    def origin(self):
        parsed = urlparse(self.endpoint)
        return f'{parsed.scheme}://{parsed.netloc}'


def health_summary(report):
    """Reject unrecognized codes instead of forwarding arbitrary server text."""
    if not isinstance(report, dict) or report.get('status') not in {'ok', 'alert'}:
        raise ValueError('invalid health status')
    alerts = report.get('alerts')
    if not isinstance(alerts, list) or len(alerts) > len(ALERT_CODES):
        raise ValueError('invalid health alerts')
    codes = []
    for item in alerts:
        if not isinstance(item, dict) or not isinstance(item.get('code'), str) or item['code'] not in ALERT_CODES:
            raise ValueError('invalid health alert code')
        codes.append(item['code'])
    if len(set(codes)) != len(codes) or (report['status'] == 'alert') != bool(codes):
        raise ValueError('inconsistent health alerts')
    return report['status'], sorted(codes)


def _credential():
    token = os.environ.get(CREDENTIAL_ENV)
    if not token or not 16 <= len(token) <= 4096 or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError('dedicated webhook credential required')
    return token


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _target_id(config, token):
    # Include credential rotation as it can route to a different tenant. Neither
    # the credential nor its standalone digest is stored in the outbox/output.
    target = config.model_dump()
    target['credential_digest'] = hashlib.sha256(token.encode()).hexdigest()
    return hashlib.sha256(_json(target).encode()).hexdigest()


def _schema_signature(conn):
    """Inspect constraints, defaults, key collations and table options.

    PRAGMA metadata avoids comparing CREATE statement whitespace/casing. CHECK
    and ON CONFLICT clauses are not exposed by those pragmas, so reject such
    additions. The small lexer excludes comments and quoted text when checking
    those keywords and the events table's AUTOINCREMENT requirement.
    """
    tables = {'notification_meta', 'notification_targets', 'notification_events', 'sqlite_sequence'}
    objects = conn.execute('SELECT type,name,tbl_name,sql FROM sqlite_master').fetchall()
    if ({name for kind, name, _, _ in objects if kind == 'table'} != tables
            or any(kind not in {'table', 'index'}
                   or kind == 'index' and (not name.startswith('sqlite_autoindex_notification_') or sql is not None)
                   for kind, name, _, sql in objects)):
        raise ValueError('unsupported notification schema objects')
    for kind, name, _, sql in objects:
        if kind != 'table':
            continue
        tokens = re.findall(r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|[A-Za-z_][A-Za-z0-9_]*|.", sql, re.DOTALL)
        keywords = {token.upper() for token in tokens if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', token)}
        if (keywords & {'CHECK', 'CONFLICT', 'COLLATE'}
                or ('AUTOINCREMENT' in keywords) != (name == 'notification_events')):
            raise ValueError('unsupported notification constraints')
    options = sorted(tuple(row) for row in conn.execute('PRAGMA table_list') if row[0] == 'main' and row[1] in tables)
    detail = []
    for table in sorted(tables):
        columns = [tuple(row) for row in conn.execute('PRAGMA table_xinfo(' + table + ')')]
        columns = [row[:2] + (row[2].upper(),) + row[3:] for row in columns]
        if conn.execute('PRAGMA foreign_key_list(' + table + ')').fetchall():
            raise ValueError('unsupported notification foreign key')
        indexes = []
        for row in conn.execute('PRAGMA index_list(' + table + ')'):
            name = row[1].replace("'", "''")
            index_columns = tuple(tuple(item) for item in conn.execute("PRAGMA index_xinfo('" + name + "')"))
            indexes.append((row[2], row[3], row[4], index_columns))
        detail.append((table, columns, sorted(indexes)))
    return options, detail


def _connect(path):
    # Even though new outboxes use rollback journals, an existing database may
    # use WAL. Never open/checkpoint it on an unconfirmed runtime.
    require_safe_python_runtime()
    path = Path(path)
    if path.is_symlink():
        raise ValueError('dedicated notification database required')
    if path.exists():
        with path.open('rb') as file:
            header = file.read(100)
        if (len(header) != 100 or header[:16] != b'SQLite format 3\x00'
                or int.from_bytes(header[68:72], 'big') not in (0, APPLICATION_ID)):
            raise ValueError('existing file is not an AIRLOCK notification database')
        # Earlier outboxes have application_id=0. Permit a schema-checked
        # migration while refusing unrelated databases before any write.
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as existing:
            with closing(sqlite3.connect(':memory:')) as expected:
                for statement in OUTBOX_DDL:
                    expected.execute(statement)
                if _schema_signature(existing) != _schema_signature(expected):
                    raise ValueError('existing file is not an AIRLOCK notification database')
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA synchronous=FULL')
        for statement in OUTBOX_DDL:
            conn.execute(statement)
        if conn.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
        return conn
    except BaseException:
        conn.close()
        raise


class StaleObservation(ValueError):
    pass


def health_observation_time(report):
    value = report.get('checked_at')
    if 'checked_at' not in report:
        return None  # Legacy/local callers have no timestamp ordering claim.
    if type(value) not in (int, float) or not 0 <= value < 253402300800 or not math.isfinite(value):
        raise ValueError('finite health observation timestamp required')
    return value


def _observe(conn, target, status, codes, checked_at):
    conn.execute('BEGIN IMMEDIATE')
    try:
        previous = conn.execute('SELECT status,codes FROM notification_targets WHERE target_id=?', (target,)).fetchone()
        active = conn.execute("SELECT value FROM notification_meta WHERE key='active_target' ").fetchone()
        previous_codes = json.loads(previous['codes']) if previous else []
        changed = previous is None or previous['status'] != status or previous_codes != codes
        time_key = 'checked_at:' + target
        high_water = conn.execute('SELECT value FROM notification_meta WHERE key=?', (time_key,)).fetchone()
        if high_water is not None:
            latest = health_observation_time({'checked_at': json.loads(high_water['value'])})
            if checked_at is None or checked_at <= latest and changed:
                raise StaleObservation('out-of-order health observation')
            checked_at = max(latest, checked_at)
        switched = active is None or active['value'] != target
        # Initial healthy observations are quiet. Alerts on a newly selected
        # target are sent even if some other target acknowledged that condition.
        if (changed and (previous is not None or status == 'alert')) or (switched and status == 'alert'):
            event_id = str(uuid.uuid4())
            payload = {'version': 1, 'event_id': event_id,
                       'kind': 'recovery' if status == 'ok' else 'alert',
                       'status': status, 'alert_codes': codes,
                       'resolved_codes': sorted(set(previous_codes) - set(codes))}
            conn.execute('INSERT INTO notification_events(event_id,target_id,payload) VALUES(?,?,?)',
                         (event_id, target, _json(payload)))
        conn.execute('INSERT OR REPLACE INTO notification_targets VALUES(?,?,?)', (target, status, _json(codes)))
        conn.execute("INSERT OR REPLACE INTO notification_meta VALUES('active_target',?)", (target,))
        if checked_at is not None:
            conn.execute('INSERT OR REPLACE INTO notification_meta VALUES(?,?)', (time_key, _json(checked_at)))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _pending(conn, target):
    return conn.execute("SELECT count(*) FROM notification_events WHERE target_id=? AND delivery_state!='delivered'", (target,)).fetchone()[0]


def _post(config, token, row):
    try:
        with network.client(config.origin, pins=config.address_pins,
                            allow_loopback=config.allow_loopback_fixture,
                            ca_file=config.ca_file, timeout=config.timeout_seconds) as client:
            # Do not read, log or persist receiver-controlled response bodies.
            with client.stream('POST', config.endpoint, content=row['payload'].encode(), headers={
                'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                'Idempotency-Key': row['event_id'],
            }) as response:
                if 200 <= response.status_code < 300:
                    return 'delivered', response.status_code, None
                return 'failed', response.status_code, 'webhook_non_success'
    except ValueError:
        return 'blocked', None, 'webhook_network_configuration_rejected'
    except (httpx.HTTPError, OSError):
        # A transport error does not prove that the receiver did not process it.
        return 'unknown', None, 'webhook_outcome_unknown'


def deliver_alerts(config: AlertConfig, report, state_path):
    """Persist observation and drain up to 32 ordered events for this target.

    Failed/unknown events retain their original ID and payload for the next
    operator-scheduled run. One database writer serializes observations and
    sends; a crash after remote acceptance still requires receiver deduplication.
    Local state loss also loses deduplication history. No actions are approved,
    retried or reconciled by this function.
    """
    result = {'status': 'blocked', 'event_ids': [], 'pending_count': None}
    try:
        status, codes = health_summary(report)
        checked_at = health_observation_time(report)
        token = _credential()
        # Revalidate mutable list members if an operator modifies an instance.
        config = AlertConfig.model_validate(config.model_dump())
        target = _target_id(config, token)
    except (ValueError, TypeError):
        return dict(result, error_code='alert_configuration_or_report_invalid')
    conn = None
    attempted_event_id = None
    try:
        conn = _connect(state_path)
        _observe(conn, target, status, codes, checked_at)
        for _ in range(32):
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT * FROM notification_events WHERE target_id=? AND delivery_state!='delivered' ORDER BY seq LIMIT 1", (target,)).fetchone()
            if row is None:
                conn.commit()
                return dict(result, status='delivered' if result['event_ids'] else 'unchanged', pending_count=0)
            attempted_event_id = row['event_id']
            delivery, response_status, failure = _post(config, token, row)
            conn.execute('''UPDATE notification_events SET delivery_state=?, attempts=attempts+1,
                            response_status=?, failure_code=? WHERE event_id=?''',
                         (delivery, response_status, failure, row['event_id']))
            conn.commit()
            if delivery != 'delivered':
                return dict(result, status=delivery, event_id=row['event_id'],
                            error_code=failure, pending_count=_pending(conn, target))
            result['event_ids'].append(row['event_id'])
        pending = _pending(conn, target)
        return dict(result, status='pending' if pending else 'delivered', pending_count=pending)
    except StaleObservation:
        return dict(result, error_code='health_observation_stale_or_unordered')
    except (sqlite3.Error, OSError, ValueError, RuntimeError):
        if conn is not None:
            conn.rollback()
        return dict(result, status='unknown' if attempted_event_id else 'blocked',
                    event_id=attempted_event_id, error_code='notification_state_unavailable')
    finally:
        if conn is not None:
            conn.close()
