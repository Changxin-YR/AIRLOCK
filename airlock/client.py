"""Agent-side client. No target path, execution secret, or human credential."""
from __future__ import annotations
import time
from urllib.parse import urlsplit

import httpx

from .common import AirlockError
from .contracts import TERMINAL, ToolRequest


class AgentClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 15):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
            raise ValueError('Gateway must be an explicit HTTP(S) origin without credentials')
        if parsed.scheme != 'https' and parsed.hostname not in {'127.0.0.1', 'localhost', 'gateway', 'testserver'}:
            raise ValueError('Non-local gateway connections require HTTPS')
        if len(token) < 32: raise ValueError('Missing Agent credential')
        self.http = httpx.Client(base_url=base_url, headers={'Authorization': 'Bearer '+token},
                                 timeout=timeout, follow_redirects=False, trust_env=False)

    def _result(self, response: httpx.Response) -> dict:
        try: body = response.json()
        except ValueError:
            raise AirlockError('GATEWAY_UNAVAILABLE', '网关返回了无法解析的响应。', 502) from None
        if response.is_error:
            error = body.get('error', {})
            raise AirlockError(error.get('code', 'GATEWAY_REJECTED'),
                               error.get('safe_message', '网关拒绝此请求。'), response.status_code,
                               retryable=bool(error.get('retryable', False)))
        if not isinstance(body, dict):
            raise AirlockError('INVALID_RESPONSE', '网关响应不符合契约。', 502)
        return body

    def submit(self, request: ToolRequest | dict, idempotency_key: str) -> dict:
        request = request if isinstance(request, ToolRequest) else ToolRequest.model_validate(request)
        return self._result(self.http.post('/api/operations', json=request.model_dump(mode='json'),
            headers={'Idempotency-Key': idempotency_key}))

    def get(self, operation_id: str) -> dict:
        # A handle is data, never a path or URL supplied to the HTTP transport.
        if not operation_id or len(operation_id) > 80 or any(c not in '0123456789abcdef-' for c in operation_id):
            raise ValueError('Invalid operation handle')
        return self._result(self.http.get('/api/operations/'+operation_id))

    def wait(self, operation_id: str, *, timeout: float = 300, interval: float = 1) -> dict:
        deadline = time.monotonic()+timeout
        while True:
            result = self.get(operation_id)
            if result['state'] in TERMINAL or result['state'] == 'UNKNOWN': return result
            if time.monotonic() >= deadline: return result  # Still pending, never assume success.
            time.sleep(max(0.1, interval))

    def close(self): self.http.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
