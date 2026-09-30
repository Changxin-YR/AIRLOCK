"""Durable review state machine. Network I/O never holds a metadata transaction."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any
from sqlalchemy import and_, func, or_, select, update

from .common import AirlockError, canonical, digest, sign
from .config import Settings
from .contracts import ApprovalDecision, TERMINAL, ToolRequest, normalize
from .plans import make_plan, validate_plan
from .policy import Policy, load_policy
from .runner import Runner
from .storage import Store, approvals, audit_events, jobs, operations, principals, review_views, sessions, telemetry

ALLOWED = {
    "RECEIVED": {"PREVIEWING", "BLOCKED", "EXPIRED", "CANCELLED"},
    "PREVIEWING": {"READY", "PENDING_APPROVAL", "BLOCKED", "EXPIRED", "CANCELLED"},
    "PENDING_APPROVAL": {"READY", "REJECTED", "EXPIRED", "CANCELLED", "STALE", "BLOCKED"},
    "READY": {"EXECUTING", "EXPIRED", "CANCELLED", "STALE", "BLOCKED"},
    "EXECUTING": {"SUCCEEDED", "STALE", "FAILED", "UNKNOWN", "EXPIRED"},
    "UNKNOWN": {"EXECUTING", "SUCCEEDED", "STALE", "FAILED", "EXPIRED"},
}


class Service:
    def __init__(self, store: Store, runner: Runner, settings: Settings, *, policy: Policy | None = None):
        self.store, self.runner, self.settings = store, runner, settings
        self.override_policy = policy
        self.owner = str(uuid.uuid4())

    def policy(self) -> Policy:
        return self.override_policy or load_policy(self.settings.policy_path)

    def _transition(self, conn, op: dict, state: str, **fields) -> dict:
        if state not in ALLOWED.get(op["state"], set()):
            raise RuntimeError(f"Invalid state transition {op['state']} -> {state}")
        changes = fields | {"state": state, "version": op["version"]+1, "updated_at": self.store.clock()}
        conn.execute(update(operations).where(operations.c.id == op["id"]).values(**changes))
        self.store.audit(conn, op, "STATE_CHANGED", {"from": op["state"], "to": state,
                         "reason_code": fields.get("reason_code", op.get("reason_code"))})
        return op | changes

    def _agent_current(self, conn, op: dict) -> dict:
        agent = self.store.row(conn, principals, principals.c.id == op["principal_id"])
        if (not agent or not agent["active"] or agent["kind"] != "agent"
                or agent["scope"] != op["scope"] or agent["version"] != op["auth_version"]
                or op["tool"] not in json.loads(agent["tools_json"])):
            raise AirlockError("AUTH_REVOKED", "请求者当前不再具备此操作权限。", 403)
        return agent

    def _human_current(self, conn, supplied: dict) -> dict:
        human = self.store.row(conn, principals, principals.c.id == supplied["id"])
        session = self.store.row(conn, sessions, sessions.c.token_hash == supplied.get("session_hash", ""))
        if (not human or not human["active"] or human["kind"] != "human" or not session
                or session["principal_id"] != human["id"] or session["auth_version"] != human["version"]
                or session["expires_at"] <= self.store.clock()):
            raise AirlockError("LOGIN_REQUIRED", "审批身份或会话已失效。", 401)
        return human

    @staticmethod
    def _access(op: dict | None, principal: dict) -> None:
        if (not op or op["scope"] != principal["scope"]
                or (principal["kind"] == "agent" and op["principal_id"] != principal["id"])):
            raise AirlockError("NOT_FOUND", "未找到有权访问的操作。", 404)

    def _enqueue(self, conn, op_id: str, kind: str) -> None:
        existing = self.store.row(conn, jobs, and_(jobs.c.operation_id == op_id, jobs.c.kind == kind))
        if not existing:
            conn.execute(jobs.insert().values(id=str(uuid.uuid4()), operation_id=op_id, kind=kind,
                status="queued", available_at=self.store.clock(), lease_until=0, revision=0, attempts=0))

    def public(self, op: dict, *, detail: bool = False) -> dict:
        request = json.loads(op["request_json"])
        result = {key: op[key] for key in ("id", "state", "decision", "reason_code", "version",
                                         "created_at", "updated_at", "expires_at", "tool")}
        result.update(task=request["task"], run_id=request["run_id"], resource_id=request["resource_id"],
                      summary=json.loads(op["summary_json"]) if op["summary_json"] else None,
                      result=json.loads(op["result_json"]) if op["result_json"] else None,
                      error=json.loads(op["error_json"]) if op["error_json"] else None,
                      retry_after_seconds=1 if op["state"] not in TERMINAL else None)
        if detail:
            result.update(request=request, plan=json.loads(op["plan_json"]) if op["plan_json"] else None)
        return result

    def submit(self, agent: dict, request: ToolRequest, key: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,100}", key):
            raise AirlockError("INVALID_IDEMPOTENCY_KEY", "需要 8–100 位稳定幂等键。", 422)
        if agent["kind"] != "agent":
            raise AirlockError("AGENT_REQUIRED", "该入口只接受 Agent 服务身份。", 403)
        policy = self.policy()
        data = normalize(request)
        fingerprint = digest(data)
        with self.store.transaction() as conn:
            candidate = {"principal_id": agent["id"], "scope": agent["scope"],
                         "auth_version": agent["version"], "tool": request.tool}
            self._agent_current(conn, candidate)
            old = self.store.row(conn, operations, and_(operations.c.principal_id == agent["id"],
                                                        operations.c.idempotency_key == key))
            if old:
                if old["request_digest"] != fingerprint:
                    raise AirlockError("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同请求。")
                return self.public(old)
            active_count = conn.execute(select(func.count()).select_from(operations).where(
                operations.c.principal_id == agent["id"], operations.c.state.not_in(TERMINAL))).scalar_one()
            total = conn.execute(select(func.count()).select_from(operations).where(
                operations.c.principal_id == agent["id"])).scalar_one()
            if active_count >= 50 or total >= 2000:
                raise AirlockError("QUEUE_LIMIT", "此演示身份的请求配额已满。", 429)
            timestamp = self.store.clock()
            op = candidate | {"id": str(uuid.uuid4()), "idempotency_key": key, "request_digest": fingerprint,
                "request_json": canonical(data), "state": "RECEIVED", "decision": None, "reason_code": None,
                "version": 1, "created_at": timestamp, "updated_at": timestamp,
                "expires_at": timestamp+policy.approval_ttl_seconds, "plan_json": None, "summary_json": None,
                "permit_json": None, "result_json": None, "error_json": None}
            conn.execute(operations.insert().values(**op))
            self.store.audit(conn, op, "REQUEST_RECEIVED", {"request_digest": fingerprint, "tool": request.tool})
            self._enqueue(conn, op["id"], "preview")
            return self.public(op)

    def get(self, op_id: str, principal: dict, *, provide_view: bool = False) -> dict:
        with self.store.transaction() as conn:
            op = self.store.row(conn, operations, operations.c.id == op_id)
            self._access(op, principal)
            if provide_view and principal["kind"] == "human" and op["plan_json"]:
                human = self._human_current(conn, principal)
                self._access(op, human)
                plan = json.loads(op["plan_json"])
                condition = and_(review_views.c.operation_id == op_id,
                                 review_views.c.session_hash == principal["session_hash"],
                                 review_views.c.view_digest == plan["view_digest"])
                if not self.store.row(conn, review_views, condition):
                    conn.execute(review_views.insert().values(id=str(uuid.uuid4()), operation_id=op_id,
                        session_hash=principal["session_hash"], principal_id=human["id"],
                        view_digest=plan["view_digest"], created_at=self.store.clock()))
                    self.store.audit(conn, op, "VIEW_PROVIDED", {"reviewer": human["id"],
                        "view_digest": plan["view_digest"], "view_schema_version": plan["view_schema_version"]})
            return self.public(op, detail=principal["kind"] == "human")

    def list(self, principal: dict, *, state: str | None = None, offset: int = 0, limit: int = 30) -> dict:
        conditions = [operations.c.scope == principal["scope"]]
        if principal["kind"] == "agent": conditions.append(operations.c.principal_id == principal["id"])
        if state: conditions.append(operations.c.state == state)
        # Do not load full preview bodies for a list view.
        columns = [c for c in operations.c if c.name not in {"plan_json", "permit_json"}]
        with self.store.engine.connect() as conn:
            total = conn.execute(select(func.count()).select_from(operations).where(*conditions)).scalar_one()
            rows = conn.execute(select(*columns).where(*conditions).order_by(
                operations.c.created_at.desc(), operations.c.id.desc()).limit(limit).offset(offset)).mappings().all()
        return {"items": [self.public(dict(r)) for r in rows], "total": total,
                "next_offset": offset+limit if offset+limit < total else None}

    def decide(self, op_id: str, supplied: dict, decision: ApprovalDecision) -> dict:
        body = decision.model_dump(mode="json")
        with self.store.transaction() as conn:
            human = self._human_current(conn, supplied)
            op = self.store.row(conn, operations, operations.c.id == op_id)
            self._access(op, human)
            prior = self.store.row(conn, approvals, approvals.c.operation_id == op_id)
            if prior:
                if (prior["principal_id"] == human["id"] and prior["decision_key"] == decision.decision_key
                        and prior["body_digest"] == digest(body)):
                    return self.public(op, detail=True)
                raise AirlockError("ALREADY_DECIDED", "此操作已有审批结果，请刷新状态。")
            if op["state"] != "PENDING_APPROVAL" or op["version"] != decision.expected_version:
                raise AirlockError("VERSION_CONFLICT", "操作状态已改变，请刷新后重新查看。")
            plan = json.loads(op["plan_json"])
            validate_plan(plan)
            if plan["plan_digest"] != decision.plan_digest or plan["view_digest"] != decision.view_digest:
                raise AirlockError("PLAN_MISMATCH", "批准内容与提供的预览不一致。")
            viewed = self.store.row(conn, review_views, and_(review_views.c.operation_id == op_id,
                review_views.c.session_hash == supplied["session_hash"], review_views.c.view_digest == decision.view_digest))
            if not viewed:
                raise AirlockError("VIEW_REQUIRED", "请在当前会话中读取完整审批详情后再决定。", 403)
            if self.store.clock() >= op["expires_at"]:
                return self.public(self._transition(conn, op, "EXPIRED", reason_code="APPROVAL_EXPIRED"), detail=True)
            try:
                self._agent_current(conn, op)
            except AirlockError as exc:
                return self.public(self._transition(conn, op, "BLOCKED", reason_code=exc.code,
                    error_json=canonical(exc.public(op_id))), detail=True)
            if plan["policy_version"] != self.policy().version:
                return self.public(self._transition(conn, op, "STALE", reason_code="POLICY_CHANGED"), detail=True)
            conn.execute(approvals.insert().values(operation_id=op_id, principal_id=human["id"],
                principal_version=human["version"], decision_key=decision.decision_key, body_digest=digest(body),
                decision=decision.decision, reason=decision.reason, plan_digest=decision.plan_digest,
                view_digest=decision.view_digest, view_json=canonical(plan["view"]), created_at=self.store.clock()))
            self.store.audit(conn, op, "HUMAN_DECISION", {"reviewer": human["id"], "decision": decision.decision,
                "reason": decision.reason, "plan_digest": decision.plan_digest, "view_digest": decision.view_digest})
            new_state = "READY" if decision.decision == "approve" else "REJECTED"
            op = self._transition(conn, op, new_state, reason_code="HUMAN_APPROVED" if new_state == "READY" else "HUMAN_REJECTED")
            if new_state == "READY": self._enqueue(conn, op_id, "execute")
            return self.public(op, detail=True)

    def cancel(self, op_id: str, principal: dict) -> dict:
        with self.store.transaction() as conn:
            if principal["kind"] == "human": self._human_current(conn, principal)
            op = self.store.row(conn, operations, operations.c.id == op_id)
            self._access(op, principal)
            if op["state"] == "CANCELLED": return self.public(op)
            if op["state"] not in {"RECEIVED", "PREVIEWING", "PENDING_APPROVAL", "READY"}:
                raise AirlockError("NOT_CANCELLABLE", "执行已领取或操作已结束，不能承诺取消。")
            op = self._transition(conn, op, "CANCELLED", reason_code="USER_CANCELLED")
            conn.execute(update(jobs).where(jobs.c.operation_id == op_id).values(status="done"))
            return self.public(op)

    def _claim(self) -> tuple[dict, dict] | None:
        timestamp = self.store.clock()
        with self.store.transaction() as conn:
            expiring = conn.execute(select(operations).where(operations.c.expires_at <= timestamp,
                operations.c.state.in_({"RECEIVED", "PREVIEWING", "PENDING_APPROVAL", "READY"})).limit(50)).mappings().all()
            for row in expiring:
                self._transition(conn, dict(row), "EXPIRED", reason_code="DEADLINE_EXPIRED")
                conn.execute(update(jobs).where(jobs.c.operation_id == row["id"]).values(status="done"))
            row = conn.execute(select(jobs).where(or_(
                and_(jobs.c.status == "queued", jobs.c.available_at <= timestamp),
                and_(jobs.c.status == "active", jobs.c.lease_until <= timestamp)))
                .order_by(jobs.c.available_at, jobs.c.id).limit(1)).mappings().first()
            if not row: return None
            job = dict(row)
            op = self.store.row(conn, operations, operations.c.id == job["operation_id"])
            if op["state"] in TERMINAL:
                conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(status="done"))
                return None
            if job["kind"] == "execute" and op["state"] == "READY":
                try:
                    plan = json.loads(op["plan_json"])
                    validate_plan(plan)
                    self._agent_current(conn, op)
                    if plan["policy_version"] != self.policy().version:
                        raise AirlockError("STALE", "执行前策略版本已变化。")
                    approval = self.store.row(conn, approvals, approvals.c.operation_id == op["id"])
                    if op["decision"] == "need_approval":
                        if not approval or approval["decision"] != "approve":
                            raise AirlockError("AUTH_REQUIRED", "缺少合法人工审批。", 403)
                        reviewer = self.store.row(conn, principals, principals.c.id == approval["principal_id"])
                        if (not reviewer or not reviewer["active"] or reviewer["version"] != approval["principal_version"]
                                or reviewer["scope"] != op["scope"]):
                            raise AirlockError("AUTH_REVOKED", "审批者的权限已被撤销。", 403)
                    permit = {"operation_id": op["id"], "plan_digest": plan["plan_digest"],
                        "issued_at": timestamp, "not_after": min(op["expires_at"], timestamp+30),
                        "source": "human" if approval else "policy"}
                    envelope = {"plan": plan, "permit": permit, "signature": sign(permit, self.settings.execution_secret)}
                    self.store.audit(conn, op, "EXECUTION_AUTHORIZED", {"plan_digest": plan["plan_digest"],
                        "source": permit["source"], "not_after": permit["not_after"]})
                    op = self._transition(conn, op, "EXECUTING", permit_json=canonical(envelope))
                except AirlockError as exc:
                    state = "STALE" if exc.code == "STALE" else "BLOCKED"
                    self._transition(conn, op, state, reason_code=exc.code, error_json=canonical(exc.public(op["id"])))
                    conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(status="done"))
                    return None
            elif job["kind"] == "execute":
                if op["state"] not in {"EXECUTING", "UNKNOWN"} or not op["permit_json"]:
                    raise RuntimeError("Execution job without a durable authorization envelope")
                if op["state"] == "UNKNOWN": op = self._transition(conn, op, "EXECUTING")
                self.store.audit(conn, op, "RECOVERY_CLAIMED", {"original_permit_reused": True})
            elif op["state"] == "RECEIVED":
                op = self._transition(conn, op, "PREVIEWING")
            elif op["state"] != "PREVIEWING":
                raise RuntimeError("Preview job has an inconsistent lifecycle")
            new = {"status": "active", "lease_owner": self.owner, "lease_until": timestamp+self.settings.lease_seconds,
                   "revision": job["revision"]+1, "attempts": job["attempts"]+1}
            conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(**new))
            return job | new, op

    def _owned(self, conn, job: dict) -> bool:
        current = self.store.row(conn, jobs, jobs.c.id == job["id"])
        return bool(current and current["status"] == "active" and current["lease_owner"] == self.owner
                    and current["revision"] == job["revision"])

    def _finish_preview(self, job: dict, op: dict) -> None:
        try:
            with self.store.engine.connect() as conn: self._agent_current(conn, op)
            facts = self.runner.preview(json.loads(op["request_json"]), op["scope"])
            policy = self.policy()
            decision, reason = policy.decide(ToolRequest.model_validate_json(op["request_json"]), facts)
            with self.store.transaction() as conn:
                if not self._owned(conn, job): return
                fresh = self.store.row(conn, operations, operations.c.id == op["id"])
                agent = self._agent_current(conn, fresh)
                if self.store.clock() >= fresh["expires_at"]:
                    self._transition(conn, fresh, "EXPIRED", reason_code="PREVIEW_EXPIRED")
                else:
                    plan = make_plan(op["id"], agent, json.loads(op["request_json"]), facts, policy.version, op["expires_at"])
                    summary = {k: facts[k] for k in ("coverage", "direct_changed", "cascade_changed", "total_changed", "preview_ms")}
                    self.store.audit(conn, fresh, "PREVIEW_READY", {"plan_digest": plan["plan_digest"],
                        "view_digest": plan["view_digest"], "summary": summary})
                    state = {"pass": "READY", "block": "BLOCKED", "need_approval": "PENDING_APPROVAL"}[decision]
                    self._transition(conn, fresh, state, decision=decision, reason_code=reason,
                        plan_json=canonical(plan), summary_json=canonical(summary))
                    if state == "READY": self._enqueue(conn, op["id"], "execute")
                conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(status="done"))
        except Exception as exc:
            error = exc if isinstance(exc, AirlockError) else AirlockError("PREVIEW_UNAVAILABLE", "未取得完整预检证据，停止操作。", 503)
            with self.store.transaction() as conn:
                if not self._owned(conn, job): return
                fresh = self.store.row(conn, operations, operations.c.id == op["id"])
                if fresh["state"] == "PREVIEWING":
                    self._transition(conn, fresh, "BLOCKED", decision="block", reason_code=error.code,
                        error_json=canonical(error.public(op["id"])))
                conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(status="done"))

    def _finish_execute(self, job: dict, op: dict) -> None:
        recovered = job["attempts"] > 1 or op.get("reason_code") == "OUTCOME_UNKNOWN"
        try:
            envelope = json.loads(op["permit_json"])
            receipt = self.runner.lookup_receipt(op["id"], envelope["plan"]["plan_digest"]) if recovered else None
            # A lookup miss is not proof of no execution. The target rechecks under
            # BEGIN IMMEDIATE and deduplicates the original operation/permit.
            if receipt is None: receipt = self.runner.execute_once(envelope)
        except Exception as exc:
            definite = isinstance(exc, AirlockError) and exc.status < 500 and exc.code != "RECEIPT_CONFLICT"
            with self.store.transaction() as conn:
                if not self._owned(conn, job): return
                fresh = self.store.row(conn, operations, operations.c.id == op["id"])
                if definite:
                    state = exc.code if exc.code in {"STALE", "EXPIRED"} else "FAILED"
                    self._transition(conn, fresh, state, reason_code=exc.code, error_json=canonical(exc.public(op["id"])))
                    conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(status="done"))
                else:
                    error = AirlockError("OUTCOME_UNKNOWN", "执行结果尚未核实；不会创建新的操作重试。", 503)
                    self._transition(conn, fresh, "UNKNOWN", reason_code=error.code, error_json=canonical(error.public(op["id"])))
                    conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(
                        status="queued" if job["attempts"] < 5 else "done",
                        available_at=self.store.clock()+min(2**job["attempts"],30), lease_until=0))
            return
        # Outside the network exception handler: if this transaction fails AFTER
        # target commit, preserve the EXECUTING lease and recover from its receipt.
        with self.store.transaction() as conn:
            if not self._owned(conn, job): return
            fresh = self.store.row(conn, operations, operations.c.id == op["id"])
            plan = json.loads(fresh["plan_json"])
            if receipt.get("operation_id") != op["id"] or receipt.get("plan_digest") != plan["plan_digest"]:
                raise RuntimeError("Executor returned a mismatched receipt")
            self.store.audit(conn, fresh, "RECEIPT_RECOVERED" if recovered else "EXECUTION_RECEIPT", receipt)
            self._transition(conn, fresh, "SUCCEEDED", result_json=canonical(receipt), error_json=None, reason_code="RECEIPT_CONFIRMED" if recovered else fresh["reason_code"])
            conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(status="done"))

    def step(self) -> bool:
        claimed = self._claim()
        if claimed is None: return False
        job, op = claimed
        if job["kind"] == "preview": self._finish_preview(job, op)
        else: self._finish_execute(job, op)
        return True

    def drain(self, maximum: int = 100) -> None:
        """Deterministic CLI/test helper, not a replacement for persistent jobs."""
        for _ in range(maximum):
            if not self.step(): break

    def reconcile(self, op_id: str, supplied: dict) -> dict:
        with self.store.transaction() as conn:
            human = self._human_current(conn, supplied)
            op = self.store.row(conn, operations, operations.c.id == op_id)
            self._access(op, human)
            if op["state"] != "UNKNOWN": raise AirlockError("NOT_UNKNOWN", "只有结果未知的操作需要核实。")
            job = self.store.row(conn, jobs, and_(jobs.c.operation_id == op_id, jobs.c.kind == "execute"))
            if not job: raise AirlockError("NO_AUTHORIZATION", "未找到原执行记录。")
            conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(
                status="queued", available_at=self.store.clock(), attempts=0, lease_until=0))
            self.store.audit(conn, op, "MANUAL_RECONCILE_REQUESTED", {"reviewer": human["id"]})
            return self.public(op)

    def events(self, principal: dict, after: int = 0, limit: int = 100) -> list[dict]:
        conditions = [audit_events.c.scope == principal["scope"], audit_events.c.seq > after]
        if principal["kind"] == "agent": conditions.append(audit_events.c.requester == principal["id"])
        with self.store.engine.connect() as conn:
            rows = conn.execute(select(audit_events.c.seq, audit_events.c.operation_id, audit_events.c.event_type,
                audit_events.c.at).where(*conditions).order_by(audit_events.c.seq).limit(limit)).mappings().all()
        return [dict(row) for row in rows]

    def audit(self, op_id: str, principal: dict) -> dict:
        with self.store.engine.connect() as conn:
            op = self.store.row(conn, operations, operations.c.id == op_id)
            self._access(op, principal)
            if principal["kind"] != "human": raise AirlockError("HUMAN_REQUIRED", "审计详情需要审批身份。", 403)
            rows = conn.execute(select(audit_events).where(audit_events.c.operation_id == op_id)
                                .order_by(audit_events.c.ordinal)).mappings().all()
            approval = self.store.row(conn, approvals, approvals.c.operation_id == op_id)
        previous, valid, items = "0"*64, True, []
        for expected, row in enumerate(rows, start=1):
            data = json.loads(row["data_json"])
            body = {"operation_id": op_id, "ordinal": row["ordinal"], "event_type": row["event_type"],
                    "at": row["at"], "data": data, "prev_hash": row["prev_hash"]}
            valid &= row["ordinal"] == expected and row["prev_hash"] == previous and digest(body) == row["event_hash"]
            previous = row["event_hash"]
            items.append({"seq": row["seq"], "ordinal": row["ordinal"], "type": row["event_type"],
                          "at": row["at"], "data": data, "hash": previous})
        return {"items": items, "chain_valid": bool(valid), "integrity_scope": "local hash chain; not administrator-proof",
                "provided_approval_view": json.loads(approval["view_json"]) if approval else None}

    def record_telemetry(self, op_id: str, principal: dict, data: dict) -> None:
        with self.store.transaction() as conn:
            human = self._human_current(conn, principal)
            op = self.store.row(conn, operations, operations.c.id == op_id)
            self._access(op, human)
            prior = self.store.row(conn, telemetry, telemetry.c.event_id == data["event_id"])
            if prior:
                if prior["operation_id"] != op_id or prior["principal_id"] != human["id"] or prior["payload_json"] != canonical(data):
                    raise AirlockError("TELEMETRY_CONFLICT", "埋点幂等键冲突。")
                return
            conn.execute(telemetry.insert().values(event_id=data["event_id"], operation_id=op_id,
                principal_id=human["id"], payload_json=canonical(data), received_at=self.store.clock()))
