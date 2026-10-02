"""Operator-configured HMAC key IDs. No key material is returned over the API."""
import json
import os
import re
from pathlib import Path
from .models import digest


def keyring(settings):
    keys={'legacy':settings.audit_key}
    if settings.audit_key_file:
        raw=Path(settings.audit_key_file).read_text(encoding='utf-8')
        if len(raw.encode())>8192:raise ValueError('audit key configuration too large')
        value=json.loads(raw)
        if set(value)!={'keys'} or not isinstance(value['keys'],dict) or len(value['keys'])>16:raise ValueError('invalid audit key ring')
        for id,variable in value['keys'].items():
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}',id) or id=='legacy':raise ValueError('invalid key ID')
            if not isinstance(variable,str) or not re.fullmatch(r'AIRLOCK_AUDIT_KEY_[A-Z0-9_]+',variable):raise ValueError('invalid audit key variable')
            secret=os.environ.get(variable,'')
            if len(secret)<32 or not secret.isascii():raise ValueError('missing audit key')
            keys[id]=secret
    if len(set(keys.values()))!=len(keys) or any(secret in {settings.agent_token,settings.reviewer_token} for secret in keys.values()):
        raise ValueError('audit key separation')
    return keys


def register(conn,settings):
    keys=keyring(settings)
    for id,secret in keys.items():
        name='audit_key_fingerprint:'+id
        old=conn.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()
        if old and old[0]!=digest(secret):raise ValueError('audit key changed for existing ID')
        conn.execute('INSERT OR IGNORE INTO meta VALUES(?,?)',(name,digest(secret)))
    active=conn.execute("SELECT value FROM meta WHERE key='audit_active_key'").fetchone()
    if active and active[0] not in keys:raise ValueError('active audit key unavailable')
    return keys
