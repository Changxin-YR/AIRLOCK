from airlock.mcp import Bridge


def request(method, params=None):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def initialize(bridge):
    response = bridge.handle(request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                    "clientInfo": {"name": "test", "version": "1"}}))
    assert response["result"]["protocolVersion"] == "2025-11-25"
    bridge.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})


def test_mcp_lifecycle_and_pending_receipt(client, settings):
    bridge = Bridge(client, settings.agent_token)
    assert bridge.handle(request("tools/list"))["error"]["code"] == -32002
    initialize(bridge)
    assert len(bridge.handle(request("tools/list"))["result"]["tools"]) == 2
    result = bridge.handle(request("tools/call", {"name": "sql_execute", "arguments": {
        "sql": "DELETE FROM customers", "idempotency_key": "mcp-action-001"}}))["result"]
    assert not result["isError"] and result["structuredContent"]["state"] == "pending"
    assert result["structuredContent"]["execution_occurred"] is False
    identifier = result["structuredContent"]["id"]
    status = bridge.handle(request("tools/call", {"name": "action_status", "arguments": {"action_id": identifier}}))
    assert status["result"]["structuredContent"]["state"] == "pending"


def test_mcp_has_no_approval_tool(client, settings):
    bridge = Bridge(client, settings.agent_token)
    initialize(bridge)
    assert bridge.handle(request("tools/call", {"name": "approve", "arguments": {}}))["error"]["code"] == -32602
    bad = bridge.handle(request("tools/call", {"name": "sql_execute", "arguments": {
        "sql": "DELETE FROM customers", "idempotency_key": "attack-001", "approved": True}}))
    assert "error" in bad


def test_mcp_malformed_frames(client, settings):
    bridge = Bridge(client, settings.agent_token)
    assert bridge.handle([])["error"]["code"] == -32600
    assert bridge.handle(request("initialize", {"protocolVersion": []}))["error"]["code"] == -32602
