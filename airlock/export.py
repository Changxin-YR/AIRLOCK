"""Minimal audit summaries with randomized action aliases for external sharing.

This is an allowlist, not a regex PII scrubber. Original audit events remain
unchanged. Stable event digests link repeated exports of an event, but cannot
verify omitted data. Random aliases alone are not a claim of unlinkability.
"""
import hashlib
import hmac
import secrets
from .models import canonical


KINDS={'action.evaluated','action.executed','action.rejected','action.blocked','action.stale','action.failed',
       'action.unknown','action.executing','action.expired','governance.changed'}
STATES={'pending','executing','executed','unknown','blocked','rejected','expired','stale','failed','activated','revoked'}


def redacted_export(events):
    salt=secrets.token_bytes(32)
    def pseudonym(value):return hmac.new(salt,str(value).encode(),hashlib.sha256).hexdigest()[:24]
    rows=[]
    for event in events:
        detail=event['event']
        rows.append({'sequence':event['seq'],'action_pseudonym':pseudonym(event['action_id']),
            'kind':detail.get('kind') if detail.get('kind') in KINDS else 'other',
            'state':detail.get('state') if detail.get('state') in STATES else 'other',
            'source_event_sha256':hashlib.sha256(canonical(event).encode()).hexdigest()})
    return {'version':1,'mode':'minimal_redacted_summary','items':rows,
        'omitted':['SQL','arguments','samples','free_text','identities','timestamps','model_output','original_signatures'],
        'verification':'Summaries omit original payloads and cannot independently verify the source HMAC chain. Retain original audit and checkpoint separately.',
        'privacy':'Random pseudonyms change for every export. Sequence, counts and states remain visible; review suitability before sharing.'}
