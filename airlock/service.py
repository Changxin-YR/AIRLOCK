"""Protocol-independent approval state machine and local atomic executor."""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from .models import Decision, GateError, Invocation, Settings, canonical, digest
from .sql import classify, execute, fingerprint, preview, snapshot
from .store import Store

TERMINAL = {"executed", "blocked", "rejected", "expired", "stale", "failed"}


class Gate:
    def __init__(self, settings: Settings, clock=time.time):
        self.settings, self.clock, self.store = settings, clock, Store(settings)

    def _event(self, conn, action: dict, kind: str, **detail) -> None:
        self.store.audit(conn, action["id"], {"kind": kind, "at": self.clock(),
                         "state": action["state"], "detail": detail})

    def _finish(self, conn, action: dict, state: str, reason_code: str, **detail) -> dict:
        action.update(state=state, reason_code=reason_code, version=action["version"] + 1)
        self.store.save(conn, action)
        self._event(conn, action, "action." + state, **detail)
        return action

    def expire(self) -> int:
        with self.store.transaction() as conn:
            rows = conn.execute("SELECT document FROM actions WHERE state='pending' AND expires<=?",
                                (self.clock(),)).fetchall()
            for row in rows:
                self._finish(conn, json.loads(row[0]), "expired", "approval_expired")
        return len(rows)

    def submit(self, call: Invocation, principal: str = "agent:demo") -> dict:
        started = time.perf_counter()
        request_hash = digest({"principal": principal, "call": call.model_dump()})
        self.expire()
        with self.store.transaction() as conn:
            existing = conn.execute("SELECT request_hash,document FROM actions WHERE principal=? AND idem=?",
                                    (principal, call.idempotency_key)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise GateError("idempotency_conflict")
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
                "policy_version": self.settings.policy_version, "version": 1,
                "state": "blocked", "decision": "block", "reason_code": "unsupported_or_invalid_sql",
                "risk": "blocked", "impact": None, "result": None, "review_digest": None,
                "confirmation_required": "", "reviewer": None,
            }
            static_start = time.perf_counter()
            try:
                try:
                    operations = classify(conn, call)
                finally:
                    action["static_ms"] = round((time.perf_counter() - static_start) * 1000, 3)
                if not operations:
                    action.update(state="executed", decision="pass", reason_code="bounded_read",
                                  risk="low", result=execute(conn, call))
                else:
                    pending = conn.execute("SELECT count(*) FROM actions WHERE principal=? AND state='pending'",
                                           (principal,)).fetchone()[0]
                    if pending >= self.settings.max_pending:
                        action["reason_code"] = "pending_budget_exhausted"
                    else:
                        dry_start = time.perf_counter()
                        impact = preview(conn, call, operations)
                        action["preview_ms"] = round((time.perf_counter() - dry_start) * 1000, 3)
                        risk = "critical" if impact["changed_rows"] >= self.settings.critical_rows else "high"
                        action.update(state="pending", decision="need_approval", reason_code="write_requires_review",
                                      risk=risk, impact=impact)
                        if risk == "critical":
                            action["confirmation_required"] = f"EXECUTE {impact['changed_rows']}"
                        action["review_digest"] = digest({"request": request_hash, "impact": impact,
                                                         "policy": action["policy_version"]})
            except (sqlite3.Error, ValueError, OverflowError):
                # Failure to compile or preview never creates permission to execute.
                action.update(state="blocked", decision="block", reason_code="unsupported_or_invalid_sql",
                              risk="blocked", result=None)
            action["evaluation_ms"] = round((time.perf_counter() - started) * 1000, 3)
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

    def list_actions(self, limit: int = 100, before: float | None = None, before_id: str | None = None) -> list[dict]:
        self.expire()
        with self.store.connection() as conn:
            rows = conn.execute("SELECT document FROM actions WHERE (? IS NULL OR created<? OR (created=? AND id<?)) "
                                "ORDER BY created DESC,id DESC LIMIT ?", (before, before, before, before_id, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def decide(self, action_id: str, decision: Decision, reviewer: str = "reviewer:owner") -> dict:
        self.expire()
        with self.store.transaction() as conn:
            row = conn.execute("SELECT document FROM actions WHERE id=?", (action_id,)).fetchone()
            if not row:
                raise GateError("not_found", 404)
            action = json.loads(row[0])
            if action["principal"] == reviewer:
                raise GateError("self_approval_forbidden", 403)
            if action["state"] != "pending":
                raise GateError("action_not_pending")
            if decision.expected_version != action["version"] or decision.review_digest != action["review_digest"]:
                raise GateError("review_binding_mismatch")
            if self.clock() >= action["expires_at"]:
                return self._finish(conn, action, "expired", "approval_expired")
            action["reviewer"] = reviewer
            human = {"reviewer": reviewer, "decision": decision.decision, "reason": decision.reason,
                     "review_digest": decision.review_digest, "visible_ms_untrusted": decision.visible_ms}
            if decision.decision == "reject":
                return self._finish(conn, action, "rejected", "human_rejected", **human)
            if decision.confirmation != action["confirmation_required"]:
                raise GateError("impact_confirmation_required", 422)
            # BEGIN IMMEDIATE holds the writer lock through revalidation and actual execution.
            if action["policy_version"] != self.settings.policy_version:
                return self._finish(conn, action, "stale", "policy_changed", **human)
            if fingerprint(snapshot(conn)) != action["impact"]["before_hash"]:
                return self._finish(conn, action, "stale", "target_changed", **human)
            if digest({"request": action["request_hash"], "impact": action["impact"],
                       "policy": action["policy_version"]}) != action["review_digest"]:
                return self._finish(conn, action, "failed", "stored_review_mismatch", **human)
            call = Invocation.model_validate(action["request"])
            if digest({"principal": action["principal"], "call": call.model_dump()}) != action["request_hash"]:
                return self._finish(conn, action, "failed", "stored_request_mismatch", **human)
            conn.execute("SAVEPOINT effect")
            try:
                classify(conn, call)
                result = execute(conn, call)
                if fingerprint(snapshot(conn)) != action["impact"]["after_hash"]:
                    raise ValueError("execution diverged from preview")
                conn.execute("RELEASE effect")
            except (sqlite3.Error, ValueError, OverflowError):
                conn.execute("ROLLBACK TO effect")
                conn.execute("RELEASE effect")
                return self._finish(conn, action, "failed", "execution_failed", **human)
            action["result"] = result
            # Audit failure rolls back the effect too. No distributed exactly-once claim is made.
            return self._finish(conn, action, "executed", "human_approved", **human)

    def metrics(self) -> dict:
        self.expire()
        with self.store.connection() as conn:
            counts = dict(conn.execute("SELECT state,count(*) FROM actions GROUP BY state"))
            records = [json.loads(r[0]) for r in conn.execute(
                "SELECT document FROM actions ORDER BY created DESC LIMIT 1000")]
            customers = conn.execute("SELECT count(*) FROM customers").fetchone()[0]
        def p95(key):
            values = sorted(a[key] for a in records if key in a)
            return values[max(0, (95 * len(values) + 99) // 100 - 1)] if values else None
        return {"states": counts, "customers": customers, "sample_size": len(records),
                "evaluation_p95_ms": p95("evaluation_ms"), "preview_p95_ms": p95("preview_ms"),
                "static_p95_ms": p95("static_ms"), "llm_calls": 0,
                "scope": "last 1000 local actions; evaluation excludes final persistence/commit, HTTP transport and human waiting"}


def agent_view(action: dict) -> dict:
    """No reviewer credential, approval digest, audit snapshot or internal policy is returned."""
    return {k: action[k] for k in ("id", "state", "decision", "reason_code", "result", "expires_at")} | {
        "execution_occurred": action["state"] == "executed",
        "next_step": "Poll action status; never treat pending as success." if action["state"] == "pending"
        else "Use a bounded SELECT or submit a narrower NEW action; do not retry rejected writes blindly."
        if action["state"] in TERMINAL - {"executed"} else "Read the result."}
