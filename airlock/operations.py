"""Read-only operational checks with stable alert codes and no sensitive samples."""
from collections import Counter
import json
import time
from . import telemetry


def health(gate):
    now=gate.clock();alerts=[]
    audit=gate.store.verify_audit()
    if not audit['valid']:alerts.append({'code':'audit_integrity_failed','severity':'critical'})
    with gate.store.connection() as conn:
        counts=dict(conn.execute('SELECT state,count(*) FROM actions GROUP BY state'))
        overdue=conn.execute("SELECT count(*) FROM actions WHERE state='pending' AND expires<=?",(now,)).fetchone()[0]
        unknown=conn.execute("SELECT count(*) FROM actions WHERE state IN ('unknown','executing') AND created<?",(now-300,)).fetchone()[0]
    spans=telemetry.metrics(gate.store)
    if unknown:alerts.append({'code':'remote_outcome_needs_reconciliation','severity':'critical','count':unknown})
    if overdue:alerts.append({'code':'pending_expiry_backlog','severity':'warning','count':overdue})
    if spans['pending_spans']>=800:alerts.append({'code':'telemetry_outbox_pressure','severity':'warning','count':spans['pending_spans']})
    if spans['dropped_spans']:alerts.append({'code':'telemetry_spans_dropped','severity':'warning','count':spans['dropped_spans']})
    return {'status':'alert' if alerts else 'ok','alerts':alerts,'state_counts':counts,'telemetry':spans,
        'checked_at':now,'authorization_effect':'none; checks do not approve, retry or reconcile actions',
        'recommended_exit_code':2 if alerts else 0}


def prometheus(report):
    lines=['# HELP airlock_operations_alert Active operator-visible conditions.',
           '# TYPE airlock_operations_alert gauge']
    codes={a['code'] for a in report['alerts']}
    for code in ('audit_integrity_failed','remote_outcome_needs_reconciliation','pending_expiry_backlog','telemetry_outbox_pressure','telemetry_spans_dropped'):
        lines.append(f'airlock_operations_alert{{code="{code}"}} {int(code in codes)}')
    for key in ('pending_spans','dropped_spans','exported_spans'):
        lines.append(f'airlock_telemetry_{key} {report["telemetry"][key]}')
    return '\n'.join(lines)+'\n'
