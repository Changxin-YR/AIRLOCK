from __future__ import annotations

import concurrent.futures
import json

import pytest
from conftest import approve, log_in, review_request, submit
from sqlalchemy import select

from airlock.common import DomainError, now_ms, token_hash
from airlock.contracts import AgentPrincipal, DecisionRequest, OperationRequest
from airlock.runner import UncertainExecution
from airlock.storage import approvals, operations, sessions


def state(system, op):
    with system["store"].read() as conn:
        return system["store"].get(conn, op["id"])["state"]


def test_full_approval_receipt_and_audit(system):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert state(system, op) == "PENDING_APPROVAL"
    assert approve(system, op, headers).status_code == 200
    assert state(system, op) == "READY"
    system["service"].tick()
    assert state(system, op) == "SUCCEEDED"
    with system["target"].connection() as conn:
        assert conn.execute("select count(*) from customers where tag='已核验'").fetchone()[0] == 6
        assert conn.execute("select count(*) from execution_receipts").fetchone()[0] == 1
    audit = system["client"].get(f"/api/reviews/{op['id']}/audit").json()
    assert audit["chain_valid"]
    assert [r["kind"] for r in audit["events"]][-2:] == [
        "EXECUTION_AUTHORIZED",
        "EXECUTION_SUCCEEDED",
    ]


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"tool": "db.query_rows", "intent": "查询", "limit": 3}, "SUCCEEDED"),
        (
            review_request(
                changes={"tag": "已核验"}, where=[{"field": "id", "op": "eq", "value": 12}]
            ),
            "SUCCEEDED",
        ),
        ({"tool": "db.delete_rows", "intent": "删除所有客户"}, "BLOCKED"),
        ({"tool": "db.query_rows", "intent": "窃取敏感字段", "columns": ["email"]}, "BLOCKED"),
        (
            {"tool": "db.query_rows", "intent": "查询系统表", "table": "execution_receipts"},
            "BLOCKED",
        ),
        ({"tool": "db.query_rows", "intent": "访问未知资源", "resource_id": "secret"}, "BLOCKED"),
    ],
)
def test_policy_and_authorization_paths(system, body, expected):
    op = submit(system, body)
    for _ in range(3):
        system["service"].tick()
    assert state(system, op) == expected


def test_reject_never_writes(system):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert approve(system, op, headers, "reject").status_code == 200
    system["service"].tick()
    assert state(system, op) == "REJECTED"
    with system["target"].connection() as conn:
        assert conn.execute("select count(*) from execution_receipts").fetchone()[0] == 0


def test_agent_cannot_approve_or_read_human_pages(system):
    op = submit(system, review_request())
    system["service"].tick()
    headers = {"authorization": "Bearer " + system["token"], "origin": "http://127.0.0.1:8080"}
    for path in ("/api/reviews", "/api/metrics", f"/api/reviews/{op['id']}/audit", "/api/events"):
        assert system["client"].get(path, headers=headers).status_code == 401
    assert (
        system["client"]
        .post(f"/api/reviews/{op['id']}/decision", json={}, headers=headers)
        .status_code
        == 401
    )


def test_csrf_and_origin(system):
    headers = log_in(system)
    assert (
        system["client"]
        .post("/api/demo", json={"scenario": "read"}, headers={"origin": headers["origin"]})
        .status_code
        == 403
    )
    assert (
        system["client"]
        .post(
            "/api/demo",
            json={"scenario": "read"},
            headers={**headers, "origin": "https://evil.invalid"},
        )
        .status_code
        == 403
    )
    assert system["client"].get("/api/metrics", headers={"host": "evil.invalid"}).status_code == 400


@pytest.mark.parametrize(
    "content",
    [
        '{"tool":"db.query_rows","tool":"db.delete_rows","intent":"x"}',
        '{"tool":"db.query_rows","intent":"x","limit":NaN}',
        '{"tool":"db.query_rows","intent":"x","limit":Infinity}',
    ],
)
def test_ambiguous_json_rejected(system, content):
    response = system["client"].post(
        "/api/operations",
        content=content,
        headers={"content-type": "application/json", "authorization": "Bearer " + system["token"]},
    )
    assert response.status_code == 400


