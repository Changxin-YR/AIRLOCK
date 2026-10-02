"""Untrusted inputs are deliberately smaller than persisted server state."""
from __future__ import annotations
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


Scalar = StrictStr | StrictInt | StrictFloat | None


class Invocation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    tool: str = Field(default="sql", min_length=1, max_length=64)
    sql: str = Field(default='', max_length=4000)
    arguments: dict[str, Scalar | StrictBool] = Field(default_factory=dict,max_length=16)
    parameters: list[Scalar] = Field(default_factory=list, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")

    @model_validator(mode='after')
    def valid_request(self):
        canonical(self.model_dump()).encode('utf-8')
        if not self.tool.startswith('upstream:') and not self.sql.strip():
            raise ValueError('SQL or source action ID required')
        if any(len(k)>100 or (isinstance(v,str) and len(v)>1000) for k,v in self.arguments.items()):
            raise ValueError('upstream argument too long')
        return self

    @field_validator("parameters")
    @classmethod
    def bounded_parameters(cls, values: list[Scalar]) -> list[Scalar]:
        for value in values:
            if isinstance(value, str) and len(value) > 1000:
                raise ValueError("parameter too long")
            if type(value) is int and not -(2**63) <= value < 2**63:
                raise ValueError("integer outside SQLite range")
        return values


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    decision: Literal["approve", "reject"]
    review_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str = Field(default="", max_length=80)
    visible_ms: float | int | None = Field(default=None, ge=0, le=3_600_000)


    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("a meaningful review reason is required")
        return value


class BatchDecision(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    group_id: str=Field(pattern=r'^[a-f0-9]{64}$')
    group_digest: str=Field(pattern=r'^[a-f0-9]{64}$')
    member_ids: list[str]=Field(min_length=1,max_length=100)
    decision: Literal['approve','reject']
    reason: str=Field(min_length=3,max_length=500)
    confirmation: str=Field(max_length=100)


class GovernanceChange(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    candidate_digest: str=Field(pattern=r'^[a-f0-9]{64}$')
    expected_version: int=Field(ge=0)
    expires_at: float
    reason: str=Field(min_length=3,max_length=500)


@dataclass(frozen=True)
class Settings:
    database: Path
    agent_token: str
    reviewer_token: str
    audit_key: str
    origin: str = "http://127.0.0.1:8000"
    ttl_seconds: int = 300
    max_pending: int = 20
    critical_rows: int = 100
    seed_rows: int = 1206
    calls_per_minute: int = 120
    max_actions: int = 10000
    internal_host: str | None = None
    policy_file: Path | None = None
    reviewer_file: Path | None = None
    upstream_file: Path | None = None
    semantic_file: Path | None = None
    budget_units: int = 10000
    budget_window_seconds: int = 86400

    def __post_init__(self) -> None:
        if self.internal_host and not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", self.internal_host):
            raise ValueError("invalid internal service host")
        origin = urlparse(self.origin)
        _ = origin.port  # Validate malformed ports before starting the service.
        if origin.scheme not in {"http", "https"} or not origin.hostname or origin.username or origin.path or origin.query or origin.fragment:
            raise ValueError("origin must be scheme://host[:port] without a path")
        if not 1 <= self.calls_per_minute <= 1000 or not 1 <= self.max_actions <= 10000:
            raise ValueError("invalid admission limits")
        keys = (self.agent_token, self.reviewer_token, self.audit_key)
        if any(len(k) < 32 or not k.isascii() for k in keys) or len(set(keys)) != 3:
            raise ValueError("three distinct ASCII secrets of at least 32 characters are required")
        if not 1 <= self.ttl_seconds <= 86400 or not 1 <= self.max_pending <= 100:
            raise ValueError("invalid TTL or pending limit")
        if not 1 <= self.critical_rows <= 10000 or not 1 <= self.seed_rows <= 5000:
            raise ValueError("invalid demonstration bounds")
        if not 1 <= self.budget_units <= 1000000 or not 60 <= self.budget_window_seconds <= 86400:
            raise ValueError('invalid risk budget')

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database=Path(os.getenv("AIRLOCK_DB", "var/airlock.db")),
            agent_token=os.environ["AIRLOCK_AGENT_TOKEN"],
            reviewer_token=os.environ["AIRLOCK_REVIEWER_TOKEN"],
            audit_key=os.environ["AIRLOCK_AUDIT_KEY"],
            origin=os.getenv("AIRLOCK_ORIGIN", "http://127.0.0.1:8000"),
            ttl_seconds=int(os.getenv("AIRLOCK_TTL", "300")),
            internal_host=os.getenv("AIRLOCK_INTERNAL_HOST"),
            policy_file=Path(os.environ['AIRLOCK_POLICY_FILE']) if os.getenv('AIRLOCK_POLICY_FILE') else None,
            reviewer_file=Path(os.environ['AIRLOCK_REVIEWER_FILE']) if os.getenv('AIRLOCK_REVIEWER_FILE') else None,
            upstream_file=Path(os.environ['AIRLOCK_UPSTREAM_FILE']) if os.getenv('AIRLOCK_UPSTREAM_FILE') else None,
            semantic_file=Path(os.environ['AIRLOCK_SEMANTIC_FILE']) if os.getenv('AIRLOCK_SEMANTIC_FILE') else None,
            budget_units=int(os.getenv('AIRLOCK_BUDGET_UNITS','10000')),
            budget_window_seconds=int(os.getenv('AIRLOCK_BUDGET_WINDOW','86400')),
        )

    @property
    def policy_version(self) -> str:
        return digest({"version": "bounded-sql-v1", "critical_rows": self.critical_rows,
                       "max_pending": self.max_pending, "ttl": self.ttl_seconds,
                       "budget_units":self.budget_units,"budget_window":self.budget_window_seconds})


class GateError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)
