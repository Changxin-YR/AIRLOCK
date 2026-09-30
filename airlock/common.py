"""Deterministic encodings and deliberately non-sensitive public errors."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


def now() -> float:
    return time.time()


def canonical(value: Any) -> str:
    # Reject NaN and non-JSON types. Field types are additionally checked at ingress.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sign(value: Any, secret: str) -> str:
    return hmac.new(secret.encode(), canonical(value).encode(), hashlib.sha256).hexdigest()


def verify(value: Any, signature: str, secret: str) -> bool:
    return hmac.compare_digest(sign(value, secret), signature)


def strict_json(data: str | bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(_: str) -> None:
        raise ValueError("Non-finite JSON number")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


class AirlockError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, *, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable

    def public(self, operation_id: str | None = None) -> dict[str, Any]:
        return {"code": self.code, "safe_message": self.message, "retryable": self.retryable,
                "operation_id": operation_id, "suggested_next_action":
                "重新读取状态并创建新计划；不要重用旧批准。" if self.code == "STALE" else
                "检查输入和授权范围；需要人工确认时等待审批。"}