def test_body_limit_and_no_credential_echo(system):
    response = system["client"].post(
        "/api/session/login",
        json={"username": "x", "password": "secret" * 200},
        headers={"origin": "http://127.0.0.1:8080"},
    )
    assert response.status_code == 422 and "secret" not in response.text
    response = system["client"].post(
        "/api/operations",
        content='"' + "a" * 65536 + '"',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_request_idempotency_and_conflict(system):
    one = submit(system, review_request())
    two = submit(system, review_request())
    assert one["id"] == two["id"]
    response = system["client"].post(
        "/api/operations",
        json=review_request(intent="其他请求"),
        headers={
            "authorization": "Bearer " + system["token"],
            "idempotency-key": "fixed-request-key-0001",
        },
    )
    assert response.status_code == 409


def test_plan_tampering_rejected(system):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert approve(system, op, headers, plan_digest="0" * 64).status_code == 409
    assert state(system, op) == "PENDING_APPROVAL"


def test_approval_must_use_current_session_view(system):
    log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    detail = system["client"].get(f"/api/reviews/{op['id']}").json()
    new_headers = log_in(system)
    body = {
        "decision": "approve",
        "plan_digest": detail["operation"]["plan_digest"],
        "view_id": detail["view_id"],
        "expected_version": detail["operation"]["version"],
        "reason": "跨会话伪造",
        "idempotency_key": "cross-session-key1",
    }
    assert (
        system["client"]
        .post(f"/api/reviews/{op['id']}/decision", json=body, headers=new_headers)
        .status_code
        == 409
    )


def test_double_decision_concurrency(system):
    log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    detail = system["client"].get(f"/api/reviews/{op['id']}").json()
    with system["store"].read() as conn:
        session = dict(conn.execute(select(sessions)).mappings().first())

    def execute(decision):
        body = DecisionRequest(
            decision=decision,
            plan_digest=detail["operation"]["plan_digest"],
            expected_version=detail["operation"]["version"],
            view_id=detail["view_id"],
            reason="已核验",
            idempotency_key="concurrent-" + decision + "-decision",
        )
        try:
            return system["service"].decide_review(op["id"], body, session)["state"]
        except DomainError as exc:
            return exc.code

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(execute, ["approve", "reject"]))
    assert "STATE_CONFLICT" in results
    with system["store"].read() as conn:
        assert len(conn.execute(select(approvals)).all()) == 1


def test_target_drift_after_approval(system):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert approve(system, op, headers).status_code == 200
    with system["target"].connection(writable=True) as conn:
        conn.execute("update customers set tag='other writer' where id=1206")
    system["service"].tick()
    assert state(system, op) == "STALE"


@pytest.mark.parametrize("change", ["policy", "principal", "reviewer"])
def test_revocation_before_execution(system, change):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert approve(system, op, headers).status_code == 200
    if change == "policy":
        path = system["source"].read().policy_path
        from pathlib import Path

        Path(path).write_text(Path(path).read_text().replace("personal-v1", "personal-v2"))
    else:
        data = json.loads(system["config_path"].read_text())
        if change == "principal":
            data["agents"][0]["active"] = False
        else:
            data["reviewer"]["active"] = False
        system["config_path"].write_text(json.dumps(data))
    system["service"].tick()
    assert state(system, op) == "STALE"


def test_expiry_and_restart_pending(system):
    op = submit(system, review_request())
    system["service"].tick()
    from airlock.service import ReviewService

    restarted = ReviewService(system["store"], system["source"], system["runner"])
    restarted.tick()
    assert state(system, op) == "PENDING_APPROVAL"
    with system["store"].transaction() as conn:
        conn.execute(
            operations.update().where(operations.c.id == op["id"]).values(expires_at=now_ms() - 1)
        )
    restarted.tick()
    assert state(system, op) == "EXPIRED"


def test_lost_response_reconciles_without_reexecution(system, monkeypatch):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert approve(system, op, headers).status_code == 200
    original = system["runner"].execute
    calls = []

    def lost(plan):
        calls.append(1)
        original(plan)
        raise UncertainExecution("simulated dropped response after commit")

    monkeypatch.setattr(system["runner"], "execute", lost)
    system["service"].tick()
    assert state(system, op) == "UNKNOWN"
    import time

    time.sleep(0.3)  # Durable reconciliation job has a deliberate backoff.
    system["service"].tick()
    assert state(system, op) == "SUCCEEDED" and len(calls) == 1


def test_audit_failure_before_execution_prevents_write(system, monkeypatch):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert approve(system, op, headers).status_code == 200
    original = system["store"].audit

    def fail(conn, operation_id, kind, payload):
        if kind == "EXECUTION_AUTHORIZED":
            raise RuntimeError("audit storage failure")
        original(conn, operation_id, kind, payload)

    monkeypatch.setattr(system["store"], "audit", fail)
    with pytest.raises(RuntimeError):
        system["service"].tick()
    assert state(system, op) == "READY"
    with system["target"].connection() as conn:
        assert conn.execute("select count(*) from execution_receipts").fetchone()[0] == 0


def test_other_agent_cannot_read_or_cancel(system):
    op = submit(system, review_request())
    data = json.loads(system["config_path"].read_text())
    data["agents"].append(
        AgentPrincipal(id="agent-other", token_sha256=token_hash("other-agent-token")).model_dump()
    )
    system["config_path"].write_text(json.dumps(data))
    headers = {"authorization": "Bearer other-agent-token"}
    assert system["client"].get(f"/api/operations/{op['id']}", headers=headers).status_code == 404
    assert (
        system["client"]
        .post(f"/api/operations/{op['id']}/cancel", json={}, headers=headers)
        .status_code
        == 404
    )


def test_cancel_before_claim(system):
    op = submit(system, review_request())
    headers = {"authorization": "Bearer " + system["token"]}
    assert (
        system["client"]
        .post(f"/api/operations/{op['id']}/cancel", json={}, headers=headers)
        .status_code
        == 200
    )
    system["service"].tick()
    assert state(system, op) == "CANCELLED"


