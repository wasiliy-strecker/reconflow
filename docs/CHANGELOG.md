# Development log

## 2026-11-13 09:06 CET — Local application foundation

- Area: independent ReconFlow repository, branch `main`.
- Added typed invoice extraction, Decimal reconciliation, PostgreSQL/Data API boundary,
  SQL migrations, S3/SQS adapters, durable worker jobs and atomic AI budget reservations.
- Added FastAPI endpoints, isolated demo sessions, synthetic PDF/PNG/JPEG/CSV fixtures,
  invoice confirmation and XLSX export with formula-injection protection.
- Added React/TypeScript dashboard and Docker Compose/build configuration.
- Files: `backend/`, `frontend/`, `tests/`, Docker and dependency configuration, `docs/`.
- Verification before commit: 25 unit/adapter tests and 9 PostgreSQL/API integration tests
  passed. TypeScript and production frontend build passed. Backend image built successfully.
- Existing Contest Gallery repositories were inspected; their generated asset changes
  were left untouched. The local OpenAI key was copied privately into ignored `.env` (0600).
- AWS resources have not been provisioned. Data API is contract-tested; real AWS parity
  and pause/resume remain deployment acceptance checks.
- Live OpenAI evaluation: three synthetic documents (PDF, PNG, JPEG), 27/27 checked
  header fields correct. Estimated usage cost EUR 0.00122045. Report in
  `docs/evaluation/latest.json`; a small smoke evaluation, not an accuracy guarantee.

## 2026-11-13 09:34 CET — Validated application and browser workflow

- Area: ReconFlow application, branch `main`.
- Indexed deterministic reference matching; measured 50,000 invoices/payments in 3.165 seconds.
- Added stale-run detection, server Decimal totals, atomic manual version checks and candidate-snapshot job keys.
- Made local bootstrap repeatable and documents persistent across Moto restarts.
- Added bounded request streams, public-fixture checks, keyboard modal handling and formatted frontend sources.
- Set Standard OpenAI processing with explicit cache mode and no breakpoints to avoid cache-write charges.
- Files: backend, frontend, tests, Compose, scripts, evaluation reports and screenshots.
- Validation: 44 Python tests passed with no real API key; production frontend build passed.
- Browser flow passed on desktop/mobile, including real extraction and AI proposal before the final cache-mode change.
- Final cache-mode extraction evaluated separately: PDF/PNG/JPEG, 27/27 header fields, estimated EUR 0.00135355.
- Full Docker images built successfully; final source-only layers reused those dependency images because the host disk is nearly full.
- Only reproducible package/build caches were cleaned; existing project data was preserved.

## 2026-11-13 09:36 CET — AWS delivery preparation and documentation

- Area: ReconFlow infrastructure and delivery, branch `main`.
- Added Terraform bootstrap (ECR and encrypted versioned state) and app stack: CloudFront/S3, HTTP API, Lambda, SQS/DLQ, private Aurora Data API with 0–1 ACU and 300-second auto-pause.
- Added scoped IAM, GitHub OIDC deployment role, logs/alarms and account budget awareness.
- Added CI and manual deployment workflow with CI prerequisite, immutable image digest, migration-result check and previous-image records.
- Added README, data format guide, AWS runbook, explicit cost assumptions, MIT license and non-overwriting local environment setup.
- Files: infra/, .github/, README.md, LICENSE, docs/AWS_RUNBOOK.md, docs/COSTS.md, docs/DATA_FORMATS.md, scripts/init_env.py.
- Validation: both Terraform modules initialized with signed locked AWS provider 6.73.0 and passed validate; recursive fmt and workflow YAML parsing passed. Provider storage used temporary container memory due host disk pressure.
- No terraform plan/apply against AWS, remote GitHub workflow run, Git push, public publication or Marketplace submission was performed.
- Final application browser test passed again against the final source layers. Compose services remain available locally.
