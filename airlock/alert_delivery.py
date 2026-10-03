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
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlparse
import uuid

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import network


ALERT_CODES = frozenset({
    'audit_integrity_failed', 'remote_outcome_needs_reconciliation',
    'pending_expiry_backlog', 'telemetry_outbox_pressure', 'telemetry_spans_dropped',
})
CREDENTIAL_ENV = 'AIRLOCK_ALERT_WEBHOOK_TOKEN'


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


def _connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('CREATE TABLE IF NOT EXISTS notification_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS notification_targets (target_id TEXT PRIMARY KEY, status TEXT NOT NULL, codes TEXT NOT NULL)')
        conn.execute('''CREATE TABLE IF NOT EXISTS notification_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
            target_id TEXT NOT NULL, payload TEXT NOT NULL,
            delivery_state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            response_status INTEGER, failure_code TEXT)''')
        return conn
    except BaseException:
        conn.close()
        raise


def _observe(conn, target, status, codes):
    conn.execute('BEGIN IMMEDIATE')
    try:
        previous = conn.execute('SELECT status,codes FROM notification_targets WHERE target_id=?', (target,)).fetchone()
        active = conn.execute("SELECT value FROM notification_meta WHERE key='active_target' ").fetchone()
        previous_codes = json.loads(previous['codes']) if previous else []
        changed = previous is None or previous['status'] != status or previous_codes != codes
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
        _observe(conn, target, status, codes)
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
    except (sqlite3.Error, OSError):
        if conn is not None:
            conn.rollback()
        return dict(result, status='unknown' if attempted_event_id else 'blocked',
                    event_id=attempted_event_id, error_code='notification_state_unavailable')
    finally:
        if conn is not None:
            conn.close()
