from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from airlock.api import create_app
from airlock.cli import initialize
from airlock.config import ConfigSource
from airlock.runner import LocalRunner
from airlock.target import SQLiteTarget


@pytest.fixture
def system(tmp_path):
    directory = tmp_path / "environment"
    result = initialize(directory, reviewer_password="test-reviewer-password")
    config_path = Path(result["gateway"])
    data = json.loads(config_path.read_text())
    data["worker_enabled"] = False
    config_path.write_text(json.dumps(data))
    source = ConfigSource(config_path)
    target = SQLiteTarget(directory / "runner/target.db", data["runner_secret"])
    runner = LocalRunner(target, data["policy_path"])
    app = create_app(str(config_path), runner)
    token = (directory / "agent/client.env").read_text().split("AIRLOCK_AGENT_TOKEN=", 1)[1].strip()
    with TestClient(app, base_url="http://127.0.0.1:8080") as client:
        yield {
            "client": client,
            "app": app,
            "service": app.state.service,
            "store": app.state.store,
            "source": source,
            "config_path": config_path,
            "target": target,
            "runner": runner,
            "directory": directory,
            "token": token,
            "principal": source.principal("agent-demo"),
        }


def log_in(system):
    client = system["client"]
    response = client.post(
        "/api/session/login",
        json={"username": "reviewer", "password": "test-reviewer-password"},
        headers={"origin": "http://127.0.0.1:8080"},
    )
    assert response.status_code == 200, response.text
    return {"origin": "http://127.0.0.1:8080", "x-csrf-token": response.json()["csrf_token"]}


def submit(system, body, key="fixed-request-key-0001"):
    response = system["client"].post(
        "/api/operations",
        json=body,
        headers={"authorization": "Bearer " + system["token"], "idempotency-key": key},
    )
    assert response.status_code == 202, response.text
    return response.json()


def review_request(**overrides):
    return {
        "tool": "db.update_rows",
        "intent": "归档测试客户",
        "where": [{"field": "id", "op": "lte", "value": 6}],
        "changes": {"status": "archived", "tag": "已核验"},
        **overrides,
    }


def approve(system, op, headers, decision="approve", **overrides):
    response = system["client"].get(f"/api/reviews/{op['id']}")
    assert response.status_code == 200, response.text
    detail = response.json()
    body = {
        "decision": decision,
        "plan_digest": detail["operation"]["plan_digest"],
        "expected_version": detail["operation"]["version"],
        "view_id": detail["view_id"],
        "reason": "已经检查具体变更",
        "idempotency_key": "decision-key-" + op["id"],
        **overrides,
    }
    return system["client"].post(f"/api/reviews/{op['id']}/decision", json=body, headers=headers)
