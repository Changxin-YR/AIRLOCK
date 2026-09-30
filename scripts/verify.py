"""Run reproducible local/CI gates; raw outputs and exit codes are the evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "Evidence/local")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    commands = [
        (
            "ruff",
            [sys.executable, "-m", "ruff", "check", "airlock", "tests", "scripts", "benchmark"],
            ROOT,
        ),
        (
            "format",
            [
                sys.executable,
                "-m",
                "ruff",
                "format",
                "--check",
                "airlock",
                "tests",
                "scripts",
                "benchmark",
            ],
            ROOT,
        ),
        (
            "pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-s",
                f"--junitxml={out / 'pytest.xml'}",
                "--cov=airlock",
                f"--cov-report=json:{out / 'coverage.json'}",
                "--cov-report=term-missing",
            ],
            ROOT,
        ),
        (
            "benchmark",
            [sys.executable, "benchmark/evaluate.py", "--output", str(out / "benchmark.json")],
            ROOT,
        ),
        ("frontend", ["npm", "run", "build"], ROOT / "apps/web"),
    ]
    if args.browser:
        commands.append(("browser", ["npm", "run", "test:e2e"], ROOT / "apps/web"))
    results = []
    for name, command, cwd in commands:
        started = time.monotonic()
        with (out / f"{name}.log").open("w") as stream:
            result = subprocess.run(
                command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, check=False
            )
        item = {
            "gate": name,
            "command": command,
            "exit_code": result.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "status": "PASS" if result.returncode == 0 else "FAIL",
        }
        results.append(item)
        print(json.dumps(item), flush=True)
        if result.returncode:
            print((out / f"{name}.log").read_text()[-10000:], flush=True)
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    hashes = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in sorted(set(tracked))
        if (ROOT / path).is_file() and not path.startswith(("Evidence/", ".delivery/", ".github/"))
    }
    report = {
        "schema_version": 1,
        "platform": platform.platform(),
        "python": sys.version,
        "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "packages": {
            p: importlib.metadata.version(p)
            for p in ["fastapi", "pydantic", "sqlalchemy", "mcp", "pytest", "ruff"]
        },
        "git_sha": os.environ.get("GITHUB_SHA"),
        "gates": results,
        "live_model": {
            "status": "NOT_TESTABLE",
            "reason": "No real provider credentials supplied for this verification run. Fixture tests are not live calls.",
        },
        "human_study": {"status": "NOT_CONDUCTED", "participants": 0},
        "source_hashes": hashes,
        "source_digest": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
    }
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if any(x["status"] == "FAIL" for x in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
