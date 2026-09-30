# AIRLOCK engineering contract

This is a small personal portfolio project, not a universal security gateway.

Read README.md and docs/PLAN.md. Agent credentials must never approve a request. Human approval cannot override authorization or block rules. Only registered structured SQLite operations are supported; no raw SQL, shell, arbitrary URL, or bypass switch. Preview must modify only a consistent shadow snapshot. Bind approval to immutable arguments, identity, policy, schema and business state. Recheck inside the final write transaction. Commit business mutations and the operation receipt atomically. Recover uncertain outcomes through that receipt. Persist state; SSE is notification only.

Do not manufacture benchmarks, model responses, user studies, screenshots or green test output. Report unavailable external checks as NOT_TESTABLE. Do not weaken tests to obtain a green build. Do not touch other repositories. Never commit runtime credentials or databases.

Implementation is being completed in this conversation. Codex's final role is independent review and repair, not silently replacing the design.
