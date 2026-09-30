"""Small shared primitives. A digest is integrity evidence, never authorization."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable

    def public(self) -> dict[str, Any]:
        return {"code": self.code, "safe_message": self.message, "retryable": self.retryable}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sign(value: Any, secret: str) -> str:
    return hmac.new(secret.encode(), canonical(value).encode(), hashlib.sha256).hexdigest()


def strict_json(raw: bytes | str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DomainError("INVALID_JSON", "JSON 格式无效或存在重复字段。", 400) from exc
