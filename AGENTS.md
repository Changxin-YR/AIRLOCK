# AIRLOCK repository context

This is an implemented personal project. The next Codex task is **final verification**, not rebuilding it from an obsolete prompt. Read `docs/CODEX_REVIEW.md`, `docs/ARCHITECTURE.md`, and the actual code/tests. Prior conversations and progress claims are not evidence.

Commands: `pip install -r requirements-dev.lock`; `npm ci --prefix apps/web`; `python scripts/verify.py`; for browser install Chromium with the project Playwright CLI, then `python scripts/verify.py --output Evidence/ci --browser`. Compose isolation is a separate workflow gate.

Invariants: Agent and human credentials are separate; approvals never override authorization/blocks; previews write only a consistent shadow copy; immutable plans bind args/state/schema/policy/grants/expiry; revalidate and execute in one short target transaction; business effect and receipt commit together; uncertain results reconcile receipts, never blindly replay; no arbitrary SQL/shell/connection string, no test bypass in production. Historical reads must enforce current permissions. SSE is notification, not authority.

Do not expose `.airlock*`, `.env`, reviewer credentials, runner keys, model keys or checkpoints. Synthetic benchmark results are not real-world security accuracy. Provider fixture tests are not live LLM tests. No user study has been performed. Only report commands actually run, with exit codes and evidence.

Preserve history. Do not reset/delete user data. Make minimal justified repairs with regression tests; do not weaken failing tests to pass. Scope changes require an ADR. Stop after verified findings/repairs; don't add MySQL/RAG/multi-tenancy/automatic approvals.
