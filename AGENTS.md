# AIRLOCK engineering contract

Read README.md and docs/ARCHITECTURE.md. This is a constrained personal SQLite review project, not a universal security gateway. Codex is the final independent reviewer, not the primary implementer.

Agent identity cannot approve. Approval cannot override authorization or block rules. Never add raw SQL, shell, arbitrary resource URLs, bypass flags or model-controlled permissions. Preview writes only an SQLite Backup API shadow. Bind immutable request, principal, policy, schema, snapshot and expiry. Recheck within the final target transaction. Business changes and receipt commit atomically. Recover uncertain results via receipts. Never hold a target transaction while a human decides. SSE is notification, not durable state.

Run `python -m pytest -q`, `npm ci --ignore-scripts --prefix apps/web`, `npm run build --prefix apps/web`, `python scripts/evaluate.py`, actual browser and Compose checks. Preserve raw results. Do not weaken assertions or fake external model calls, screenshots, user studies or performance. Unavailable checks are NOT_TESTABLE. Credentials, runtime databases and private checkpoints must never enter Git, logs or public artifacts. Restrict work to this repository. See CODEX_REVIEW.md for final gates.
