import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from airlock.common import DomainError, now_ms
from airlock.config import read_policy
from airlock.contracts import AgentPrincipal, OperationRequest
from airlock.plans import execution_envelope, make_plan
from airlock.target import SQLiteTarget, seed_target

SECRET = "test-only-runner-secret-" + "x" * 32


@pytest.fixture
def target_env(tmp_path):
    path = tmp_path / "target.db"
    seed_target(path)
    target = SQLiteTarget(path, SECRET)
    principal = AgentPrincipal(id="agent-test", token_sha256="0" * 64)
    policy = read_policy(Path(__file__).parents[1] / "policies/default.yaml")
    return path, target, principal, policy


def request(tool="db.delete_rows", where=None, **kwargs):
    return OperationRequest(
        tool=tool,
        intent="测试变更",
        where=where or [{"field": "id", "op": "eq", "value": 1}],
        **kwargs,
    )


def plan_for(env, req):
    _, target, principal, policy = env
    preview = target.preview(req, principal, policy)
    return make_plan("1" * 32, principal, req, preview, policy, now_ms() + 300000)


def test_preview_exact_cascade_and_zero_target_change(target_env):
    path, target, principal, policy = target_env
    before = path.read_bytes()
    p = target.preview(request(), principal, policy)
    assert p["direct_changes"] == 1
    assert p["cascaded_changes"] == 2
    assert {(r["table"], r["id"]) for r in p["changes"]} == {
        ("customers", 1),
        ("customer_notes", 1),
        ("customer_notes", 2),
    }
    assert path.read_bytes() == before
    assert "fixture-1@" not in json.dumps(p)


def test_execute_receipt_is_idempotent(target_env):
    path, target, _, policy = target_env
    plan = plan_for(target_env, request())
    envelope = execution_envelope(plan, SECRET)
    first = target.execute(**envelope, policy=policy)
    second = target.execute(**envelope, policy=policy)
    assert first == second
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 1205
        assert conn.execute("SELECT count(*) FROM execution_receipts").fetchone()[0] == 1


def test_stale_target_blocks_even_same_row_count(target_env):
    path, target, _, policy = target_env
    plan = plan_for(target_env, request())
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE customers SET tag='changed' WHERE id=100")
    with pytest.raises(DomainError, match="目标数据已变化"):
        target.execute(**execution_envelope(plan, SECRET), policy=policy)
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 1206


def test_receipt_failure_rolls_back_business_change(target_env, monkeypatch):
    path, target, _, policy = target_env
    plan = plan_for(target_env, request())

    def fail(*_):
        raise RuntimeError("receipt disk fault")

    monkeypatch.setattr(target, "_insert_receipt", fail)
    with pytest.raises(RuntimeError):
        target.execute(**execution_envelope(plan, SECRET), policy=policy)
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 1206
        assert conn.execute("SELECT count(*) FROM customer_notes").fetchone()[0] == 24


def test_unknown_trigger_is_not_simulated(target_env):
    path, target, principal, policy = target_env
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER surprise AFTER DELETE ON customers BEGIN UPDATE customers SET tag='oops'; END"
        )
    with pytest.raises(DomainError) as e:
        target.preview(request(), principal, policy)
    assert e.value.code == "SCHEMA_UNSUPPORTED"


def test_client_cannot_replace_plan_or_signature(target_env):
    _, target, _, policy = target_env
    plan = plan_for(target_env, request())
    envelope = execution_envelope(plan, SECRET)
    envelope["signature"] = "0" * 64
    with pytest.raises(DomainError) as e:
        target.execute(**envelope, policy=policy)
    assert e.value.code == "INVALID_PERMIT"
    envelope = execution_envelope(plan, SECRET)
    envelope["plan"]["payload"]["request"]["where"][0]["value"] = 2
    with pytest.raises(DomainError) as e:
        target.execute(**envelope, policy=policy)
    assert e.value.code == "INVALID_PLAN"


def test_preview_limit_fails_closed(target_env):
    _, target, principal, policy = target_env
    policy = policy.model_copy(update={"max_snapshot_rows": 20})
    with pytest.raises(DomainError) as e:
        target.preview(request(), principal, policy)
    assert e.value.code == "PREVIEW_UNSUPPORTED"
