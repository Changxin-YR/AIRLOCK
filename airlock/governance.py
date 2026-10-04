"""Durable row-unit budgets and explicit, snapshot-bound request groups."""
import json
from collections import defaultdict
from contextvars import ContextVar
from .models import GateError,digest

batch_context=ContextVar('batch_context',default=None)
batch_risk=ContextVar('batch_risk',default=None)


def duplicate_hit(conn):
    conn.execute("INSERT INTO meta(key,value) VALUES('idempotent_hits','1') ON CONFLICT(key) DO UPDATE SET value=MIN(CAST(value AS INTEGER)+1,9007199254740991)")


def reserve(conn,action,settings,now):
    units=max(1,action['impact']['changed_rows'],action['impact']['matched_rows'])
    scope=digest({'principal':action['principal'],'resource':action['resource']})
    window=int(now//settings.budget_window_seconds)
    consumed=conn.execute("SELECT COALESCE(sum(units),0) FROM risk_budget WHERE scope=? AND window=? AND state IN ('reserved','settled')",(scope,window)).fetchone()[0]
    if consumed+units>settings.budget_units:
        return False
    conn.execute('INSERT INTO risk_budget VALUES(?,?,?,?,?)',(action['id'],scope,window,units,'reserved'))
    action['budget']={'units':units,'unit':'max(matched_rows, changed_rows, 1)','window':window,
        'window_seconds':settings.budget_window_seconds,'limit':settings.budget_units,
        'scope':scope,'authorization_effect':'none'}
    return True


def settle(conn,action,state):
    if state=='executed': target='settled'
    elif state in {'rejected','expired','stale','failed','blocked'}: target='released'
    else: return
    conn.execute('UPDATE risk_budget SET state=? WHERE action_id=?',(target,action['id']))


def groups(actions,window_seconds=60):
    buckets=defaultdict(list)
    for action in actions:
        if action['state']!='pending': continue
        key={'principal':action['principal'],'tool':action['request']['tool'],'resource':action['resource'],
             'policy':action['policy_version'],'risk':action['risk'],'reviewers':action['reviewers'],
             'window':int(action['created_at']//window_seconds)}
        buckets[digest(key)].append(action)
    result=[]
    for group_id,members in buckets.items():
        members.sort(key=lambda a:a['id'])
        bindings=[{'id':a['id'],'request_hash':a['request_hash'],'review_digest':a['review_digest'],
                   'version':a['version'],'expires_at':a['expires_at']} for a in members]
        total=sum(max(a['impact']['matched_rows'],a['impact']['changed_rows'],1) for a in members)
        result.append({'id':group_id,'digest':digest(bindings),'members':members,'cumulative_units':total,
                       'confirmation_required':f'REVIEW {len(members)} ACTIONS {total} UNITS'})
    return result
