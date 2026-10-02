# Continuation evidence inventory

Application validation anchor: `17ccd2c5942aa316ee94509109cc01fbca925a26`.

- `final-17ccd2c/`: full 177-case local Python run at the final application SHA.
- `CI_FINAL.json`, `ci/acceptance-17ccd2c.zip`, `ci/download-final-verification.json`, `ci/final-artifact-verifier.log*`: complete Linux CI ZIP, server digest match, 57 payload hashes and independent verifier exit 0. The ZIP is archived in Git; the Actions original expires 2026-12-31T10:55:52Z.
- `ci/acceptance-400024b.zip` and earlier metadata preserve the previous successful application run. `ci/failed-6ad-job.log` preserves an actual failed integration run.
- `final/`: original continuation runs at their receipt SHAs, including real provider boundaries/Agent, v1 dev/test ablation, offline controls, browser, latency, dependency scans and local Docker network failure. Do not relabel these as v2 model results.
- `retest/`: integration and browser repeats, diagnostic model replay and the 10-case v2 development recheck. `final-code/` is the preceding 400024b Python run.
- `model-ledger-export.json`: 638 real calls, 622 valid / 16 error, CNY 1.11779816 reserved or settled estimate under one cumulative CNY 3 ledger. It is synthetic experiment evidence, not a provider invoice. Initial invalid outputs were not retained; later diagnostics retain schema errors and raw output.
- `browser-initial/`, `preflight-pytest.xml`, `integration-initial/` and the initial diagnostic PNG are preflight evidence, not frozen-source acceptance.
- `matrix-validation.log*`: structure/provenance validation of all 126 original IDs; it does not itself prove functionality.
- `ARCHIVE_MANIFEST.json`: hashes and sizes of payloads archived here, excluding itself and ignored expanded CI directories.

Raw receipts distinguish command, exit code, source SHA, source dirtiness and environment. Human participants and independent human annotators are zero. Model calls are real, but cases are authored synthetic tasks; no real danger-recall or human-benefit claim follows.

Expanded `ci/raw/` and `ci/raw-17ccd2c/` are local ignored copies recoverable from the Git ZIPs. Runtime databases, credentials, temporary signed download URLs and public-page caches are not archive payloads. Git has no automatic expiry but is not external WORM; see `docs/acceptance/EVIDENCE_RETENTION.md`.
