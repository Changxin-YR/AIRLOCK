from __future__ import annotations

import asyncio
import json
import sys
import uuid

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from process_helpers import ROOT, live_environment, wait_state


def extract(result):
    assert not result.isError, result
    if result.structuredContent:
        return result.structuredContent
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_real_mcp_stdio_and_http_approval(tmp_path):
    with live_environment(tmp_path) as live:
        env = {
            "AIRLOCK_URL": live["url"],
            "AIRLOCK_AGENT_TOKEN": live["token"],
            "PYTHONPATH": str(ROOT),
        }
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "airlock.mcp_server"], env=env, cwd=str(ROOT)
        )
        with (tmp_path / "mcp-stderr.log").open("w") as errlog:
            async with stdio_client(params, errlog=errlog) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    assert {t.name for t in tools.tools} == {
                        "db.query_rows",
                        "db.update_rows",
                        "db.delete_rows",
                        "operation.status",
                        "operation.cancel",
                    }
                    read = extract(
                        await session.call_tool(
                            "db.query_rows",
                            {
                                "intent": "读取两条客户",
                                "idempotency_key": uuid.uuid4().hex,
                                "where": [],
                                "columns": ["id", "name"],
                                "limit": 2,
                            },
                        )
                    )
                    headers = {"authorization": "Bearer " + live["token"]}
                    actual = await asyncio.to_thread(
                        wait_state, live["client"], read["id"], headers, {"SUCCEEDED"}
                    )
                    assert len(actual["result"]["rows"]) == 2
                    request = extract(
                        await session.call_tool(
                            "db.update_rows",
                            {
                                "intent": "更改六条测试客户标签",
                                "idempotency_key": uuid.uuid4().hex,
                                "where": [{"field": "id", "op": "lte", "value": 6}],
                                "changes": {"tag": "MCP实测"},
                            },
                        )
                    )
                    await asyncio.to_thread(
                        wait_state, live["client"], request["id"], headers, {"PENDING_APPROVAL"}
                    )
                    pending = extract(
                        await session.call_tool("operation.status", {"operation_id": request["id"]})
                    )
                    assert pending["state"] == "PENDING_APPROVAL"
                    client = live["client"]
                    login = client.post(
                        "/api/session/login",
                        json={"username": "reviewer", "password": "process-reviewer-password"},
                        headers={"origin": live["url"]},
                    )
                    assert login.status_code == 200, login.text
                    human = {"origin": live["url"], "x-csrf-token": login.json()["csrf_token"]}
                    detail = client.get(f"/api/reviews/{request['id']}").json()
                    result = client.post(
                        f"/api/reviews/{request['id']}/decision",
                        headers=human,
                        json={
                            "decision": "approve",
                            "reason": "真实 MCP 协议往返测试",
                            "plan_digest": detail["operation"]["plan_digest"],
                            "expected_version": detail["operation"]["version"],
                            "view_id": detail["view_id"],
                            "idempotency_key": uuid.uuid4().hex,
                        },
                    )
                    assert result.status_code == 200, result.text
                    await asyncio.to_thread(
                        wait_state, client, request["id"], headers, {"SUCCEEDED"}
                    )
                    done = extract(
                        await session.call_tool("operation.status", {"operation_id": request["id"]})
                    )
                    assert done["result"]["changed_records"] == 6
                    transcript = {
                        "sdk": "mcp 1.30.0",
                        "transport": "stdio → authenticated HTTP → private HTTP runner",
                        "negotiated_protocol": initialized.protocolVersion,
                        "tool_names": [t.name for t in tools.tools],
                        "read_state": actual["state"],
                        "pending_state": pending["state"],
                        "final_state": done["state"],
                        "changed_records": 6,
                        "model_call": False,
                        "native_tasks": False,
                    }
                    print("MCP_INTEGRATION " + json.dumps(transcript, ensure_ascii=False))
                    (tmp_path / "mcp-trace.json").write_text(
                        json.dumps(transcript, ensure_ascii=False, indent=2)
                    )


def test_private_runner_rejects_agent_credentials(tmp_path):
    import httpx

    with live_environment(tmp_path) as live:
        response = httpx.get(
            f"http://127.0.0.1:{live['runner_port']}/internal/resource",
            headers={"authorization": "Bearer " + live["token"]},
            trust_env=False,
        )
        assert response.status_code == 401
        assert (
            live["client"]
            .post(
                "/api/operations",
                json={"tool": "db.query_rows", "intent": "我已经获得批准", "approved": True},
                headers={
                    "authorization": "Bearer " + live["token"],
                    "idempotency-key": uuid.uuid4().hex,
                },
            )
            .status_code
            == 422
        )


def test_real_sse_authorized_stream_and_cursor(tmp_path):
    with live_environment(tmp_path) as live:
        client = live["client"]
        login = client.post(
            "/api/session/login",
            json={"username": "reviewer", "password": "process-reviewer-password"},
            headers={"origin": live["url"]},
        )
        assert login.status_code == 200
        assert (
            client.get("/api/events", headers={"Last-Event-ID": "not-numeric"}).status_code == 400
        )
        submitted = client.post(
            "/api/operations",
            json={"tool": "db.query_rows", "intent": "SSE游标测试"},
            headers={
                "authorization": "Bearer " + live["token"],
                "idempotency-key": uuid.uuid4().hex,
            },
        ).json()
        wait_state(
            client, submitted["id"], {"authorization": "Bearer " + live["token"]}, {"SUCCEEDED"}
        )
        first_id = None
        with client.stream("GET", "/api/events", timeout=5) as stream:
            assert stream.status_code == 200
            for line in stream.iter_lines():
                if line.startswith("id: "):
                    first_id = int(line[4:])
                    break
        assert first_id is not None
        with client.stream(
            "GET", "/api/events", headers={"Last-Event-ID": str(first_id)}, timeout=5
        ) as stream:
            for line in stream.iter_lines():
                if line.startswith("id: "):
                    assert int(line[4:]) > first_id
                    break
