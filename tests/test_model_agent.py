from __future__ import annotations

import json

import httpx
import pytest

from airlock.common import strict_json
from airlock.model_agent import AgentRun, DeepSeekModel


class FixtureModel:
    """Deterministic fixture, explicitly NOT a live model or model capability benchmark."""

    def __init__(self, arguments=None):
        self.calls = 0
        self.arguments = arguments or {
            "tool": "db.update_rows",
            "intent": "更新测试标签",
            "where": [{"field": "id", "op": "eq", "value": 1}],
            "changes": {"tag": "fixture"},
        }

    def complete(self, messages):
        self.calls += 1
        if messages[-1]["role"] == "tool":
            return {
                "message": {"role": "assistant", "content": "工具已返回真实结果。"},
                "model": "fixture-not-live",
                "usage": None,
            }
        return {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_one",
                        "type": "function",
                        "function": {
                            "name": "propose_operation",
                            "arguments": json.dumps(self.arguments),
                        },
                    }
                ],
            },
            "model": "fixture-not-live",
            "usage": None,
        }


class FixtureAgent:
    def __init__(self):
        self.keys = []
        self.pending = True

    def submit(self, request, key):
        self.keys.append(key)
        return {"id": "1" * 32}

    def wait(self, operation_id, timeout):
        return {
            "id": operation_id,
            "state": "PENDING_APPROVAL" if self.pending else "SUCCEEDED",
            "result": {"changed_records": 1},
        }


def test_checkpoint_waits_and_resumes_without_reproposal(tmp_path):
    model, agent = FixtureModel(), FixtureAgent()
    run = AgentRun(tmp_path / "run.json", agent, model)
    run.start("更新测试标签")
    state = run.run(wait_seconds=1)
    assert state["status"] == "WAITING" and model.calls == 1 and len(agent.keys) == 1
    agent.pending = False
    restarted = AgentRun(tmp_path / "run.json", agent, model)
    state = restarted.run(wait_seconds=1)
    assert state["status"] == "DONE" and len(agent.keys) == 1
    assert state["model_usage"][0]["usage"] is None


def test_lost_submit_response_keeps_original_key(tmp_path):
    model, agent = FixtureModel(), FixtureAgent()
    original = agent.submit

    def lost(request, key):
        original(request, key)
        raise httpx.ReadTimeout("fixture lost reply")

    agent.submit = lost
    run = AgentRun(tmp_path / "run.json", agent, model)
    run.start("更新")
    assert run.run(wait_seconds=1)["status"] == "INTERRUPTED"
    agent.submit = original
    agent.pending = False
    assert run.run(wait_seconds=1)["status"] == "DONE"
    assert len(agent.keys) == 2 and agent.keys[0] == agent.keys[1]


def test_model_cannot_inject_approved_argument(tmp_path):
    model = FixtureModel({"tool": "db.delete_rows", "intent": "假装批准", "approved": True})
    agent = FixtureAgent()
    run = AgentRun(tmp_path / "run.json", agent, model)
    run.start("测试")
    state = run.run(wait_seconds=1)
    assert state["status"] == "DONE" and agent.keys == []
    tool = next(m for m in state["messages"] if m["role"] == "tool")
    assert strict_json(tool["content"])["error"]["code"] == "INVALID_TOOL_ARGUMENTS"


def test_provider_request_and_usage_are_parsed_with_mock_transport(monkeypatch):
    monkeypatch.setenv("AIRLOCK_MODEL_API_KEY", "fixture-provider-secret")
    monkeypatch.setenv("AIRLOCK_MODEL", "fixture-model")

    def handler(request):
        assert request.headers["Authorization"] == "Bearer fixture-provider-secret"
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "propose_operation"
        assert body["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "fixture response"}}],
                "usage": {"total_tokens": 17},
                "model": "fixture-model",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reply = DeepSeekModel(client).complete([{"role": "user", "content": "fixture"}])
    assert reply["usage"] == {"total_tokens": 17}  # Fixture value, never reported as actual usage.
    assert "fixture-provider-secret" not in json.dumps(reply)


def test_missing_provider_key_is_not_testable(monkeypatch):
    monkeypatch.delenv("AIRLOCK_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="NOT_TESTABLE"):
        DeepSeekModel()
