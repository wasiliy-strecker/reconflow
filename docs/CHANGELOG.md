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

## 2026-11-14 09:22 CET — Local AWS Agent Toolkit and Codex connection

- Area: ReconFlow development tooling and AWS documentation, branch `main`.
- Installed AWS CLI 2.40.3 for the local user with the official GPG-verified installer.
  Configured profile `portfolio` for the new AWS experience in `eu-north-1` and
  completed browser login. The toolkit itself uses its `us-east-1` service endpoint.
- Configured Codex only, installed 25 default AWS skills and set
  `AWS_MCP_PROXY_PROFILES=portfolio` in the local MCP configuration. Preserved a private
  configuration backup and verified all pre-existing Codex settings were unchanged.
- Verification: authenticated STS identity and plan queries succeeded; the toolkit
  catalog returned 123 skills; an independent MCP handshake and tool listing succeeded
  with 8 tools. Verified the profile region, config mode 0600, preserved original
  project instructions and a single marked AWS guidance block. `git diff --check` passed.
- The plan query reported Free Plan, active, positive remaining credits at setup time.
  No application resources, paid-plan upgrade or advanced-feature activation were made.
- Files: `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/AWS_RUNBOOK.md`,
  `docs/CHANGELOG.md`, `docs/licenses/AWS_AGENT_TOOLKIT_LICENSE.txt`,
  `docs/licenses/AWS_AGENT_TOOLKIT_NOTICE.txt`. User-local binaries, skills and
  configuration are outside Git; credentials and authentication caches were not committed.
- Existing Frankfurt deployment templates still require a coordinated compatibility
  and region update before deployment to Stockholm. Restart Codex to load its new tools
  and skills. No application code changed, so application tests were not rerun.

## 2026-11-15 10:18 CET — Stockholm Free Plan preparation with OpenAI retained

- Replaced Frankfurt defaults in Terraform, backend, environment examples and deployment
  workflow with Stockholm. Updated only the private local region; keys and EUR 10 AI
  budget were preserved. Rebuilt/restarted local backend services without deleting volumes.
- Prepared Aurora Express (0–1 ACU, 300-second auto-pause, deletion protection), an
  application SQL login and three Secrets Manager secrets through an explicit operator
  script. Its default is read-only; resource creation requires --apply and the expected
  project ID. SDK login support uses the development-only boto3 CRT dependency.
- Preparation rejects non-active/non-Free plans, exhausted credits, wrong region/project
  and foreign resource ownership. It preserves existing secret values, uses verified TLS,
  and does not retry ambiguous mutations automatically or expose secrets in output/state.
- Terraform now reads the separately managed database, leaves Lambda concurrency unreserved
  for the observed 10-slot quota, and disables GitHub OIDC by default. Added regional and
  project checks, six mocked infrastructure plan tests and eleven preparation tests.
- Updated architecture, deployment/cleanup instructions and Stockholm cost assumptions:
  provisional USD 3–7 monthly AWS credit consumption for 20–100 short visits. OpenAI remains
  separately billed; local and AWS SQL databases have independent budget ledgers.
- Verification: 41 unit/adapter/preparation tests and 14 PostgreSQL/API integration tests
  passed. Integration job dispatch was mocked so the running worker could not consume test
  jobs; AI responses were simulated. The real local SQL-login setup was tested twice and
  did not rotate its password or grant administrator privileges.
- Ruff check/format, TypeScript, production frontend build, backend Docker build, workflow
  YAML parsing, both Terraform validates and six mocked Terraform plan tests passed.
  The browser flow passed against the restarted local stack without paid AI calls.
- Authenticated read-only preflight confirmed ACTIVE FREE, positive credits, expiry
  <private-plan-expiry>, 10 unreserved Lambda slots and Aurora default 17.9 with zero-ACU support.
  A real bootstrap plan using the new default proposes six additions in Stockholm only.
- No AWS resources/secrets were created, no real Express/Data API deployment was claimed,
  no Paid/Advanced upgrade occurred, and nothing was pushed or published. Actual deployment
  and real AWS acceptance checks remain subject to the separately agreed deployment step.

## 2026-11-15 11:11 CET — Express initial database compatibility

- The user approved AWS deployment on the existing Free Plan. The first create request
  definitively failed with `InvalidParameterCombination`; CloudTrail identified the
  unsupported initial `DatabaseName` argument. Stockholm cluster inventory remained empty.
- Preparation now creates the SQL database through the IAM-authenticated `postgres`
  connection, outside a transaction and under an advisory lock. Terraform no longer
  checks the initial-database metadata, which does not reflect later SQL creation.
- Verification: all eleven preparation tests passed, including real local database
  creation, repeated setup, password preservation and restricted role privileges.
  Ruff and all four application Terraform tests passed. Frontend was unaffected.
