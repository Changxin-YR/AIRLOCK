"""Protocol-independent approval state machine and local atomic executor."""
from __future__ import annotations
import json
import math
import sqlite3
import time
import uuid
from .models import Decision, GateError, Invocation, Settings, canonical, digest
from .sql import SCHEMA, classify, execute, fingerprint, preview, snapshot
from .store import Store
from .policy import PolicyManager
from .access import AccessControl
from . import recovery
from . import governance
from .upstream import Registry,RemoteActions
from .semantic import SemanticAdvisor
from . import observability

TERMINAL = {"executed", "blocked", "rejected", "expired", "stale", "failed", "unknown"}


class Gate:
    def __init__(self, settings: Settings, clock=time.time):
        self.settings, self.clock, self.store = settings, clock, Store(settings)
        self.policy = PolicyManager(settings.policy_file,self.store)
        self.policy.reload_hook=self.reload_policy
        self.access = AccessControl(settings)
        self.access.accounts()
        self.registry=Registry(settings.upstream_file)
        self.remote=RemoteActions(self)
        self.semantic=SemanticAdvisor(settings.semantic_file,settings.database)

    def assess_semantics(self,action):
        if action.get('impact'):
            action['impact']['recovery_classification']=recovery.classification(action['impact'],action['request']['tool'])
        if action['state']=='blocked': return
        started=time.perf_counter()
        request={k:v for k,v in action['request'].items() if k!='idempotency_key'}
        advice=self.semantic.assess({'principal':action['principal'],'request':request,
            'policy_version':action['policy_version'],'resource':action.get('resource','customers'),
            'snapshot':action['impact'].get('before_hash',action['impact'].get('target_version')) if action['impact'] else None})
        action['semantic']=advice; action['semantic_ms']=round((time.perf_counter()-started)*1000,3)
        if advice['status']=='error':
            action.update(state='blocked',decision='block',reason_code='semantic_assessment_unavailable',result=None,review_digest=None)
        elif advice.get('advice',{}).get('risk') in {'high','critical'} or advice.get('advice',{}).get('score',0)>=.7:
            # Advice may restrict a request, never grant permission or erase the human requirement.
            if action['state']=='executed': action.update(state='blocked',decision='block',reason_code='semantic_risk_block',result=None)
            elif advice['advice']['risk']=='critical' or advice['advice']['score']>=.9:
                action['risk']='critical'; action['confirmation_required']=f"EXECUTE {action['impact']['changed_rows']}"

    def admit(self,conn,principal):
        if conn.execute('SELECT count(*) FROM actions').fetchone()[0]>=self.settings.max_actions:
            raise GateError('storage_budget_exhausted',429)
        if conn.execute('SELECT count(*) FROM actions WHERE principal=? AND created>?',(principal,self.clock()-60)).fetchone()[0]>=self.settings.calls_per_minute:
            raise GateError('rate_limited',429)
        if conn.execute("SELECT count(*) FROM actions WHERE principal=? AND state='pending'",(principal,)).fetchone()[0]>=self.settings.max_pending:
            raise GateError('pending_budget_exhausted',429)

    @property
    def policy_version(self):
        return digest({'base':self.settings.policy_version,'cel':self.policy.active.version,
            'semantic':self.semantic.config.model_dump() if self.semantic.config else None})

    def _event(self, conn, action: dict, kind: str, **detail) -> None:
        self.store.audit(conn, action["id"], {"kind": kind, "at": self.clock(),
                         "state": action["state"], "trace_id":action.get('trace_id',action['id']),
                         "request_id":observability.request_id.get() or action.get('request_id'),"detail": detail})

    def _finish(self, conn, action: dict, state: str, reason_code: str, **detail) -> dict:
        governance.settle(conn,action,state)
        if action['state']=='pending': action['queue_ms']=max(0,(self.clock()-action['created_at'])*1000)
        action.update(state=state, reason_code=reason_code, version=action["version"] + 1)
        self.store.save(conn, action)
        self._event(conn, action, "action." + state, **detail)
        return action

    def expire(self) -> int:
        with self.store.transaction() as conn:
            now=self.clock()
            prior=conn.execute("SELECT value FROM meta WHERE key='clock_high_water'").fetchone()
            if not math.isfinite(now) or (prior and now<float(prior[0])-1):
                raise GateError('clock_regression_detected',503)
            conn.execute("INSERT OR REPLACE INTO meta VALUES('clock_high_water',?)",(str(max(now,float(prior[0]) if prior else now)),))
            rows = conn.execute("SELECT document FROM actions WHERE state='pending' AND expires<=?",
                                (self.clock(),)).fetchall()
            for row in rows:
                self._finish(conn, json.loads(row[0]), "expired", "approval_expired")
            for row in conn.execute("SELECT document FROM actions WHERE state='executing'").fetchall():
                action=json.loads(row[0])
                if self.clock()>=action['execution_deadline']: self._finish(conn,action,'unknown','execution_lease_expired')
        return len(rows)

    def reload_policy(self):
        with self.policy.lock:
            previous=self.policy.active
            try:
                from .policy import Policy
                if self.policy.path is None:raise ValueError('no configured policy file')
                text=self.policy.read_candidate();replacement=Policy.parse(text)
                version=replacement.version
                with self.store.transaction() as conn:
                    self.policy.synchronize(conn)
                    previous=self.policy.active
                    conn.execute("UPDATE meta SET value=? WHERE key='active_policy'",(text,))
                    self.store.audit(conn,'governance:policy',{'kind':'governance.changed','at':self.clock(),
                        'state':'activated','detail':{'kind':'policy_reload','previous':previous.version,'version':version}})
                self.policy.active,self.policy._source=replacement,text
                return {'version':version,'pending_effect':'prior policy approvals become stale'}
            except Exception:
                self.policy.active=previous
                raise GateError('policy_reload_failed',422) from None

    def submit(self, call: Invocation, principal: str = "agent:demo") -> dict:
        with self.policy.lock:
            if call.tool.startswith('upstream:'): return self.remote.submit(call,principal)
            if call.arguments: raise GateError('tool_arguments_invalid',422)
            return self._submit(call,principal)

    def _submit(self, call: Invocation, principal: str) -> dict:
        started = time.perf_counter()
        request_hash = digest({"principal": principal, "call": call.model_dump()})
        self.expire()
        with self.store.transaction() as conn:
            self.policy.synchronize(conn)
            existing = conn.execute("SELECT request_hash,document FROM actions WHERE principal=? AND idem=?",
                                    (principal, call.idempotency_key)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise GateError("idempotency_conflict")
                governance.duplicate_hit(conn)
                return json.loads(existing["document"])
            if conn.execute("SELECT count(*) FROM actions").fetchone()[0] >= self.settings.max_actions:
                raise GateError("storage_budget_exhausted", 429)
            recent = conn.execute("SELECT count(*) FROM actions WHERE principal=? AND created>?",
                                  (principal, self.clock() - 60)).fetchone()[0]
            if recent >= self.settings.calls_per_minute:
                raise GateError("rate_limited", 429)
            action = {
                "id": uuid.uuid4().hex, "principal": principal, "request": call.model_dump(),
                "request_hash": request_hash, "created_at": self.clock(),
                "expires_at": self.clock() + self.settings.ttl_seconds,
                "policy_version": self.policy_version, "version": 1,
                "state": "blocked", "decision": "block", "reason_code": "unsupported_or_invalid_sql",
                "risk": "blocked", "impact": None, "result": None, "review_digest": None,
                "confirmation_required": "", "reviewer": None,
                "trace_id":uuid.uuid4().hex,"request_id":observability.request_id.get() or uuid.uuid4().hex,
                "template_version":"review-v2",
            }
            static_start = time.perf_counter()
            try:
                try:
                    restore_plan=recovery.plan(conn,call.sql,principal) if call.tool=='restore' else None
                    operations = ['restore'] if restore_plan else classify(conn, call)
                finally:
                    action["static_ms"] = round((time.perf_counter() - static_start) * 1000, 3)
                if not operations:
                    policy,hits=self.policy.active.evaluate({'tool':call.tool,'resource':'customers','principal':principal,
                        'operation':'read','changed_rows':0,'matched_rows':0},False)
                    action['rule_ids']=hits
                    if policy=='pass':
                        action.update(state="executed", decision="pass", reason_code="bounded_read",risk="low",result=execute(conn,call))
                    elif policy=='block':
                        action['reason_code']='policy_block'
                    else:
                        impact=preview(conn,call,operations)
                        action.update(state='pending',decision='need_approval',reason_code='policy_requires_review',risk='high',impact=impact)
                        action['review_digest']=digest({'request':request_hash,'impact':impact,'policy':action['policy_version']})
                else:
                    pending = conn.execute("SELECT count(*) FROM actions WHERE principal=? AND state='pending'",
                                           (principal,)).fetchone()[0]
                    if pending >= self.settings.max_pending:
                        action["reason_code"] = "pending_budget_exhausted"
                    else:
                        dry_start = time.perf_counter()
                        impact = recovery.preview_restore(conn,restore_plan) if restore_plan else preview(conn, call, operations)
                        impact.update(source='isolated_sqlite_clone',generated_at=self.clock(),target='synthetic:customers',
                                      schema_version=digest(SCHEMA),
                                      sample_limit=5,returned_rows_limit=100)
                        action["preview_ms"] = round((time.perf_counter() - dry_start) * 1000, 3)
                        risk = "critical" if impact["changed_rows"] >= self.settings.critical_rows else "high"
                        action.update(state="pending", decision="need_approval", reason_code="write_requires_review",
                                      risk=risk, impact=impact)
                        if risk == "critical":
                            action["confirmation_required"] = f"EXECUTE {impact['changed_rows']}"
                        action["review_digest"] = digest({"request": request_hash, "impact": impact,
                                                         "policy": action["policy_version"]})
                        policy,hits=self.policy.active.evaluate({'tool':call.tool,'resource':'customers','principal':principal,
                            'operation':'+'.join(operations),'changed_rows':impact['changed_rows'],'matched_rows':impact['matched_rows']},True)
                        action['rule_ids']=hits
                        if policy=='block':
                            action.update(state='blocked',decision='block',reason_code='policy_block',risk='blocked',review_digest=None)
            except (sqlite3.Error, ValueError, OverflowError):
                # Failure to compile or preview never creates permission to execute.
                action.update(state="blocked", decision="block", reason_code="unsupported_or_invalid_sql",
                              risk="blocked", result=None)
            action["evaluation_ms"] = round((time.perf_counter() - started) * 1000, 3)
            action['resource']='customers'
            self.assess_semantics(action)
            action['evaluation_ms']=round((time.perf_counter()-started)*1000,3)
            action['reviewers']=self.access.route(action)
            if action['state']=='pending':
                if not action['reviewers']:
                    action.update(state='blocked',decision='block',reason_code='review_route_missing',review_digest=None)
                elif conn.execute("SELECT count(*) FROM actions WHERE principal=? AND state='pending'",(principal,)).fetchone()[0]>=self.settings.max_pending:
                    action.update(state='blocked',decision='block',reason_code='pending_budget_exhausted',review_digest=None)
                else:
                    action['review_digest']=self.review_digest(action)
                    if not governance.reserve(conn,action,self.settings,self.clock()):
                        action.update(state='blocked',decision='block',reason_code='risk_budget_exhausted',review_digest=None)
            conn.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)", (
                action["id"], principal, call.idempotency_key, request_hash, action["state"],
                action["created_at"], action["expires_at"], canonical(action)))
            # The original review snapshot is stored in the signed event, never recomputed for replay.
            self._event(conn, action, "action.evaluated", snapshot=action)
            return action

    def get(self, action_id: str, principal: str | None = None) -> dict:
        self.expire()
        with self.store.connection() as conn:
            row = conn.execute("SELECT document FROM actions WHERE id=?", (action_id,)).fetchone()
        if not row:
            raise GateError("not_found", 404)
        action = json.loads(row[0])
        if principal is not None and action["principal"] != principal:
            raise GateError("not_found", 404)
        return action

    @staticmethod
    def review_digest(action):
        return digest({'id':action['id'],'expires_at':action['expires_at'],'version':action['version'],
                       'request':action['request_hash'],'impact':action['impact'],
                       'policy':action['policy_version'],'reviewers':action.get('reviewers',['reviewer:owner']),
                       'upstream_config':action.get('upstream_config_digest'),'resource':action.get('resource'),
                       'risk':action['risk'],'semantic':action.get('semantic'),'template':action.get('template_version')})

    def list_actions(self, limit: int = 100, before: float | None = None, before_id: str | None = None, state_filter: str | None = None, reviewer: str | None = None) -> list[dict]:
        self.expire()
        with self.store.connection() as conn:
            rows = conn.execute("SELECT document FROM actions WHERE (? IS NULL OR state=?) AND (? IS NULL OR created<? OR (created=? AND id<?)) "
                                "ORDER BY created DESC,id DESC LIMIT ?", (state_filter, state_filter, before, before, before, before_id, self.settings.max_actions if reviewer else limit)).fetchall()
        actions=[json.loads(row[0]) for row in rows]
        return [a for a in actions if reviewer is None or self.access.can_review(reviewer,a)][:limit]

    def decide(self, action_id: str, decision: Decision, reviewer: str = "reviewer:owner") -> dict:
        with self.policy.lock:
            action=self.get(action_id)
            if action['request']['tool'].startswith('upstream:'): return self.remote.decide(action_id,decision,reviewer)
            return self._decide(action_id,decision,reviewer)

    def _decide(self, action_id: str, decision: Decision, reviewer: str) -> dict:
        self.expire()
        with self.store.transaction() as conn:
            self.policy.synchronize(conn)
            row = conn.execute("SELECT document FROM actions WHERE id=?", (action_id,)).fetchone()
            if not row:
                raise GateError("not_found", 404)
            action = json.loads(row[0])
            if action["principal"] == reviewer:
                raise GateError("self_approval_forbidden", 403)
            self.access.require(reviewer,action)
            if action["state"] != "pending":
                raise GateError("action_not_pending")
            if decision.expected_version != action["version"] or decision.review_digest != action["review_digest"]:
                raise GateError("review_binding_mismatch")
            if self.clock() >= action["expires_at"]:
                return self._finish(conn, action, "expired", "approval_expired")
            action["reviewer"] = reviewer
            action['batch_digest']=governance.batch_context.get()
            human = {"reviewer": reviewer, "decision": decision.decision, "reason": decision.reason,
                     "review_digest": decision.review_digest, "visible_ms_untrusted": decision.visible_ms,'batch_digest':action['batch_digest']}
            if decision.decision == "reject":
                return self._finish(conn, action, "rejected", "human_rejected", **human)
            if decision.confirmation != action["confirmation_required"]:
                raise GateError("impact_confirmation_required", 422)
            # BEGIN IMMEDIATE holds the writer lock through revalidation and actual execution.
            if action["policy_version"] != self.policy_version:
                return self._finish(conn, action, "stale", "policy_changed", **human)
            if fingerprint(snapshot(conn)) != action["impact"]["before_hash"]:
                return self._finish(conn, action, "stale", "target_changed", **human)
            if self.review_digest(action) != action["review_digest"]:
                return self._finish(conn, action, "failed", "stored_review_mismatch", **human)
            call = Invocation.model_validate(action["request"])
            if digest({"principal": action["principal"], "call": call.model_dump()}) != action["request_hash"]:
                return self._finish(conn, action, "failed", "stored_request_mismatch", **human)
            conn.execute("SAVEPOINT effect")
            execution_started=time.perf_counter()
            try:
                before=snapshot(conn)
                if call.tool=='restore':
                    stored_plan=recovery.plan(conn,call.sql,action['principal'])
                    if fingerprint(before)!=stored_plan['after_hash']: raise ValueError('recovery target drift')
                    recovery.apply_rows(conn,stored_plan['before_rows'])
                    result={'matched_rows':len(before),'rows':[],'truncated':False,'compensates':call.sql}
                else:
                    classify(conn, call)
                    result = execute(conn, call)
                if fingerprint(snapshot(conn)) != action["impact"]["after_hash"]:
                    raise ValueError("execution diverged from preview")
                if action['impact']['operations']:
                    recovery.save_plan(conn,action,before,snapshot(conn),self.clock())
                conn.execute("RELEASE effect")
            except (sqlite3.Error, ValueError, OverflowError):
                conn.execute("ROLLBACK TO effect")
                conn.execute("RELEASE effect")
                return self._finish(conn, action, "failed", "execution_failed", **human)
            action["result"] = result
            action['execution_ms']=(time.perf_counter()-execution_started)*1000
            action['recovery_plan_available']=bool(action['impact']['operations'])
            # Audit failure rolls back the effect too. No distributed exactly-once claim is made.
            return self._finish(conn, action, "executed", "human_approved", **human)

    def metrics(self, reviewer: str | None = None) -> dict:
        from . import telemetry
        self.expire()
        with self.store.connection() as conn:
            counts = dict(conn.execute("SELECT state,count(*) FROM actions GROUP BY state"))
            records = [json.loads(r[0]) for r in conn.execute(
                "SELECT document FROM actions ORDER BY created DESC LIMIT 1000")]
            customers = conn.execute("SELECT count(*) FROM customers").fetchone()[0]
            duplicate=conn.execute("SELECT value FROM meta WHERE key='idempotent_hits'").fetchone()
        if reviewer and self.settings.reviewer_file:
            records=[a for a in records if self.access.can_review(reviewer,a)]
            from collections import Counter
            counts=dict(Counter(a['state'] for a in records))
            customers=None
        def p95(key):
            values = sorted(a[key] for a in records if key in a)
            return values[max(0, (95 * len(values) + 99) // 100 - 1)] if values else None
        return {"states": counts, "customers": customers, "sample_size": len(records),
                "evaluation_p95_ms": p95("evaluation_ms"), "preview_p95_ms": p95("preview_ms"),
                "static_p95_ms": p95("static_ms"),
                'idempotent_receipts_total':int(duplicate[0]) if duplicate and not self.settings.reviewer_file else None,
                'provider_admission':self.semantic.ledger_summary() if not self.settings.reviewer_file else None,
                'telemetry':telemetry.metrics(self.store) if not self.settings.reviewer_file else None,
                **observability.summarize(records)}

    def audit_events(self,reviewer,action_id=None,after=0,limit=200):
        # Filter on the server before limiting. Revocation takes effect on every read.
        events=self.store.audit_events(action_id,after,self.settings.max_actions*4)
        visible=[]
        with self.store.connection() as conn:
            for event in events:
                row=conn.execute('SELECT document FROM actions WHERE id=?',(event['action_id'],)).fetchone()
                if (row and self.access.can_review(reviewer,json.loads(row[0]))) or (reviewer=='reviewer:owner' and event['event']['kind']=='governance.changed'):
                    visible.append(event)
                if len(visible)>=limit: break
        return visible

    def groups(self,reviewer):
        preference=self.governance_preference()
        window=preference.get('window_seconds',60) if preference.get('expires_at',0)>self.clock() and not preference.get('revoked') else 60
        return governance.groups(self.list_actions(self.settings.max_pending,state_filter='pending',reviewer=reviewer),window)

    def governance_preference(self):
        with self.store.connection() as conn:
            row=conn.execute("SELECT value FROM meta WHERE key='grouping_preference'").fetchone()
            return json.loads(row[0]) if row else {'version':0}

    def suggestions(self):
        with self.store.connection() as conn:
            rows=[json.loads(r[0]) for r in conn.execute("SELECT document FROM actions WHERE state IN ('executed','rejected') ORDER BY created DESC LIMIT 1000")]
        approved=[a for a in rows if a.get('reviewer') and a['reason_code']=='human_approved']
        if len(approved)<3: return []
        candidate={'kind':'group_window','window_seconds':120,'mode':'shadow','evidence_action_ids':sorted(a['id'] for a in approved),
                   'reason':'Multiple explicit reviews observed; suggest a wider display grouping window.',
                   'authorization_effect':'none; approval requirements, hard blocks, risk and budget stay enforced'}
        return [dict(candidate,digest=digest(candidate))]

    def change_governance(self,change,revoke=False):
        if not self.clock()<change.expires_at<=self.clock()+86400: raise GateError('governance_expiry_invalid',422)
        candidate=next((s for s in self.suggestions() if s['digest']==change.candidate_digest),None)
        if not revoke and candidate is None: raise GateError('suggestion_changed')
        with self.store.transaction() as conn:
            row=conn.execute("SELECT value FROM meta WHERE key='grouping_preference'").fetchone()
            old=json.loads(row[0]) if row else {'version':0}
            if old['version']!=change.expected_version: raise GateError('governance_version_conflict')
            preference={'version':old['version']+1,'window_seconds':120,'expires_at':change.expires_at,
                'revoked':revoke,'candidate_digest':change.candidate_digest,'reason':change.reason}
            conn.execute("INSERT OR REPLACE INTO meta VALUES('grouping_preference',?)",(canonical(preference),))
            self.store.audit(conn,'governance:'+change.candidate_digest,{'kind':'governance.changed','at':self.clock(),
                'state':'revoked' if revoke else 'activated','detail':preference})
            return preference

    def decide_group(self,batch,reviewer):
        with self.policy.lock:
            group=next((g for g in self.groups(reviewer) if g['id']==batch.group_id),None)
            if group is None or group['digest']!=batch.group_digest or sorted(batch.member_ids)!=[m['id'] for m in group['members']]:
                raise GateError('group_membership_changed')
            if batch.confirmation!=group['confirmation_required']:
                raise GateError('group_confirmation_required',422)
            if batch.decision=='approve' and group['cumulative_units']>=self.settings.critical_rows:
                scope=dict(group['members'][0],risk='critical')
                if reviewer not in self.access.route(scope): raise GateError('group_risk_route_forbidden',403)
            receipts=[]
            for member in group['members']:
                context=governance.batch_context.set(group['digest'])
                try:
                    # Each member remains a separate atomic effect/state/audit transaction.
                    item=self.decide(member['id'],Decision(decision=batch.decision,reason=batch.reason,
                        review_digest=member['review_digest'],expected_version=member['version'],
                        confirmation=member['confirmation_required']),reviewer)
                    receipts.append({'id':item['id'],'state':item['state'],'reason_code':item['reason_code']})
                except GateError as error:
                    receipts.append({'id':member['id'],'state':'conflict','reason_code':error.code})
                finally: governance.batch_context.reset(context)
            return {'group_id':group['id'],'group_digest':group['digest'],'receipts':receipts,
                    'atomicity':'per_member; prior effects may make later snapshots stale'}


def agent_view(action: dict) -> dict:
    """No reviewer credential, approval digest, audit snapshot or internal policy is returned."""
    return {k: action[k] for k in ("id", "state", "decision", "reason_code", "result", "expires_at")} | {
        'action_id':action['id'],'trace_id':action.get('trace_id',action['id']),
        'retryable':action['state'] in {'pending','executing','unknown'},
        'allowed_alternatives':['query_original_action','bounded_read'] if action['state'] in TERMINAL-{'executed'} else ['query_original_action'],
        "execution_occurred": None if action['state'] in {'executing','unknown'} else action["state"] == "executed",
        "next_step": "Query/reconcile this action ID. Do not create another execution attempt." if action['state'] in {'unknown','executing'}
        else "Poll action status; never treat pending as success." if action["state"] == "pending"
        else "Use a bounded SELECT or submit a narrower NEW action; do not retry rejected writes blindly."
        if action["state"] in TERMINAL - {"executed"} else "Read the result."}
