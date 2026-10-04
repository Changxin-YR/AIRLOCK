"""Complete synthetic-table compensation, never an implicit permission or backup claim."""
import json
import sqlite3
from .sql import SCHEMA,snapshot,fingerprint
from .models import GateError


def classification(impact,tool):
    evidence=impact.get('recovery_evidence',{})
    remote=tool.startswith('upstream:')
    return {
        'preview_rollback':'private_clone_discarded' if not remote else 'upstream_declared_no_effect_preview',
        'before_commit_rollback':'same_database_transaction' if not remote else 'upstream_contract_dependent',
        'technical_reversibility':evidence.get('technical_reversibility','snapshot_compensation_after_successful_commit' if not remote else 'unknown'),
        'restore_feasibility':evidence.get('restore_feasibility','requires_saved_snapshot_and_unchanged_target' if not remote else 'unknown'),
        'evidence':evidence or {'snapshot_hash':impact.get('before_hash'),'snapshot_saved':'on_successful_commit','is_backup':False},
        'business_authorization':'not_inferred_from_reversibility; separate_review_required',
        'backup_status':'unknown','automatic_approval':False}


def apply_rows(conn,rows):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='customers'").fetchone():
        raise ValueError('recovery does not support triggers')
    conn.execute('DELETE FROM customers')
    conn.executemany('INSERT INTO customers VALUES (:id,:name,:tier,:balance)',rows)


def plan(conn,source,principal):
    row=conn.execute('SELECT document FROM recovery_plans WHERE source_id=?',(source,)).fetchone()
    if not row: raise GateError('recovery_plan_unavailable',404)
    result=json.loads(row[0])
    if result['principal']!=principal: raise GateError('recovery_plan_unavailable',404)
    return result


def preview_restore(conn,recovery):
    before=snapshot(conn)
    if fingerprint(before)!=recovery['after_hash']: raise GateError('recovery_target_drift',409)
    clone=sqlite3.connect(':memory:',isolation_level=None,cached_statements=0)
    clone.row_factory=sqlite3.Row
    try:
        clone.execute(SCHEMA); clone.executemany('INSERT INTO customers VALUES (:id,:name,:tier,:balance)',before)
        clone.execute('BEGIN'); apply_rows(clone,recovery['before_rows']); after=snapshot(clone)
        if fingerprint(after)!=recovery['before_hash']: raise ValueError('restore rehearsal mismatch')
        clone.execute('ROLLBACK')
    finally: clone.close()
    a,b={r['id']:r for r in before},{r['id']:r for r in after}
    ids=sorted(k for k in a.keys()|b.keys() if a.get(k)!=b.get(k))
    return {'certainty':'snapshot_exact','is_estimate':False,'before_count':len(before),'after_count':len(after),
        'matched_rows':len(before),'changed_rows':len(ids),'operations':['restore'],'before_hash':fingerprint(before),
        'after_hash':fingerprint(after),'sample':[{'id':k,'before':a.get(k),'after':b.get(k)} for k in ids[:5]],
        'sample_truncated':len(ids)>5,'recovery':'Separate compensation action; a full synthetic snapshot was rehearsed in an isolated clone.',
        'backup_age_seconds':None,'recovery_evidence':{'source_action_id':recovery['source_id'],'snapshot_created_at':recovery['created_at'],
            'technical_reversibility':'full_snapshot_compensation','restore_feasibility':'rehearsed_in_clone',
            'business_authorization':'independent_approval_required','is_backup':False}}


def save_plan(conn,action,before,after,now):
    record={'source_id':action['id'],'principal':action['principal'],'created_at':now,
            'before_rows':before,'before_hash':fingerprint(before),'after_hash':fingerprint(after)}
    conn.execute('INSERT INTO recovery_plans VALUES(?,?)',(action['id'],json.dumps(record,ensure_ascii=False)))
