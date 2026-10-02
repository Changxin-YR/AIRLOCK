"""Structural replay completeness, separate from cryptographic integrity."""
import math

STATES={'pending','blocked','executed','rejected','expired','stale','failed','executing','unknown'}
SNAPSHOT_FIELDS={'id','principal','request','request_hash','created_at','expires_at','version','policy_version',
    'state','decision','reason_code','risk','impact','result','review_digest','confirmation_required','reviewers','trace_id','request_id','template_version'}


def completeness(events):
    snapshots={};claims=set();rows=[]
    for record in events:
        event=record['event'];kind=event.get('kind','');missing=[];na={}
        if not kind.startswith('action.'):
            rows.append({'seq':record['seq'],'applicable':False,'reason':'operator governance event, not an action transition'});continue
        for field in ('kind','at','state','trace_id','request_id','detail'):
            if field not in event or event[field] is None:missing.append('event.'+field)
        if event.get('state') not in STATES:missing.append('valid action state')
        if type(event.get('at')) not in (int,float) or not math.isfinite(event['at']):missing.append('finite event time')
        detail=event.get('detail') or {};snapshot=detail.get('snapshot')
        if kind=='action.evaluated':
            if not isinstance(snapshot,dict):missing.append('original snapshot')
            else:
                missing.extend('snapshot.'+f for f in sorted(SNAPSHOT_FIELDS-set(snapshot)))
                if snapshot.get('id')!=record['action_id']:missing.append('action binding')
                if snapshot.get('trace_id')!=event.get('trace_id'):missing.append('trace binding')
                for field in ('tool','sql','parameters','arguments','idempotency_key'):
                    if field not in snapshot.get('request',{}):missing.append('request.'+field)
                if snapshot.get('state')=='pending' and (not snapshot.get('impact') or not snapshot.get('review_digest')):missing.append('pending approval evidence')
                if snapshot.get('impact') is None:na['impact']='Read-only or blocked before supported write preview; see reason_code and decision.'
                if snapshot.get('review_digest') is None:na['review_digest']='No pending reviewer authorization offered.'
                na['reviewer']='Evaluation occurs before any human decision.'
                snapshots[record['action_id']]=snapshot
        else:
            original=snapshots.get(record['action_id'])
            if not original:missing.append('preceding original snapshot')
            elif original['trace_id']!=event.get('trace_id'):missing.append('transition trace binding')
            receipt=detail.get('receipt')
            if receipt is not None:
                if not isinstance(receipt,dict) or not original or receipt.get('action_id')!=record['action_id'] or receipt.get('request_hash')!=original.get('request_hash') or receipt.get('state')!=event.get('state') or record['action_id'] not in claims:
                    missing.append('bound upstream receipt with preceding independent approval')
                na['reviewer']='Reviewer and approval digest recorded in preceding action.executing claim.'
            elif event.get('state') in {'rejected','stale','failed','executing','executed'}:
                if not detail.get('reviewer') or not detail.get('reason') or not detail.get('review_digest'):missing.append('independent review evidence')
                elif event.get('state')=='executing':claims.add(record['action_id'])
            elif event.get('state') in {'expired','unknown'}:
                na['reviewer']='Server expiry or unresolved upstream result; consult preceding approval claim if present.'
        rows.append({'seq':record['seq'],'state':event.get('state'),'applicable':True,'missing':missing,'not_applicable':na,'complete':not missing})
    applicable=[r for r in rows if r['applicable']];complete=sum(r['complete'] for r in applicable)
    return {'schema':'airlock-replay-completeness-v1','events':len(events),'applicable_events':len(applicable),
        'complete_events':complete,'completeness':complete/len(applicable) if applicable else None,
        'states':sorted({r['state'] for r in applicable}),'rows':rows,
        'limitation':'Structural completeness is not proof of truth or chain integrity; verify HMAC/checkpoint separately.'}
