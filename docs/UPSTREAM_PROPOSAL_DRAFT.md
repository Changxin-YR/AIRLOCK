# 未发送的上游讨论草稿

目标：theagentrouter/agent-router #2073。状态：仅仓库内草稿，未向第三方发送；需要用户授权才发布。

Hello, thanks for documenting gateway-owned HITL. I built a small reproducible approval lab exploring the exact-call binding discussed here. It separates the agent credential from reviewer credentials, binds approval to canonical arguments, policy, target version and expiry, and preserves unknown outcomes for remote reconciliation.

A synthetic HTTP CAS adapter and official MCP SDK test are included in `tests/test_upstream.py` and `tests/test_sdk_interop.py`. The response-loss case commits once upstream, returns unknown locally, and resolves by querying the original receipt. This is a bounded research example, not an Envoy integration or general exactly-once guarantee.

Would a minimal interoperability fixture for a delegated approval context and signed decision receipt be useful? I would first align variable environments, error semantics and asynchronous client capabilities with the project's chosen contract. I am not proposing that a model recommendation or reversibility should grant permission.

复现：`python -m pytest -q tests/test_sdk_interop.py tests/test_upstream.py tests/test_new_boundaries.py`。外部服务是本机独立合成进程，没有生产凭据或数据。
