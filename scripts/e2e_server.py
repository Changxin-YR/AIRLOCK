"""Fresh throwaway real two-process deployment for browser tests. Never resets a user database."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from airlock.cli import initialize


def main():
    port = int(os.environ.get("AIRLOCK_E2E_PORT", "8782"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        runner_port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="airlock-e2e-") as temp:
        result = initialize(
            Path(temp) / "environment",
            f"http://127.0.0.1:{port}",
            reviewer_password="test-e2e-password",
        )
        path = Path(result["gateway"])
        config = json.loads(path.read_text())
        config["runner_url"] = f"http://127.0.0.1:{runner_port}"
        path.write_text(json.dumps(config))
        env = {
            **os.environ,
            "AIRLOCK_CONFIG": str(path),
            "AIRLOCK_RUNNER_CONFIG": result["runner"],
            "PYTHONPATH": str(ROOT),
        }
        children = []

        def shutdown(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, shutdown)
        try:
            for factory, p in (
                ("airlock.runner_api:create_runner_app", runner_port),
                ("airlock.api:create_app", port),
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
                            str(p),
                            "--no-access-log",
                        ],
                        env=env,
                        cwd=ROOT,
                    )
                )
            while all(c.poll() is None for c in children):
                time.sleep(0.3)
        except KeyboardInterrupt:
            pass
        finally:
            for c in children:
                if c.poll() is None:
                    c.terminate()
            for c in children:
                try:
                    c.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    c.kill()
                    c.wait()


if __name__ == "__main__":
    main()
