from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from airlock.cli import initialize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / ".airlock-compose")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if (ROOT / ".env").exists():
        raise SystemExit(
            "Refusing to overwrite .env; choose a clean checkout or preserve it explicitly."
        )
    directory = args.directory.resolve()
    result = initialize(directory, f"http://127.0.0.1:{args.port}")
    path = Path(result["gateway"])
    config = json.loads(path.read_text())
    config.update(
        meta_path="/state/meta.db",
        policy_path="/config/policy.yaml",
        runner_url="http://runner:8081",
        internal_agent_host="gateway:8080",
        web_dist="/app/apps/web/dist",
    )
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    path = Path(result["runner"])
    config = json.loads(path.read_text())
    config.update(target_path="/state/target.db", policy_path="/config/policy.yaml")
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    path = directory / "agent/client.env"
    text = path.read_text()
    lines = text.splitlines()
    lines[0] = "AIRLOCK_URL=http://gateway:8080"
    path.write_text("\n".join(lines) + "\n")
    env = ROOT / ".env"
    env.write_text(
        f"AIRLOCK_DATA_DIR={directory.as_posix()}\nAIRLOCK_WEB_PORT={args.port}\nAIRLOCK_UID={os.getuid() if hasattr(os, 'getuid') else 1000}\nAIRLOCK_GID={os.getgid() if hasattr(os, 'getgid') else 1000}\n"
    )
    env.chmod(0o600)
    print(f"Fresh Compose environment ready. Reviewer credentials: {directory / 'reviewer.txt'}")


if __name__ == "__main__":
    main()
