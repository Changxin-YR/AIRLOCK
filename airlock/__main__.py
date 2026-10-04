"""Development launcher. Never shares the database or reviewer secret with an agent."""
from __future__ import annotations
import argparse
import json
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Airlock local service")
    parser.add_argument("command", choices=["init", "serve"])
    parser.add_argument("--config", help="Configuration file (default: var/local.json); serve requires an explicit path to exist")
    args = parser.parse_args()
    path = Path(args.config) if args.config is not None else Path("var/local.json")
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
    # An explicitly selected configuration must never silently fall back to
    # another identity/database configuration inherited from the environment.
    # Omitting --config retains the environment-only development entry point.
    try:
        if args.config is not None or path.exists() or path.is_symlink():
            if not path.is_file():
                raise ValueError("configuration is not a regular file")
            config = json.loads(path.read_text(encoding="utf-8-sig"))
            keys = {"AIRLOCK_AGENT_TOKEN", "AIRLOCK_REVIEWER_TOKEN", "AIRLOCK_AUDIT_KEY"}
            if not isinstance(config, dict) or any(not isinstance(value, str)
                                                   for key, value in config.items() if key in keys):
                raise ValueError("invalid configuration object")
            for key, value in config.items():
                if key in keys:
                    os.environ.setdefault(key, value)
    except (OSError, ValueError):
        # Do not echo configuration values, JSON excerpts or filesystem errors.
        parser.error("configuration must be a readable regular UTF-8 JSON file with string credential values")
    import uvicorn
    uvicorn.run("airlock.api:create_app", factory=True, host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    main()
