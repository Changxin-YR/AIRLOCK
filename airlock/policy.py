from __future__ import annotations

from pathlib import Path
from pydantic import Field
import yaml
from .common import AirlockError, digest
from .contracts import StrictModel, ToolRequest


class Policy(StrictModel):
    name: str = "personal-demo-v1"
    max_changed_records: int = Field(default=100, ge=1, le=10000)
    auto_tag_records: int = Field(default=1, ge=0, le=1)
    approval_ttl_seconds: int = Field(default=300, ge=1, le=3600)

    @property
    def version(self) -> str:
        return digest(self.model_dump())

    def decide(self, request: ToolRequest, facts: dict) -> tuple[str, str]:
        if facts.get("coverage") != "exact_on_snapshot":
            return "block", "PREVIEW_UNAVAILABLE"
        if request.tool == "db.query_rows":
            return "pass", "AUTHORIZED_READ"
        if facts["total_changed"] > self.max_changed_records:
            return "block", "IMPACT_LIMIT"
        if request.tool == "db.delete_rows" and not request.filters:
            return "block", "UNBOUNDED_DELETE"
        if facts["total_changed"] == 0:
            return "pass", "NO_BUSINESS_CHANGE"
        if (request.tool == "db.update_rows" and set(request.values) == {"tag"}
                and facts["total_changed"] <= self.auto_tag_records):
            return "pass", "EXPLICIT_SMALL_TAG_RULE"
        return "need_approval", "HUMAN_REVIEW_REQUIRED"


def load_policy(path: Path | None) -> Policy:
    if path is None:
        return Policy()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Policy.model_validate(raw)
    except Exception as exc:
        raise AirlockError("POLICY_UNAVAILABLE", "策略无法校验，停止新的执行。", 503) from exc
