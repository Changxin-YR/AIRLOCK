"""Loopback-only notification inbox, independent from AIRLOCK business state.

This accepts the fixed health-code payload emitted by alert_delivery. It has
no approval, action execution, reconciliation or business retry endpoint. Local
receipt is not evidence of a production notification SLA or remote retention.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.requests import ClientDisconnect

from .alert_delivery import ALERT_CODES
from .sqlite_runtime import enable_wal, require_safe_python_runtime


DEFAULT_PORT = 8767
MAX_BODY_BYTES = 4096
APPLICATION_ID = 0x41494E42  # AINB: reject other application databases before opening.
STATIC = Path(__file__).with_name('static')
SECURITY_HEADERS = {
    'Cache-Control': 'no-store', 'Pragma': 'no-cache',
    'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
    'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer', 'Cross-Origin-Resource-Policy': 'same-origin',
}


class InboxEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    version: int = Field(ge=1, le=1)
    event_id: str = Field(min_length=36, max_length=36)
    kind: Literal['alert', 'recovery']
    status: Literal['alert', 'ok']
    alert_codes: list[str] = Field(max_length=len(ALERT_CODES))
    resolved_codes: list[str] = Field(max_length=len(ALERT_CODES))

    @model_validator(mode='after')
    def validate_event(self):
        parsed = uuid.UUID(self.event_id)
        if parsed.version != 4 or str(parsed) != self.event_id:
            raise ValueError('canonical UUID4 event ID required')
        for codes in (self.alert_codes, self.resolved_codes):
            if len(set(codes)) != len(codes) or any(code not in ALERT_CODES for code in codes):
                raise ValueError('fixed unique health codes required')
        if (set(self.alert_codes) & set(self.resolved_codes)
                or (self.status == 'alert') != bool(self.alert_codes)
                or (self.kind == 'alert') != (self.status == 'alert')
                or self.kind == 'recovery' and not self.resolved_codes):
            raise ValueError('inconsistent health event')
        return self


def _canonical(event):
    return json.dumps(event.model_dump(), sort_keys=True, separators=(',', ':'))


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _token(value):
    if (not isinstance(value, str) or not 16 <= len(value) <= 4096
            or any(not 33 <= ord(char) <= 126 for char in value)):
        raise ValueError('dedicated inbox credentials required')
    return value


class InboxStore:
    def __init__(self, database):
        # Rejected runtimes must never open/checkpoint an existing persistent DB.
        require_safe_python_runtime()
        self.database = Path(database)
        if self.database.is_symlink():
            raise ValueError('dedicated inbox database required')
        if self.database.exists():
            with self.database.open('rb') as file:
                header = file.read(100)
            if (len(header) != 100 or header[:16] != b'SQLite format 3\x00'
                    or int.from_bytes(header[68:72], 'big') != APPLICATION_ID):
                raise ValueError('existing file is not an AIRLOCK inbox database')
        else:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        with self.connection() as conn:
            enable_wal(conn)
            conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
            conn.execute('''CREATE TABLE IF NOT EXISTS inbox_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL, received_at TEXT NOT NULL)''')

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.database, timeout=3, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA synchronous=FULL')
            yield conn
        finally:
            conn.close()

    def receive(self, event):
        payload = _canonical(event)
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                previous = conn.execute('SELECT payload FROM inbox_events WHERE event_id=?',
                                        (event.event_id,)).fetchone()
                if previous is not None:
                    if previous['payload'] != payload:
                        raise ValueError('event_id_conflict')
                    conn.commit()
                    return True
                conn.execute('INSERT INTO inbox_events(event_id,payload,received_at) VALUES(?,?,?)',
                             (event.event_id, payload, datetime.now(timezone.utc).isoformat()))
                conn.commit()
                return False
            except BaseException:
                conn.rollback()
                raise

    def list_events(self, limit, before):
        with self.connection() as conn:
            rows = conn.execute('''SELECT seq,payload,received_at FROM inbox_events
                                   WHERE seq < ? ORDER BY seq DESC LIMIT ?''',
                                (before, limit + 1)).fetchall()
        selected = rows[:limit]
        return {'events': [dict(json.loads(row['payload']), seq=row['seq'],
                                received_at=row['received_at']) for row in selected],
                'next_before': selected[-1]['seq'] if len(rows) > limit else None}


def create_app(database: Path, *, write_token: str, read_token: str, port: int = DEFAULT_PORT):
    """Create an isolated inbox; fixtures use an explicit loopback base URL/port."""
    write_token, read_token = _token(write_token), _token(read_token)
    if hmac.compare_digest(write_token, read_token):
        raise ValueError('inbox write and read credentials must differ')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('valid loopback port required')
    store = InboxStore(database)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}

    def error(code, status):
        return JSONResponse({'error_code': code}, status_code=status)

    def authorized(request, expected):
        headers = request.headers.getlist('authorization')
        return (len(headers) == 1 and len(headers[0]) <= 4103
                and hmac.compare_digest(headers[0].encode(), ('Bearer ' + expected).encode()))

    @app.middleware('http')
    async def boundary(request, call_next):
        hosts = request.headers.getlist('host')
        origins = request.headers.getlist('origin')
        if (len(hosts) != 1 or hosts[0] not in allowed_hosts
                or origins and (len(origins) != 1 or origins[0] != 'http://' + hosts[0])
                or request.headers.get('sec-fetch-site') == 'cross-site'):
            response = error('inbox_origin_rejected', 403)
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'alert-inbox.html')

    @app.get('/static/alert-inbox.js')
    def javascript():
        return FileResponse(STATIC / 'alert-inbox.js', media_type='text/javascript')

    @app.get('/static/alert-inbox.css')
    def stylesheet():
        return FileResponse(STATIC / 'alert-inbox.css', media_type='text/css')

    @app.post('/airlock/events')
    async def receive(request: Request):
        if not authorized(request, write_token):
            return error('inbox_write_credential_required', 401)
        if request.url.query:
            return error('inbox_query_rejected', 400)
        lengths = request.headers.getlist('content-length')
        if (len(lengths) > 1 or lengths and (len(lengths[0]) > 10 or not lengths[0].isdigit()
                or int(lengths[0]) > MAX_BODY_BYTES)):
            return error('inbox_body_too_large_or_invalid', 413)
        if request.headers.get('content-encoding', 'identity') != 'identity':
            return error('inbox_encoding_rejected', 415)
        types = request.headers.getlist('content-type')
        if len(types) != 1 or types[0].lower() not in {'application/json', 'application/json; charset=utf-8'}:
            return error('inbox_json_required', 415)
        keys = request.headers.getlist('idempotency-key')
        if len(keys) != 1 or len(keys[0]) != 36:
            return error('inbox_event_binding_required', 400)
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        return error('inbox_body_too_large_or_invalid', 413)
                    body.extend(chunk)
            if lengths and len(body) != int(lengths[0]):
                return error('inbox_body_length_mismatch', 400)
            event = InboxEvent.model_validate(json.loads(body, object_pairs_hook=_no_duplicate_keys))
        except TimeoutError:
            return error('inbox_body_timeout', 408)
        except (ValueError, TypeError, UnicodeError, ValidationError, RecursionError, ClientDisconnect):
            return error('inbox_payload_rejected', 400)
        if not hmac.compare_digest(keys[0].encode(), event.event_id.encode()):
            return error('inbox_event_binding_mismatch', 400)
        try:
            # sqlite3 may wait for a writer; keep it off the ASGI event loop.
            duplicate = await asyncio.to_thread(store.receive, event)
        except ValueError:
            return error('inbox_event_id_conflict', 409)
        except (sqlite3.Error, OSError):
            return error('inbox_storage_unavailable', 503)
        return JSONResponse({'status': 'received', 'event_id': event.event_id, 'duplicate': duplicate},
                            status_code=200 if duplicate else 201)

    @app.get('/api/events')
    async def events(request: Request):
        if not authorized(request, read_token):
            return error('inbox_read_credential_required', 401)
        query = request.query_params
        if any(key not in {'limit', 'before'} for key in query) or any(len(query.getlist(key)) != 1 for key in query):
            return error('inbox_query_rejected', 400)
        try:
            limit, before = int(query.get('limit', '50')), int(query.get('before', str(2**63 - 1)))
            if not 1 <= limit <= 100 or not 1 <= before <= 2**63 - 1:
                raise ValueError()
        except ValueError:
            return error('inbox_query_rejected', 400)
        try:
            result = await asyncio.to_thread(store.list_events, limit, before)
        except (sqlite3.Error, OSError):
            return error('inbox_storage_unavailable', 503)
        return JSONResponse(result)

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True,
                        help='Dedicated file under ./var/, e.g. var/notifications/local.inbox.sqlite3')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    database, root = args.database.resolve(), (Path.cwd() / 'var').resolve()
    if not database.is_relative_to(root) or database == root:
        parser.error('--database must be a dedicated file under ./var/')
    try:
        app = create_app(database,
                         write_token=os.environ.get('AIRLOCK_INBOX_WRITE_TOKEN'),
                         read_token=os.environ.get('AIRLOCK_INBOX_READ_TOKEN'), port=args.port)
    except (ValueError, OSError, sqlite3.Error, RuntimeError):
        parser.exit(2, 'Inbox startup rejected; check dedicated credentials, database and SQLite runtime.\n')
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=args.port, proxy_headers=False, access_log=False,
                server_header=False, timeout_keep_alive=5, limit_concurrency=64)


if __name__ == '__main__':
    main()
