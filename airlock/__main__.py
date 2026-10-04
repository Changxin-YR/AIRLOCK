"""Development launcher. Never shares the database or reviewer secret with an agent."""
from __future__ import annotations
import argparse
from collections import ChainMap
import json
import os
import secrets
from pathlib import Path

CONFIG_KEYS = {"AIRLOCK_AGENT_TOKEN", "AIRLOCK_REVIEWER_TOKEN", "AIRLOCK_AUDIT_KEY"}
MAX_CONFIG_BYTES = 16384


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate configuration key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError("invalid JSON constant")


def load_credentials(path: Path, explicit: bool) -> dict[str, str]:
    """Read a bounded local file; never log input or change process identity."""
    if not explicit and not path.exists() and not path.is_symlink():
        return {}
    if not path.is_file():
        raise ValueError("configuration is not a regular file")
    with path.open("rb") as source:
        raw = source.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("configuration size limit")
    config = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                        parse_constant=_invalid_constant)
    if not isinstance(config, dict) or any(not isinstance(value, str)
                                           for key, value in config.items() if key in CONFIG_KEYS):
        raise ValueError("invalid configuration object")
    return {key: value for key, value in config.items() if key in CONFIG_KEYS}


def print_diagnostics(report, json_mode):
    if json_mode:
        print(json.dumps(report, ensure_ascii=True))
    else:
        print("AIRLOCK local startup preflight: " + report['status'])
        for check in report['checks']:
            print(f"{check['status']}: {check['id']} ({check['code']})")
        print("Not checked: " + ", ".join(report['not_checked']))
        print("No service was started and no persistent database was opened.")


def main():
    parser = argparse.ArgumentParser(description="Airlock local service")
    parser.add_argument("command", choices=["init", "serve", "doctor"])
    parser.add_argument("--config", help="Configuration file (default: var/local.json); an explicit path must exist")
    parser.add_argument("--json", action="store_true", help="Machine-readable doctor report")
    args = parser.parse_args()
    if args.json and args.command != "doctor":
        parser.error("--json is only supported by doctor")
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
    try:
        config = load_credentials(path, args.config is not None)
    except (OSError, ValueError, RecursionError):
        # Do not echo configuration values, JSON excerpts or filesystem errors.
        if args.command == "doctor":
            report = {'scope': 'local_startup_preflight', 'status': 'FAIL',
                      'checks': [{'id': 'configuration', 'status': 'FAIL', 'code': 'configuration_file_invalid'}],
                      'not_checked': ['sqlite_runtime', 'console', 'persistent_database',
                                      'remote_services', 'optional_integrations'], 'service_started': False}
            print_diagnostics(report, args.json)
            raise SystemExit(2) from None
        parser.error("configuration must be a readable regular UTF-8 JSON file with string credential values")
    environment = ChainMap(os.environ, config)
    if args.command == "doctor":
        from .diagnostics import collect_checks
        report = collect_checks(environment)
        print_diagnostics(report, args.json)
        if report['status'] != 'PASS':
            raise SystemExit(2)
        return
    # Validate the effective settings before Uvicorn and before changing any
    # environment values. The direct ASGI factory shares this validation.
    from .models import Settings
    try:
        Settings.from_env(environment)
    except ValueError:
        parser.error("invalid AIRLOCK environment configuration; check credentials, origin and limits")
    for key, value in config.items():
        os.environ.setdefault(key, value)
    import uvicorn
    uvicorn.run("airlock.api:create_app", factory=True, host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    main()
