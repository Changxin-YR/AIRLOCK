"""Execute INSIDE the Agent container, not the host. Emits no credentials."""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx

from airlock.agent_client import AgentClient
from airlock.contracts import OperationRequest


def main():
    assert not Path("/state/target.db").exists()
    assert not Path("/state/config.json").exists()
    assert not Path("/var/run/docker.sock").exists()
    assert not os.environ.get("AIRLOCK_RUNNER_CONFIG")
    client = AgentClient()
    runner_ip = os.environ.get("AIRLOCK_TEST_RUNNER_IP")
    assert runner_ip, "CI must supply the private runner IP to test actual network separation"
    try:
        connection = socket.create_connection((runner_ip, 8081), timeout=2)
    except (OSError, TimeoutError):
        private_socket_blocked = True
    else:
        connection.close()
        private_socket_blocked = False
    assert private_socket_blocked, "Agent can reach private runner network"
    with httpx.Client(base_url=client.base_url, trust_env=False, timeout=5) as http:
        # Even a caller choosing the public Host cannot turn an Agent bearer into a human session.
        response = http.get(
            "/api/reviews",
            headers={
                "Authorization": "Bearer " + client.token,
                "Host": os.environ.get("AIRLOCK_PUBLIC_HOST", "127.0.0.1:8080"),
            },
        )
        assert response.status_code == 401, response.status_code
        response = http.get("/api/operations", headers={"Authorization": "Bearer wrong"})
        assert response.status_code in (401, 405)
    request = OperationRequest(
        tool="db.query_rows", intent="容器隔离下的真实授权查询", columns=["id", "name"], limit=2
    )
    operation = client.submit(request, uuid.uuid4().hex)
    result = client.wait(operation["id"], timeout=20)
    assert result["state"] == "SUCCEEDED", result
    assert len(result["result"]["rows"]) == 2
    print(
        json.dumps(
            {
                "network_private_runner_blocked": True,
                "target_volume_absent": True,
                "host_docker_socket_absent": True,
                "agent_cannot_access_human_api": True,
                "authorized_agent_query": "SUCCEEDED",
                "returned_rows": 2,
                "model_call": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
