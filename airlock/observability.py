"""Fixed-label, bounded metrics; per-action correlation stays in durable evidence."""
from contextvars import ContextVar
from collections import Counter
import math

request_id=ContextVar('airlock_request_id',default=None)


def distribution(values):
    values=sorted(v for v in values if type(v) in (int,float) and math.isfinite(v) and v>=0)
    return {'n':len(values),**{f'p{q}':values[max(0,math.ceil(len(values)*q/100)-1)] if values else None for q in (50,95,99)}}


def summarize(actions):
    from .governance import groups
    pending=[a for a in actions if a['state']=='pending']
    grouped=groups(pending)
    reviewed=[a for a in actions if a.get('reviewer')]
    semantics=[a['semantic'] for a in actions if 'semantic' in a]
    receipts=[s for s in semantics if s.get('provider_call_id') and not s.get('application_cache_hit')]
    known=[s['cost_usd'] for s in receipts if s.get('cost_usd') is not None]
    usage=[s['usage'] for s in receipts if s.get('usage')]
    return {'decisions':dict(Counter(a['decision'] for a in actions)),
      'stages_ms':{key:distribution([a[key] for a in actions if key in a]) for key in
          ('static_ms','preview_ms','semantic_ms','evaluation_ms','execution_ms','queue_ms')},
      'preview_coverage':{'numerator':sum(a['impact'] is not None for a in actions),'denominator':len(actions)},
      'semantic':{'assessments':len(semantics),'provider_receipts':len(receipts),
          'application_cache_hits':sum(bool(s.get('application_cache_hit')) for s in semantics),
          'errors':sum(s['status']=='error' for s in semantics),'cost_usd':sum(known) if receipts and len(known)==len(receipts) else None,
          'known_cost_usd':sum(known) if known else None,'usage_records':len(usage),
          'input_tokens':sum(s['input_tokens'] for s in usage) if usage else None,
          'output_tokens':sum(s['output_tokens'] for s in usage) if usage else None,
          'provider_cache_read_tokens':sum(s['cache_read_tokens'] for s in usage) if usage else None,
          'provider_cache_write_tokens':None,'currency':'USD'},
      'governance':{'readonly_passes':sum(a['decision']=='pass' for a in actions),
                    'sample_requests':len(actions),'eligible_pending_members':len(pending),'display_groups_default_window':len(grouped),
                    'fold_ratio_default_window':1-len(grouped)/len(pending) if pending else None,
                    'reviewed_actions':len(reviewed),'batch_reviewed_actions':sum(bool(a.get('batch_digest')) for a in reviewed),
                    'batch_review_rate':sum(bool(a.get('batch_digest')) for a in reviewed)/len(reviewed) if reviewed else None,
                    'human_approval_errors':None,'active_user_days':None,
                    'budget_blocks':sum(a['reason_code']=='risk_budget_exhausted' for a in actions)},
      'scope':'last 1000 authorized actions; stages measured locally; absent data is null'}
