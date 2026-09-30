from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from airlock.common import DomainError, canonical

PUBLIC_FIELDS = ("id", "name", "is_test", "status", "tag", "expires_at")
WRITE_FIELDS = ("status", "tag")
TOOLS = ("db.query_rows", "db.update_rows", "db.delete_rows")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Filter(StrictModel):
    field: str = Field(min_length=1, max_length=64)
    op: Literal["eq", "lt", "lte", "gt", "gte", "in"]
    value: Any

    @model_validator(mode="after")
    def validate_value(self) -> Filter:
        values = self.value if self.op == "in" else [self.value]
        if self.op == "in" and (not isinstance(values, list) or not 1 <= len(values) <= 50):
            raise ValueError("in requires 1 to 50 scalar values")
        for value in values:
            if type(value) not in (str, int, bool):
                raise ValueError("only string, integer and boolean values are supported")
            if isinstance(value, str) and len(value) > 256:
                raise ValueError("filter text too long")
            if type(value) is int and abs(value) > 2**31 - 1:
                raise ValueError("integer out of range")
        return self


class OperationRequest(StrictModel):
    resource_id: str = Field(
        default="demo", min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$"
    )
    tool: Literal["db.query_rows", "db.update_rows", "db.delete_rows"]
    table: str = Field(default="customers", min_length=1, max_length=64)
    where: list[Filter] = Field(default_factory=list, max_length=8)
    changes: dict[str, Any] = Field(default_factory=dict, max_length=8)
    columns: list[str] = Field(default_factory=list, max_length=12)
    limit: int = Field(default=100, ge=1, le=200)
    intent: str = Field(min_length=1, max_length=512)
    run_id: str = Field(default="manual", min_length=1, max_length=80)
    supersedes_operation_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_shape(self) -> OperationRequest:
        if self.tool == "db.update_rows" and not self.changes:
            raise ValueError("update requires changes")
        if self.tool != "db.update_rows" and self.changes:
            raise ValueError("changes only applies to updates")
        if self.tool != "db.query_rows" and self.columns:
            raise ValueError("columns only applies to queries")
        if len(self.columns) != len(set(self.columns)):
            raise ValueError("duplicate columns")
        for value in self.changes.values():
            if type(value) not in (str, int, bool):
                raise ValueError("unsupported change value")
            if isinstance(value, str) and len(value) > 128:
                raise ValueError("change text too long")
        return self

    def normalized(self) -> dict[str, Any]:
        result = self.model_dump()
        result["where"] = sorted(result["where"], key=canonical)
        if self.tool == "db.query_rows":
            result["columns"] = sorted(self.columns or PUBLIC_FIELDS)
        return result


class AgentPrincipal(StrictModel):
    id: str
    token_sha256: str = Field(min_length=64, max_length=64)
    active: bool = True
    resources: list[str] = Field(default_factory=lambda: ["demo"])
    tools: list[str] = Field(default_factory=lambda: list(TOOLS))
    readable_fields: list[str] = Field(default_factory=lambda: list(PUBLIC_FIELDS))
    writable_fields: list[str] = Field(default_factory=lambda: list(WRITE_FIELDS))

    def permissions(self) -> dict[str, Any]:
        return self.model_dump(exclude={"token_sha256"})


def authorize(principal: AgentPrincipal, request: OperationRequest) -> None:
    if not principal.active:
        raise DomainError("PRINCIPAL_REVOKED", "此身份已被停用。", 403)
    if request.resource_id not in principal.resources or request.resource_id != "demo":
        raise DomainError("RESOURCE_FORBIDDEN", "当前身份无权访问此资源。", 403)
    if request.tool not in principal.tools:
        raise DomainError("TOOL_FORBIDDEN", "当前身份无权使用此工具。", 403)
    if request.table != "customers":
        raise DomainError("TABLE_FORBIDDEN", "不支持或无权访问此数据表。", 403)
    requested = set(request.columns or (PUBLIC_FIELDS if request.tool == "db.query_rows" else []))
    requested |= {f.field for f in request.where}
    if not requested <= set(principal.readable_fields) & set(PUBLIC_FIELDS):
        raise DomainError("FIELD_FORBIDDEN", "请求包含不可读取或不可筛选的字段。", 403)
    if not set(request.changes) <= set(principal.writable_fields) & set(WRITE_FIELDS):
        raise DomainError("FIELD_FORBIDDEN", "请求包含不可修改的字段。", 403)
    for item in request.where:
        values = item.value if item.op == "in" else [item.value]
        for value in values:
            if item.field == "id" and (type(value) is not int or value < 1):
                raise DomainError("INVALID_FILTER", "记录编号必须为正整数。")
            if item.field == "is_test" and not (
                type(value) is bool or type(value) is int and value in (0, 1)
            ):
                raise DomainError("INVALID_FILTER", "测试标记只接受布尔值或 0、1。")
            if item.field not in ("id", "is_test") and type(value) is not str:
                raise DomainError("INVALID_FILTER", "此字段的筛选值必须为文本。")
    if "status" in request.changes and request.changes["status"] not in ("active", "archived"):
        raise DomainError("INVALID_CHANGE", "状态只支持 active 或 archived。")
    if "tag" in request.changes and type(request.changes["tag"]) is not str:
        raise DomainError("INVALID_CHANGE", "标签必须为文本。")


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class DecisionRequest(StrictModel):
    decision: Literal["approve", "reject"]
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_version: int = Field(ge=1)
    view_id: str = Field(min_length=16, max_length=64)
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=16, max_length=128)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approval reason must not be blank")
        return value.strip()


class TelemetryRequest(StrictModel):
    event: Literal["first_visible", "visibility", "diff_expanded", "decision_click"]
    view_id: str = Field(min_length=16, max_length=64)
    visible_ms: int = Field(ge=0, le=86_400_000)
    hidden: bool = False


class DemoRequest(StrictModel):
    scenario: Literal["read", "tag", "review", "delete", "blocked"]


class ExecuteEnvelope(StrictModel):
    plan: dict[str, Any]
    permit: dict[str, Any]
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")


class PreviewRequest(StrictModel):
    request: OperationRequest
    principal: AgentPrincipal


class Policy(StrictModel):
    version: str
    max_total_changes: int = Field(ge=1, le=10000)
    max_delete_records: int = Field(ge=1, le=1000)
    auto_tag_max: int = Field(ge=0, le=10)
    plan_ttl_seconds: int = Field(ge=5, le=3600)
    max_snapshot_rows: int = Field(ge=1, le=10000)
    max_snapshot_bytes: int = Field(ge=1024, le=32_000_000)
    preview_timeout_ms: int = Field(ge=50, le=10000)

    @field_validator("version")
    @classmethod
    def version_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("version required")
        return value
