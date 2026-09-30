"""The entire supported tool language. There is intentionally no raw SQL field."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Self
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

Scalar = Annotated[StrictStr, Field(max_length=160)] | StrictInt
READ_FIELDS = {"id", "project", "name", "status", "is_test", "tag", "version"}
WRITE_FIELDS = {"name", "status", "tag"}
STATUS_VALUES = {"active", "archived", "paused"}
TERMINAL = {"SUCCEEDED", "BLOCKED", "REJECTED", "EXPIRED", "CANCELLED", "STALE", "FAILED"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Condition(StrictModel):
    field: Literal["id", "project", "name", "status", "is_test", "tag", "version"]
    op: Literal["eq", "lt", "lte", "gt", "gte", "in"] = "eq"
    value: Scalar | Annotated[list[Scalar], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.op == "in") != isinstance(self.value, list):
            raise ValueError("in requires a nonempty list; other operators require a scalar")
        values = self.value if isinstance(self.value, list) else [self.value]
        numeric = self.field in {"id", "is_test", "version"}
        if any(type(x) is not (int if numeric else str) for x in values):
            raise ValueError("Filter value type does not match the field")
        if any(isinstance(x, int) and not -(2**63) < x < 2**63 for x in values):
            raise ValueError("Integer outside SQLite range")
        return self


class ToolRequest(StrictModel):
    tool: Literal["db.query_rows", "db.update_rows", "db.delete_rows"]
    resource_id: Literal["demo-crm"] = "demo-crm"
    table: Literal["customers"] = "customers"
    filters: Annotated[list[Condition], Field(max_length=8)] = Field(default_factory=list)
    values: dict[str, Annotated[StrictStr, Field(max_length=160)]] = Field(default_factory=dict)
    columns: Annotated[list[StrictStr], Field(min_length=1, max_length=7)] = Field(
        default_factory=lambda: ["id", "name", "status", "is_test", "tag"])
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 20
    task: Annotated[StrictStr, Field(max_length=500)] = ""
    run_id: Annotated[StrictStr, Field(max_length=80)] = "default"

    @field_validator("columns")
    @classmethod
    def permitted_columns(cls, value: list[str]) -> list[str]:
        if not set(value) <= READ_FIELDS or len(set(value)) != len(value):
            raise ValueError("Unsupported or duplicate columns")
        return value

    @model_validator(mode="after")
    def check_values(self) -> Self:
        if self.tool == "db.update_rows":
            if not self.values or not set(self.values) <= WRITE_FIELDS:
                raise ValueError("Only name, status and tag may be updated")
            if "status" in self.values and self.values["status"] not in STATUS_VALUES:
                raise ValueError("Unsupported status")
        elif self.values:
            raise ValueError("Values are only valid for updates")
        return self


class ApprovalDecision(StrictModel):
    decision: Literal["approve", "reject"]
    plan_digest: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
    view_digest: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
    expected_version: Annotated[StrictInt, Field(ge=1)]
    decision_key: Annotated[StrictStr, Field(min_length=8, max_length=100)]
    reason: Annotated[StrictStr, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def rejection_reason(self) -> Self:
        if self.decision == "reject" and not self.reason.strip():
            raise ValueError("A rejection reason is required")
        return self


class Login(StrictModel):
    username: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    password: Annotated[StrictStr, Field(min_length=1, max_length=200)]


class VisibilityTelemetry(StrictModel):
    visible_ms: Annotated[StrictInt, Field(ge=0, le=86_400_000)]
    diff_opened: bool
    first_visible_at: Annotated[StrictStr, Field(max_length=40)]
    event_id: Annotated[StrictStr, Field(min_length=8, max_length=100)]


def normalize(request: ToolRequest) -> dict[str, Any]:
    # Preserve filter/column ordering: deterministic encoding, not SQL equivalence.
    return request.model_dump(mode="json")
