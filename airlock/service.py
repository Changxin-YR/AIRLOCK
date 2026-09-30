from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import and_, func, select

from airlock.common import DomainError, canonical, digest, now_ms
from airlock.config import ConfigSource, policy_hash
from airlock.contracts import AgentPrincipal, DecisionRequest, OperationRequest, authorize
from airlock.plans import make_plan, review_view, validate_plan
from airlock.policy import REASONS, decide
from airlock.runner import Runner, UncertainExecution
from airlock.storage import (
    TERMINAL,
    Store,
    approvals,
    audit_events,
    jobs,
    operations,
    views,
)


class ReviewService:
    def __init__(self, store: Store, source: ConfigSource, runner: Runner):
        self.store, self.source, self.runner = store, source, runner

    def submit(self, principal: AgentPrincipal, request: OperationRequest, key: str) -> dict:
        if not 16 <= len(key) <= 128 or not key.isascii():
            raise DomainError("IDEMPOTENCY_REQUIRED", "请提供 16–128 位 ASCII 幂等键。")
        principal = self.source.principal(principal.id)
        policy = self.source.policy()
        normalized = request.normalized()
        request_digest = digest(normalized)
        denied = None
        try:
            authorize(principal, request)
        except DomainError as exc:
            denied = exc
        with self.store.transaction() as conn:
            existing = (
                conn.execute(
                    select(operations).where(
                        operations.c.requester == principal.id, operations.c.idempotency_key == key
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                if existing["request_digest"] != request_digest:
                    raise DomainError("IDEMPOTENCY_CONFLICT", "相同幂等键不能对应不同请求。", 409)
                # Idempotency is not an authorization bypass for historical results.
                if denied and (existing["state"] != "BLOCKED" or existing["plan_json"]):
                    raise DomainError("NOT_FOUND", "原操作不存在或当前无权访问。", 404)
                return self.store.public(dict(existing))
            if request.supersedes_operation_id:
                old = self.store.get(conn, request.supersedes_operation_id)
                if old["requester"] != principal.id:
                    raise DomainError("NOT_FOUND", "原操作不存在或无权访问。", 404)
                if old["state"] not in TERMINAL - {"SUCCEEDED"}:
                    raise DomainError(
                        "UNRESOLVED_OPERATION", "原操作尚未安全终结，不能创建替代变更。", 409
                    )
            timestamp, operation_id = now_ms(), uuid.uuid4().hex
            values = {
                "id": operation_id,
                "requester": principal.id,
                "resource_id": request.resource_id,
                "idempotency_key": key,
                "request_digest": request_digest,
                "request_json": canonical(normalized),
                "state": "RECEIVED",
                "version": 1,
                "created_at": timestamp,
                "updated_at": timestamp,
                "expires_at": timestamp + policy.plan_ttl_seconds * 1000,
            }
            conn.execute(operations.insert().values(**values))
            op = self.store.get(conn, operation_id)
            self.store.audit(
                conn,
                operation_id,
                "REQUEST_RECEIVED",
                {
                    "state": "RECEIVED",
                    "requester": principal.id,
                    "request_digest": request_digest,
                    "tool": request.tool,
                    "source": "agent",
                },
            )
            if denied:
                op = self.store.transition(
                    conn,
                    op,
                    "BLOCKED",
                    decision="block",
                    reason_code=denied.code,
                    error_json=canonical(denied.public()),
                )
                self.store.audit(
                    conn, operation_id, "BLOCKED", {"state": "BLOCKED", "code": denied.code}
                )
            else:
                conn.execute(
                    jobs.insert().values(
                        operation_id=operation_id,
                        kind="preview",
                        state="queued",
                        lease_until=0,
                        attempts=0,
                        next_at=timestamp,
                    )
                )
            return self.store.public(op)

    def _expire_and_recover(self) -> None:
        now = now_ms()
        with self.store.transaction() as conn:
            expired = (
                conn.execute(
                    select(operations).where(
                        operations.c.expires_at <= now,
                        operations.c.state.in_(["RECEIVED", "PENDING_APPROVAL", "READY"]),
                    )
                )
                .mappings()
                .all()
            )
            for row in expired:
                op = self.store.transition(
                    conn,
                    dict(row),
                    "EXPIRED",
                    error_json=canonical(
                        {
                            "code": "PLAN_EXPIRED",
                            "safe_message": "计划已过期，未产生新变更。",
                            "retryable": False,
                        }
                    ),
                )
                conn.execute(
                    jobs.update().where(jobs.c.operation_id == op["id"]).values(state="done")
                )
                self.store.audit(conn, op["id"], "EXPIRED", {"state": "EXPIRED"})
            abandoned = (
                conn.execute(
                    select(jobs).where(jobs.c.state == "leased", jobs.c.lease_until <= now)
                )
                .mappings()
                .all()
            )
            for job in abandoned:
                op = self.store.get(conn, job["operation_id"])
                if op["state"] == "EXECUTING":
                    self.store.transition(
                        conn,
                        op,
                        "UNKNOWN",
                        error_json=canonical(
                            {
                                "code": "OUTCOME_UNKNOWN",
                                "safe_message": "正在通过目标回执核实结果，不会盲目重放。",
                                "retryable": False,
                            }
                        ),
                    )
                    conn.execute(
                        jobs.update()
                        .where(jobs.c.operation_id == op["id"])
                        .values(state="queued", kind="reconcile", next_at=now, lease_token=None)
                    )
                    self.store.audit(conn, op["id"], "RECOVERY_REQUIRED", {"state": "UNKNOWN"})
                elif op["state"] == "PREVIEWING":
                    self.store.transition(conn, op, "RECEIVED")
                    conn.execute(
                        jobs.update()
                        .where(jobs.c.operation_id == op["id"])
                        .values(state="queued", kind="preview", next_at=now, lease_token=None)
                    )
                    self.store.audit(conn, op["id"], "PREVIEW_REQUEUED", {"state": "RECEIVED"})
                elif op["state"] == "UNKNOWN":
                    conn.execute(
                        jobs.update()
                        .where(jobs.c.operation_id == op["id"])
                        .values(state="queued", next_at=now)
                    )
                else:
                    conn.execute(
                        jobs.update().where(jobs.c.operation_id == op["id"]).values(state="done")
                    )

    def _check_authorization(self, conn, op: dict, plan: dict) -> None:
        payload = validate_plan(plan)
        principal = self.source.principal(op["requester"])
        request = OperationRequest.model_validate(json.loads(op["request_json"]))
        authorize(principal, request)
        if (
            payload["operation_id"] != op["id"]
            or payload["request"] != request.normalized()
            or payload["expires_at"] != op["expires_at"]
        ):
            raise DomainError("INVALID_PLAN", "持久请求与计划不一致。", 409)
        if payload["principal_hash"] != digest(principal.permissions()) or payload[
            "policy_hash"
        ] != policy_hash(self.source.policy()):
            raise DomainError("AUTHORIZATION_CHANGED", "权限或策略已变化，需要重新预检。", 409)
        if op["ready_source"] == "human":
            approval = (
                conn.execute(select(approvals).where(approvals.c.operation_id == op["id"]))
                .mappings()
                .first()
            )
            reviewer = self.source.read().reviewer
            if (
                not approval
                or approval["decision"] != "approve"
                or approval["plan_digest"] != plan["plan_digest"]
                or not reviewer.active
                or approval["username"] != reviewer.username
                or op["resource_id"] not in reviewer.resources
            ):
                raise DomainError("APPROVAL_INVALID", "缺少当前有效的审批授权。", 403)
        elif op["ready_source"] == "policy":
            if (
                op["decision"] != "pass"
                or decide(request, payload["preview"], self.source.policy())[0] != "pass"
            ):
                raise DomainError("APPROVAL_REQUIRED", "此操作不能自动执行。", 403)
        else:
            raise DomainError("APPROVAL_REQUIRED", "此操作缺少执行来源。", 403)

    def _claim(self) -> tuple[dict, dict] | None:
        now, token = now_ms(), uuid.uuid4().hex
        config = self.source.read()
        with self.store.transaction() as conn:
            row = (
                conn.execute(
                    select(jobs)
                    .where(jobs.c.state == "queued", jobs.c.next_at <= now)
                    .order_by(jobs.c.next_at, jobs.c.operation_id)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            job = dict(row)
            op = self.store.get(conn, job["operation_id"])
            if job["kind"] == "execute":
                if op["state"] != "READY":
                    conn.execute(
                        jobs.update().where(jobs.c.operation_id == op["id"]).values(state="done")
                    )
                    return None
                try:
                    self._check_authorization(conn, op, json.loads(op["plan_json"]))
                except DomainError as exc:
                    self.store.transition(conn, op, "STALE", error_json=canonical(exc.public()))
                    conn.execute(
                        jobs.update().where(jobs.c.operation_id == op["id"]).values(state="done")
                    )
                    self.store.audit(
                        conn,
                        op["id"],
                        "AUTHORIZATION_CHANGED",
                        {"state": "STALE", "code": exc.code},
                    )
                    return None
                op = self.store.transition(conn, op, "EXECUTING")
                self.store.audit(
                    conn,
                    op["id"],
                    "EXECUTION_AUTHORIZED",
                    {
                        "state": "EXECUTING",
                        "plan_digest": json.loads(op["plan_json"])["plan_digest"],
                        "ready_source": op["ready_source"],
                    },
                )
            elif job["kind"] == "preview":
                if op["state"] != "RECEIVED":
                    conn.execute(
                        jobs.update().where(jobs.c.operation_id == op["id"]).values(state="done")
                    )
                    return None
                op = self.store.transition(conn, op, "PREVIEWING")
                self.store.audit(conn, op["id"], "PREVIEW_STARTED", {"state": "PREVIEWING"})
            elif op["state"] != "UNKNOWN":
                conn.execute(
                    jobs.update().where(jobs.c.operation_id == op["id"]).values(state="done")
                )
                return None
            patch = {
                "state": "leased",
                "lease_token": token,
                "lease_until": now + config.lease_ms,
                "attempts": job["attempts"] + 1,
            }
            conn.execute(jobs.update().where(jobs.c.operation_id == op["id"]).values(**patch))
            return op, {**job, **patch}

    @staticmethod
    def _owns(conn, job: dict) -> bool:
        current = conn.execute(
            select(jobs.c.state, jobs.c.lease_token).where(
                jobs.c.operation_id == job["operation_id"]
            )
        ).first()
        return bool(current and current[0] == "leased" and current[1] == job["lease_token"])

    def tick(self) -> bool:
        self._expire_and_recover()
        claimed = self._claim()
        if claimed is None:
            return False
        op, job = claimed
        if job["kind"] == "reconcile":
            self._reconcile(op, job)
        elif job["kind"] == "preview":
            self._preview(op, job)
        else:
            self._execute(op, job)
        return True

    def _preview(self, op: dict, job: dict) -> None:
        try:
            request = OperationRequest.model_validate(json.loads(op["request_json"]))
            principal, policy = self.source.principal(op["requester"]), self.source.policy()
            authorize(principal, request)
            preview = self.runner.preview(request, principal, policy)
            decision, reason = decide(request, preview, policy)
            plan = make_plan(op["id"], principal, request, preview, policy, op["expires_at"])
            state = {"pass": "READY", "block": "BLOCKED", "need_approval": "PENDING_APPROVAL"}[
                decision
            ]
            with self.store.transaction() as conn:
                if not self._owns(conn, job):
                    return
                current = self.store.get(conn, op["id"])
                if now_ms() >= op["expires_at"]:
                    self.store.transition(conn, current, "EXPIRED")
                    conn.execute(
                        jobs.update().where(jobs.c.operation_id == op["id"]).values(state="done")
                    )
                    self.store.audit(conn, op["id"], "EXPIRED", {"state": "EXPIRED"})
                    return
                error = (
                    {"code": reason, "safe_message": REASONS[reason], "retryable": False}
                    if decision == "block"
                    else None
                )
                self.store.transition(
                    conn,
                    current,
                    state,
                    decision=decision,
                    reason_code=reason,
                    ready_source="policy" if decision == "pass" else None,
                    plan_json=canonical(plan),
                    error_json=canonical(error) if error else None,
                )
                conn.execute(
                    jobs.update()
                    .where(jobs.c.operation_id == op["id"])
                    .values(
                        kind="execute" if decision == "pass" else "preview",
                        state="queued" if decision == "pass" else "done",
                        lease_token=None,
                        next_at=now_ms(),
                    )
                )
                self.store.audit(
                    conn,
                    op["id"],
                    "PREVIEW_COMPLETED",
                    {
                        "state": state,
                        "decision": decision,
                        "reason_code": reason,
                        "plan_digest": plan["plan_digest"],
                        "total_changes": preview["total_changes"],
                        "direct_changes": preview["direct_changes"],
                        "cascaded_changes": preview["cascaded_changes"],
                        "preview_ms": preview["preview_ms"],
                    },
                )
        except DomainError as exc:
            self._finish_error(op, job, "BLOCKED", exc, decision="block")
        except Exception:
            self._finish_error(
                op, job, "FAILED", DomainError("PREVIEW_FAILED", "预检失败，未执行写入。", 503)
            )

    def _finish_error(self, op: dict, job: dict, state: str, error: DomainError, **patch) -> None:
        with self.store.transaction() as conn:
            if not self._owns(conn, job):
                return
            current = self.store.get(conn, op["id"])
            self.store.transition(
                conn, current, state, error_json=canonical(error.public()), **patch
            )
            conn.execute(
                jobs.update()
                .where(jobs.c.operation_id == op["id"])
                .values(
                    state="queued" if state == "UNKNOWN" else "done",
                    kind="reconcile" if state == "UNKNOWN" else job["kind"],
                    next_at=now_ms() + 250,
                    lease_token=None,
                )
            )
            self.store.audit(
                conn,
                op["id"],
                "OUTCOME_UNKNOWN" if state == "UNKNOWN" else state,
                {"state": state, "code": error.code},
            )

    def _execute(self, op: dict, job: dict) -> None:
        try:
            plan = json.loads(op["plan_json"])
            # Recheck immediately before sending, not just when creating a job.
            with self.store.read() as conn:
                self._check_authorization(conn, op, plan)
            receipt = self.runner.execute(plan)
            self._finish_receipt(op, job, receipt, recovered=False)
        except UncertainExecution:
            self._finish_error(
                op,
                job,
                "UNKNOWN",
                DomainError("OUTCOME_UNKNOWN", "响应中断，正在查询执行回执。", 503),
            )
        except DomainError as exc:
            if exc.code == "TARGET_UNAVAILABLE":
                self._finish_error(
                    op,
                    job,
                    "UNKNOWN",
                    DomainError("OUTCOME_UNKNOWN", "目标 I/O 异常，必须通过回执核实结果。", 503),
                )
                return
            state = (
                "STALE"
                if exc.code
                in {
                    "TARGET_STALE",
                    "POLICY_CHANGED",
                    "SCHEMA_UNSUPPORTED",
                    "AUTHORIZATION_CHANGED",
                    "PRINCIPAL_REVOKED",
                }
                else "EXPIRED"
                if exc.code == "PLAN_EXPIRED"
                else "FAILED"
            )
            self._finish_error(op, job, state, exc)
        except Exception:
            # Includes metadata failure after target commit: never claim the write did not happen.
            self._finish_error(
                op,
                job,
                "UNKNOWN",
                DomainError("OUTCOME_UNKNOWN", "执行结果待核实，不会盲目重放。", 503),
            )

    def _finish_receipt(self, op: dict, job: dict, receipt: dict, recovered: bool) -> None:
        expected = json.loads(op["plan_json"])["plan_digest"]
        if receipt.get("operation_id") != op["id"] or receipt.get("plan_digest") != expected:
            raise UncertainExecution("receipt binding mismatch")
        with self.store.transaction() as conn:
            if not self._owns(conn, job):
                return
            current = self.store.get(conn, op["id"])
            self.store.transition(
                conn, current, "SUCCEEDED", result_json=canonical(receipt), error_json=None
            )
            conn.execute(
                jobs.update()
                .where(jobs.c.operation_id == op["id"])
                .values(state="done", lease_token=None)
            )
            self.store.audit(
                conn,
                op["id"],
                "RECEIPT_RECOVERED" if recovered else "EXECUTION_SUCCEEDED",
                {"state": "SUCCEEDED", "receipt": receipt},
            )

    def _reconcile(self, op: dict, job: dict) -> None:
        try:
            receipt = self.runner.receipt(op["id"], json.loads(op["plan_json"])["plan_digest"])
            if receipt is not None:
                self._finish_receipt(op, job, receipt, recovered=True)
                return
        except Exception:
            pass  # Remain UNKNOWN; no side effect is retried here.
        with self.store.transaction() as conn:
            if self._owns(conn, job):
                conn.execute(
                    jobs.update()
                    .where(jobs.c.operation_id == op["id"])
                    .values(
                        state="queued" if job["attempts"] < 10 else "done",
                        next_at=now_ms() + min(job["attempts"] * 1000, 10000),
                        lease_token=None,
                    )
                )
                self.store.audit(
                    conn,
                    op["id"],
                    "RECONCILIATION_PENDING",
                    {"state": "UNKNOWN", "attempt": job["attempts"]},
                )

    def get_for_agent(self, principal: AgentPrincipal, operation_id: str) -> dict:
        with self.store.read() as conn:
            op = self.store.get(conn, operation_id)
            try:
                current_principal = self.source.principal(principal.id)
                if op["requester"] != current_principal.id:
                    raise DomainError("FORBIDDEN", "无权访问。", 403)
                # Recheck current grants before returning previously authorized data.
                authorize(
                    current_principal,
                    OperationRequest.model_validate(json.loads(op["request_json"])),
                )
            except DomainError:
                # A submitter may inspect their own blocked envelope, never protected data.
                if op["requester"] != principal.id or op["state"] != "BLOCKED" or op["plan_json"]:
                    raise DomainError("NOT_FOUND", "操作不存在或无权访问。", 404) from None
            result = self.store.public(op)
            if op["state"] == "BLOCKED":
                result["result"] = None
            return result

    def human_operation(self, operation_id: str) -> dict:
        with self.store.read() as conn:
            op = self.store.get(conn, operation_id)
            if op["resource_id"] not in self.source.read().reviewer.resources:
                raise DomainError("NOT_FOUND", "操作不存在或无权访问。", 404)
            return op

    def list_reviews(self, state: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        predicate = operations.c.resource_id.in_(self.source.read().reviewer.resources)
        if state:
            predicate = and_(predicate, operations.c.state == state)
        with self.store.read() as conn:
            total = conn.execute(
                select(func.count()).select_from(operations).where(predicate)
            ).scalar_one()
            rows = (
                conn.execute(
                    select(operations)
                    .where(predicate)
                    .order_by(operations.c.created_at.desc(), operations.c.id)
                    .limit(limit)
                    .offset(offset)
                )
                .mappings()
                .all()
            )
        return {
            "items": [self.store.public(dict(r)) for r in rows],
            "total": total,
            "has_more": offset + len(rows) < total,
        }

    def get_review(self, operation_id: str, session: dict, read_only: bool = False) -> dict:
        op = self.human_operation(operation_id)
        public = self.store.public(op)
        if not op["plan_json"]:
            return {"operation": public, "view": None, "view_id": None, "view_digest": None}
        view = review_view(json.loads(op["plan_json"]), op["reason_code"] or "")
        view_digest, view_id = digest(view), None
        if not read_only and op["state"] == "PENDING_APPROVAL" and now_ms() < op["expires_at"]:
            view_id = uuid.uuid4().hex
            with self.store.transaction() as conn:
                conn.execute(
                    views.insert().values(
                        id=view_id,
                        operation_id=operation_id,
                        session_hash=session["token_hash"],
                        plan_digest=view["plan_digest"],
                        view_digest=view_digest,
                        view_json=canonical(view),
                        created_at=now_ms(),
                        expires_at=min(op["expires_at"], session["expires_at"]),
                    )
                )
                self.store.audit(
                    conn,
                    operation_id,
                    "REVIEW_VIEW_SERVED",
                    {
                        "state": op["state"],
                        "view_id": view_id,
                        "view_digest": view_digest,
                        "schema": view["schema"],
                        "plan_digest": view["plan_digest"],
                        "username": session["username"],
                    },
                )
        return {"operation": public, "view": view, "view_id": view_id, "view_digest": view_digest}

    def historical_view(self, operation_id: str, view_id: str) -> dict:
        self.human_operation(operation_id)
        with self.store.read() as conn:
            row = (
                conn.execute(
                    select(views).where(views.c.id == view_id, views.c.operation_id == operation_id)
                )
                .mappings()
                .first()
            )
        if not row:
            raise DomainError("NOT_FOUND", "历史审批视图不存在。", 404)
        snapshot = json.loads(row["view_json"])
        if digest(snapshot) != row["view_digest"]:
            raise DomainError("AUDIT_INTEGRITY_FAILURE", "历史审批视图与其摘要不一致。", 409)
        return {
            "read_only": True,
            "view_id": view_id,
            "view_digest": row["view_digest"],
            "created_at": row["created_at"],
            "snapshot": snapshot,
        }

    def decide_review(self, operation_id: str, body: DecisionRequest, session: dict) -> dict:
        self.human_operation(operation_id)
        decision_digest = digest({"operation_id": operation_id, **body.model_dump()})
        with self.store.transaction() as conn:
            op = self.store.get(conn, operation_id)
            previous = (
                conn.execute(
                    select(approvals).where(
                        approvals.c.username == session["username"],
                        approvals.c.idempotency_key == body.idempotency_key,
                    )
                )
                .mappings()
                .first()
            )
            if previous:
                if previous["request_digest"] != decision_digest:
                    raise DomainError("IDEMPOTENCY_CONFLICT", "此审批幂等键已用于其他决定。", 409)
                return self.store.public(op)
            if op["state"] != "PENDING_APPROVAL" or op["version"] != body.expected_version:
                raise DomainError("STATE_CONFLICT", "操作已被处理或状态已变化，请刷新。", 409)
            if op["expires_at"] <= now_ms():
                raise DomainError("PLAN_EXPIRED", "审批窗口已过期。", 409)
            plan = json.loads(op["plan_json"])
            validate_plan(plan)
            if body.plan_digest != plan["plan_digest"]:
                raise DomainError("PLAN_MISMATCH", "审批内容与原计划不一致。", 409)
            served = (
                conn.execute(select(views).where(views.c.id == body.view_id)).mappings().first()
            )
            if (
                not served
                or served["operation_id"] != operation_id
                or served["session_hash"] != session["token_hash"]
                or served["plan_digest"] != body.plan_digest
                or served["expires_at"] <= now_ms()
            ):
                raise DomainError("VIEW_MISMATCH", "请先在当前登录会话查看此审批证据。", 409)
            expected_view = review_view(plan, op["reason_code"] or "")
            if (
                served["view_digest"] != digest(expected_view)
                or digest(json.loads(served["view_json"])) != served["view_digest"]
            ):
                raise DomainError("VIEW_MISMATCH", "审批视图摘要不一致。", 409)
            conn.execute(
                approvals.insert().values(
                    operation_id=operation_id,
                    username=session["username"],
                    decision=body.decision,
                    reason=body.reason,
                    plan_digest=body.plan_digest,
                    view_digest=served["view_digest"],
                    view_id=body.view_id,
                    idempotency_key=body.idempotency_key,
                    request_digest=decision_digest,
                    created_at=now_ms(),
                )
            )
            state = "READY" if body.decision == "approve" else "REJECTED"
            op = self.store.transition(
                conn,
                op,
                state,
                ready_source="human" if body.decision == "approve" else None,
                error_json=canonical(
                    {"code": "HUMAN_REJECTED", "safe_message": body.reason, "retryable": False}
                )
                if body.decision == "reject"
                else None,
            )
            if body.decision == "approve":
                conn.execute(
                    jobs.update()
                    .where(jobs.c.operation_id == operation_id)
                    .values(kind="execute", state="queued", next_at=now_ms(), lease_token=None)
                )
            self.store.audit(
                conn,
                operation_id,
                "HUMAN_APPROVED" if body.decision == "approve" else "HUMAN_REJECTED",
                {
                    "state": state,
                    "username": session["username"],
                    "reason": body.reason,
                    "plan_digest": body.plan_digest,
                    "view_digest": served["view_digest"],
                    "view_id": body.view_id,
                },
            )
            return self.store.public(op)

    def cancel(self, operation_id: str, requester: str | None = None) -> dict:
        if requester is None:
            self.human_operation(operation_id)
        with self.store.transaction() as conn:
            op = self.store.get(conn, operation_id)
            if requester is not None:
                current = self.source.principal(requester)
                if requester != op["requester"] or op["resource_id"] not in current.resources:
                    raise DomainError("NOT_FOUND", "操作不存在或无权访问。", 404)
            if op["state"] == "CANCELLED":
                return self.store.public(op)
            if op["state"] not in {"RECEIVED", "PENDING_APPROVAL", "READY"}:
                raise DomainError("CANNOT_CANCEL", "操作已领取或已结束，不能承诺取消。", 409)
            op = self.store.transition(conn, op, "CANCELLED")
            conn.execute(
                jobs.update().where(jobs.c.operation_id == operation_id).values(state="done")
            )
            self.store.audit(
                conn,
                operation_id,
                "CANCELLED",
                {"state": "CANCELLED", "actor": requester or "reviewer"},
            )
            return self.store.public(op)

    def request_reconciliation(self, operation_id: str) -> dict:
        self.human_operation(operation_id)
        with self.store.transaction() as conn:
            op = self.store.get(conn, operation_id)
            if op["state"] != "UNKNOWN":
                raise DomainError("STATE_CONFLICT", "只有结果待核实的操作可以重新查询回执。", 409)
            job = (
                conn.execute(select(jobs).where(jobs.c.operation_id == operation_id))
                .mappings()
                .first()
            )
            if job and job["state"] == "leased" and job["lease_until"] > now_ms():
                raise DomainError("RECONCILIATION_RUNNING", "已有核实任务正在运行。", 409)
            conn.execute(
                jobs.update()
                .where(jobs.c.operation_id == operation_id)
                .values(
                    state="queued", kind="reconcile", attempts=0, next_at=now_ms(), lease_token=None
                )
            )
            self.store.audit(
                conn,
                operation_id,
                "RECONCILIATION_REQUESTED",
                {"state": "UNKNOWN", "executes_business_change": False},
            )
            return self.store.public(op)

    def metrics(self) -> dict[str, Any]:
        resources = self.source.read().reviewer.resources
        with self.store.read() as conn:
            counts = conn.execute(
                select(operations.c.state, func.count())
                .where(operations.c.resource_id.in_(resources))
                .group_by(operations.c.state)
            ).all()
            events = conn.execute(
                select(func.count())
                .select_from(audit_events.join(operations))
                .where(operations.c.resource_id.in_(resources))
            ).scalar_one()
        return {
            "states": dict(counts),
            "audit_events": events,
            "model_evaluation": "NOT_TESTED",
            "human_study": "NOT_CONDUCTED",
        }
