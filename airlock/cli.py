from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from airlock.auth import PASSWORD_HASHER
from airlock.common import canonical, token_hash
from airlock.config import ConfigSource
from airlock.contracts import AgentPrincipal
from airlock.storage import Store
from airlock.target import seed_target

ROOT = Path(__file__).resolve().parent.parent


def initialize(
    directory: Path, origin: str = "http://127.0.0.1:8080", reviewer_password: str | None = None
) -> dict:
    directory = directory.resolve()
    if directory.exists():
        raise SystemExit(f"Refusing to overwrite existing directory: {directory}")
    directory.mkdir(parents=True, mode=0o700)
    for name in ("gateway", "runner", "agent"):
        (directory / name).mkdir(mode=0o700)
    policy = directory / "policy.yaml"
    shutil.copyfile(ROOT / "policies/default.yaml", policy)
    secret, agent_token = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    password = reviewer_password or secrets.token_urlsafe(18)
    gateway = {
        "meta_path": str(directory / "gateway/meta.db"),
        "policy_path": str(policy),
        "public_origin": origin,
        "runner_url": "http://127.0.0.1:8081",
        "runner_secret": secret,
        "agents": [
            AgentPrincipal(id="agent-demo", token_sha256=token_hash(agent_token)).model_dump()
        ],
        "reviewer": {"username": "reviewer", "password_hash": PASSWORD_HASHER.hash(password)},
        "demo_enabled": True,
        "web_dist": str(ROOT / "apps/web/dist"),
    }
    runner = {
        "target_path": str(directory / "runner/target.db"),
        "policy_path": str(policy),
        "runner_secret": secret,
    }
    for path, value in (
        (directory / "gateway/config.json", gateway),
        (directory / "runner/config.json", runner),
    ):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)
    (directory / "agent/client.env").write_text(
        f"AIRLOCK_URL={origin}\nAIRLOCK_AGENT_TOKEN={agent_token}\n"
    )
    (directory / "reviewer.txt").write_text(f"username: reviewer\npassword: {password}\n")
    (directory / "agent/client.env").chmod(0o600)
    (directory / "reviewer.txt").chmod(0o600)
    source = ConfigSource(directory / "gateway/config.json")
    source.read()
    Store(gateway["meta_path"]).migrate()
    seed_target(Path(runner["target_path"]))
    Path(gateway["meta_path"]).chmod(0o600)
    Path(runner["target_path"]).chmod(0o600)
    return {
        "directory": str(directory),
        "gateway": str(directory / "gateway/config.json"),
        "runner": str(directory / "runner/config.json"),
        "credential_file": str(directory / "reviewer.txt"),
    }


def serve(directory: Path):
    directory = directory.resolve()
    source = ConfigSource(directory / "gateway/config.json")
    config = source.read()
    from urllib.parse import urlsplit

    origin = urlsplit(config.public_origin)
    if origin.scheme != "http" or origin.hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit(
            "Local serve supports loopback HTTP only. Use the TLS reverse-proxy deployment for production."
        )
    env = os.environ.copy()
    env.update(
        AIRLOCK_CONFIG=str(directory / "gateway/config.json"),
        AIRLOCK_RUNNER_CONFIG=str(directory / "runner/config.json"),
    )
    children = []
    try:
        for module, port in (
            ("airlock.runner_api:create_runner_app", 8081),
            ("airlock.api:create_app", origin.port or 8080),
        ):
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        module,
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    env=env,
                    cwd=ROOT,
                )
            )
        print(
            f"AIRLOCK running at {config.public_origin}; credentials: {directory / 'reviewer.txt'}",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            import time

            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=12)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description="AIRLOCK local development and demo management")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Initialize a NEW synthetic environment; never overwrites")
    init.add_argument("--directory", type=Path, default=ROOT / ".airlock")
    init.add_argument("--origin", default="http://127.0.0.1:8080")
    start = sub.add_parser("serve", help="Start loopback gateway and private runner")
    start.add_argument("--directory", type=Path, default=ROOT / ".airlock")
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--config", type=Path, default=ROOT / ".airlock/gateway/config.json")
    args = parser.parse_args()
    if args.command == "init":
        print(canonical(initialize(args.directory, args.origin)))
    elif args.command == "serve":
        serve(args.directory)
    elif args.command == "migrate":
        Store(ConfigSource(args.config).read().meta_path).migrate()


if __name__ == "__main__":
    main()
