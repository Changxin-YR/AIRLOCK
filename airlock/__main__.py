"""Development launcher. Never shares the database or reviewer secret with an agent."""
from __future__ import annotations
import argparse
import json
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Airlock local demonstration")
    parser.add_argument("command", choices=["init", "serve"])
    parser.add_argument("--config", default="var/local.json")
    args = parser.parse_args()
    path = Path(args.config)
    if args.command == "init":
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = {key: secrets.token_urlsafe(32) for key in
                  ("AIRLOCK_AGENT_TOKEN", "AIRLOCK_REVIEWER_TOKEN", "AIRLOCK_AUDIT_KEY")}
        # Exclusive creation prevents accidental key rotation and lost audit verification.
        with open(path, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as f:
            json.dump(config, f, indent=2)
        path.chmod(0o600)
        print(f"Created {path}. Keep it private. View it locally for the two separate role credentials.")
        return
    if path.exists():
        for key, value in json.loads(path.read_text()).items():
            if key in {"AIRLOCK_AGENT_TOKEN", "AIRLOCK_REVIEWER_TOKEN", "AIRLOCK_AUDIT_KEY"}:
                os.environ.setdefault(key, value)
    import uvicorn
    uvicorn.run("airlock.api:create_app", factory=True, host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    main()
