from __future__ import annotations

import hmac
import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import Field

from airlock.common import DomainError, digest, strict_json, token_hash
from airlock.contracts import AgentPrincipal, Policy, StrictModel


class Reviewer(StrictModel):
    username: str
    password_hash: str
    resources: list[str] = Field(default_factory=lambda: ["demo"])
    active: bool = True


class GatewayConfig(StrictModel):
    meta_path: str
    policy_path: str
    public_origin: str = "http://127.0.0.1:8080"
    runner_url: str = "http://127.0.0.1:8081"
    internal_agent_host: str | None = None
    runner_secret: str = Field(min_length=32)
    agents: list[AgentPrincipal]
    reviewer: Reviewer
    demo_enabled: bool = False
    session_seconds: int = Field(default=28800, ge=60, le=86400)
    worker_enabled: bool = True
    lease_ms: int = Field(default=15000, ge=1000, le=60000)
    web_dist: str = "apps/web/dist"

    @property
    def secure_cookie(self) -> bool:
        return self.public_origin.startswith("https://")

    def validate_deployment(self) -> None:
        origin = urlsplit(self.public_origin)
        if (
            origin.scheme not in ("http", "https")
            or not origin.hostname
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
            or origin.username
        ):
            raise ValueError("public_origin must be a bare http(s) origin")
        if origin.scheme == "http" and origin.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("non-loopback public origins require HTTPS")
        if self.public_origin.endswith("/"):
            raise ValueError("public_origin must not have trailing slash")
        ids = [a.id for a in self.agents]
        tokens = [a.token_sha256 for a in self.agents]
        if len(set(ids)) != len(ids) or len(set(tokens)) != len(tokens):
            raise ValueError("agent IDs and tokens must be unique")


class RunnerConfig(StrictModel):
    target_path: str
    policy_path: str
    runner_secret: str = Field(min_length=32)


class ConfigSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read(self) -> GatewayConfig:
        config = GatewayConfig.model_validate(strict_json(self.path.read_bytes()))
        config.validate_deployment()
        return config

    def principal(self, principal_id: str) -> AgentPrincipal:
        for principal in self.read().agents:
            if principal.id == principal_id and principal.active:
                return principal
        raise DomainError("PRINCIPAL_REVOKED", "此服务身份已停用或不存在。", 403)

    def authenticate_agent(self, token: str) -> AgentPrincipal:
        candidate = token_hash(token)
        for principal in self.read().agents:
            if hmac.compare_digest(candidate, principal.token_sha256) and principal.active:
                return principal
        raise DomainError("UNAUTHENTICATED", "服务身份凭据无效。", 401)

    def policy(self) -> Policy:
        return read_policy(self.read().policy_path)


def read_policy(path: str | Path) -> Policy:
    # A duplicate YAML key must not silently override an earlier security setting.
    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError("duplicate policy key")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return Policy.model_validate(yaml.load(Path(path).read_text(), Loader=UniqueLoader))


def policy_hash(policy: Policy) -> str:
    return digest(policy.model_dump())


def gateway_source() -> ConfigSource:
    return ConfigSource(os.environ.get("AIRLOCK_CONFIG", ".airlock/gateway/config.json"))
