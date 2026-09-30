from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit


def required_secret(name: str) -> str:
    value = os.environ.get(name, "")
    if len(value) < 32:
        raise RuntimeError(f"{name} must be set to a random secret of at least 32 characters; run airlock init")
    return value


@dataclass
class Settings:
    meta_path: Path
    runner_url: str
    runner_secret: str
    execution_secret: str
    policy_path: Path | None = None
    origins: tuple[str, ...] = ("http://127.0.0.1:8080", "http://localhost:8080")
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "gateway")
    secure_cookie: bool = False
    demo_enabled: bool = False
    worker_enabled: bool = True
    lease_seconds: float = 30
    worker_interval: float = 0.25
    dist_path: Path = field(default_factory=lambda: Path("apps/web/dist"))

    def __post_init__(self):
        if len(self.runner_secret) < 32 or len(self.execution_secret) < 32:
            raise ValueError("Service secrets must have at least 32 characters")
        parsed = urlsplit(self.runner_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("runner_url must be a trusted configured HTTP origin without credentials")
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("runner_url must be an origin")
        for origin in self.origins:
            host = urlsplit(origin).hostname
            if not self.secure_cookie and host not in {"localhost", "127.0.0.1", "testserver"}:
                raise ValueError("Non-local UI origins require HTTPS and secure cookies")
            if self.secure_cookie and not origin.startswith("https://"):
                raise ValueError("Secure mode requires HTTPS origins")

    @classmethod
    def from_env(cls) -> 'Settings':
        return cls(meta_path=Path(os.environ.get("AIRLOCK_META_DB", "runtime/gateway/meta.db")),
                   runner_url=os.environ.get("AIRLOCK_RUNNER_URL", "http://127.0.0.1:8090"),
                   runner_secret=required_secret("AIRLOCK_RUNNER_SECRET"),
                   execution_secret=required_secret("AIRLOCK_EXECUTION_SECRET"),
                   policy_path=Path(os.environ.get("AIRLOCK_POLICY", "policies/default.yaml")),
                   origins=tuple(os.environ.get("AIRLOCK_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080").split(",")),
                   allowed_hosts=tuple(os.environ.get("AIRLOCK_HOSTS", "127.0.0.1,localhost,gateway").split(",")),
                   secure_cookie=os.environ.get("AIRLOCK_SECURE_COOKIE") == "1",
                   demo_enabled=os.environ.get("AIRLOCK_DEMO") == "1",
                   worker_enabled=os.environ.get("AIRLOCK_WORKER", "1") == "1",
                   dist_path=Path(os.environ.get("AIRLOCK_DIST", "apps/web/dist")))