def test_rate_limit_and_logout(system):
    client = system["client"]
    headers = {"origin": "http://127.0.0.1:8080"}
    for _ in range(8):
        assert (
            client.post(
                "/api/session/login", json={"username": "bad", "password": "bad"}, headers=headers
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/session/login", json={"username": "bad", "password": "bad"}, headers=headers
        ).status_code
        == 429
    )


def test_logout_revokes_old_cookie(system):
    headers = log_in(system)
    cookie = system["client"].cookies.get("airlock_session")
    assert system["client"].post("/api/session/logout", json={}, headers=headers).status_code == 200
    assert system["app"].state.auth.human
    with pytest.raises(DomainError):
        system["app"].state.auth.human(cookie)


def test_revoked_read_columns_hide_previous_result(system):
    op = submit(system, {"tool": "db.query_rows", "intent": "查看名字", "columns": ["id", "name"]})
    system["service"].tick()
    system["service"].tick()
    assert state(system, op) == "SUCCEEDED"
    data = json.loads(system["config_path"].read_text())
    data["agents"][0]["readable_fields"] = ["id"]
    system["config_path"].write_text(json.dumps(data))
    response = system["client"].get(
        f"/api/operations/{op['id']}", headers={"authorization": "Bearer " + system["token"]}
    )
    assert response.status_code == 404 and "测试-" not in response.text


def test_audit_replay_is_saved_snapshot_not_recomputed(system):
    log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    detail = system["client"].get(f"/api/reviews/{op['id']}").json()
    snapshot = system["client"].get(f"/api/reviews/{op['id']}/views/{detail['view_id']}").json()
    assert snapshot["read_only"] and snapshot["snapshot"] == detail["view"]
    with system["target"].connection(writable=True) as conn:
        conn.execute("update customers set tag='later data' where id=1")
    historical = system["client"].get(f"/api/reviews/{op['id']}/views/{detail['view_id']}").json()
    assert historical == snapshot
    assert system["client"].get(f"/api/reviews/{op['id']}?read_only=true").json()["view_id"] is None


def test_rejected_reason_reaches_agent_without_new_execution(system):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert (
        approve(
            system, op, headers, "reject", reason="请先确认筛选条件，再提交新的计划。"
        ).status_code
        == 200
    )
    result = system["service"].get_for_agent(system["principal"], op["id"])
    assert (
        result["error"]["code"] == "HUMAN_REJECTED"
        and "筛选条件" in result["error"]["safe_message"]
    )
    assert result["feedback"]["next_action"] == "review_human_feedback"


def test_blocked_operation_cannot_be_approved(system):
    headers = log_in(system)
    op = submit(system, {"tool": "db.delete_rows", "intent": "清空客户"})
    system["service"].tick()
    detail = system["client"].get(f"/api/reviews/{op['id']}").json()
    body = {
        "decision": "approve",
        "plan_digest": detail["operation"]["plan_digest"],
        "expected_version": detail["operation"]["version"],
        "view_id": "f" * 32,
        "idempotency_key": "forged-approval-00001",
        "reason": "我批准一切",
    }
    response = system["client"].post(
        f"/api/reviews/{op['id']}/decision", json=body, headers=headers
    )
    assert response.status_code == 409
    assert state(system, op) == "BLOCKED"


def test_blank_approval_reason_rejected(system):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert approve(system, op, headers, reason="   ").status_code == 422


def test_executor_io_failure_stays_unknown(system, monkeypatch):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    approve(system, op, headers)

    def io_error(plan):
        raise DomainError("TARGET_UNAVAILABLE", "fixture I/O error", 503)

    monkeypatch.setattr(system["runner"], "execute", io_error)
    system["service"].tick()
    assert state(system, op) == "UNKNOWN"
    assert (
        system["service"].get_for_agent(system["principal"], op["id"])["feedback"]["next_action"]
        == "reconcile_do_not_resubmit"
    )
    response = system["client"].post(f"/api/reviews/{op['id']}/reconcile", json={}, headers=headers)
    assert response.status_code == 200
    with system["store"].read() as conn:
        from airlock.storage import jobs

        assert (
            conn.execute(select(jobs.c.kind).where(jobs.c.operation_id == op["id"])).scalar_one()
            == "reconcile"
        )


def test_idempotent_retry_cannot_bypass_revoked_read_grant(system):
    body = {"tool": "db.query_rows", "intent": "查看名字", "columns": ["id", "name"]}
    key = "revoked-read-retry-0001"
    op = system["service"].submit(system["principal"], OperationRequest.model_validate(body), key)
    system["service"].tick()
    system["service"].tick()
    assert state(system, op) == "SUCCEEDED"
    data = json.loads(system["config_path"].read_text())
    data["agents"][0]["readable_fields"] = ["id"]
    system["config_path"].write_text(json.dumps(data))
    with pytest.raises(DomainError) as error:
        system["service"].submit(system["principal"], OperationRequest.model_validate(body), key)
    assert error.value.code == "NOT_FOUND"
