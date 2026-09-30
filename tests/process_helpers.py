from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from airlock.cli import initialize

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def live_environment(tmp_path):
    gateway_port, runner_port = free_port(), free_port()
    while gateway_port == runner_port:
        runner_port = free_port()
    url = f"http://127.0.0.1:{gateway_port}"
    directory = tmp_path / "live"
    files = initialize(directory, url, reviewer_password="process-reviewer-password")
    config = json.loads(Path(files["gateway"]).read_text())
    config["runner_url"] = f"http://127.0.0.1:{runner_port}"
    Path(files["gateway"]).write_text(json.dumps(config))
    env = os.environ.copy()
    env.update(
        AIRLOCK_CONFIG=files["gateway"], AIRLOCK_RUNNER_CONFIG=files["runner"], PYTHONPATH=str(ROOT)
    )
    log = (tmp_path / "processes.log").open("w")
    children = []
    try:
        for factory, port in (
            ("airlock.runner_api:create_runner_app", runner_port),
            ("airlock.api:create_app", gateway_port),
        ):
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        factory,
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    env=env,
                    cwd=ROOT,
                    stdout=log,
                    stderr=log,
                )
            )
        with httpx.Client(base_url=url, trust_env=False, timeout=5) as client:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("live server did not start")
            token = (
                (directory / "agent/client.env")
                .read_text()
                .split("AIRLOCK_AGENT_TOKEN=", 1)[1]
                .strip()
            )
            yield {
                "directory": directory,
                "url": url,
                "client": client,
                "token": token,
                "env": env,
                "runner_port": runner_port,
                "config": config,
                "processes": children,
            }
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        log.close()


def wait_state(client, operation_id, headers, states, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get(f"/api/operations/{operation_id}", headers=headers).json()
        if result.get("state") in states:
            return result
        time.sleep(0.1)
    raise AssertionError(f"state did not reach {states}: {result}")
