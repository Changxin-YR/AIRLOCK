"""Record the exact installed dependency closure; no dependency resolver or network guessing."""

from __future__ import annotations

import importlib.metadata as md
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent


def closure(roots):
    found = {}
    pending = list(roots)
    while pending:
        name = canonicalize_name(pending.pop())
        if name in found:
            continue
        distribution = md.distribution(name)
        found[name] = distribution.version
        for text in distribution.requires or []:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            pending.append(requirement.name)
    return found


def main():
    runtime = closure(
        [
            "fastapi",
            "uvicorn",
            "pydantic",
            "sqlalchemy",
            "alembic",
            "httpx",
            "argon2-cffi",
            "PyYAML",
            "mcp",
        ]
    )
    all_deps = closure([*runtime, "pytest", "pytest-cov", "pytest-asyncio", "ruff", "setuptools"])
    header = "# Exact installed versions validated by this repository. Python 3.13 Linux closure.\n"
    (ROOT / "requirements.lock").write_text(
        header + "\n".join(f"{k}=={v}" for k, v in sorted(runtime.items())) + "\n"
    )
    (ROOT / "requirements-dev.lock").write_text(
        header
        + "-r requirements.lock\n"
        + "\n".join(f"{k}=={v}" for k, v in sorted(all_deps.items()) if k not in runtime)
        + "\n"
    )
    print(
        f"Locked {len(runtime)} runtime + {len(all_deps) - len(runtime)} development distributions."
    )


if __name__ == "__main__":
    main()
