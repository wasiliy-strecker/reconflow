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

## 2026-11-15 11:14 CET — Aurora preparation and deployment bootstrap verified

- Created the authorized Stockholm Express cluster, SQL database and restricted SQL
  user, enabled Data API and created three tagged secrets. Real Data API `SELECT 1`
  succeeded. Aurora PostgreSQL is 17.9 with 0–1 ACU, 300-second pause and deletion protection.
- Corrected local TLS trust discovery: the binary psycopg wheel's OpenSSL did not
  resolve `sslrootcert=system` to the installed trust store. Preparation now explicitly
  uses Python's system CA bundle with hostname verification; real IAM login succeeded.
- All eleven preparation tests and Ruff check/format passed. The six reviewed bootstrap
  resources were created (private encrypted/versioned state bucket and ECR configuration).
- Free Plan remains ACTIVE; AWS now reports positive credits. No tariff or advanced
  feature change was requested. Application rollout and public acceptance checks follow.

## 2026-11-15 11:24 CET — Budget visibility and Terraform login compatibility

- Excluded credits/refunds from the USD 15 monthly awareness budget so Free Plan
  credits do not mask metered consumption before the 80-percent email threshold.
  This changes alert calculation only, not the Free Plan or payable invoice.
- Documented the short-lived credential handoff needed by Terraform 1.13.5's S3
  backend. Real remote-state initialization succeeded with credentials only in the
  subprocess environment; no credentials were saved in files or arguments.
- All four mocked application Terraform tests passed, including the credit-exclusion
  assertion and an Express cluster without initial-database metadata. Formatting and
  diff checks passed; TypeScript and production frontend build also passed.
- The seed/reconciliation/XLSX integration test passed against real Aurora Data API.
  File storage and queue dispatch were mocked for this focused SQL parity check;
  complete deployed-service acceptance remains a separate step. No OpenAI call made.

## 2026-11-15 11:38 CET — Stockholm AWS deployment and public workflow acceptance

- Deployed the owner-approved test stack on the existing Free Plan: six bootstrap
  resources, 34 application resources, the external Express cluster/writer and three
  secrets. Public test URL: https://d33v3exmdsu4yz.cloudfront.net.
- Uploaded the immutable linux/amd64 image from runtime revision `4cd28b3` with digest
  `sha256:8c1cde0c613604fcfbb7537598c7636294679c0d67ce155ccd7438f871873039`.
  Published built frontend assets before index.html and invalidated the CloudFront entry.
- Migration Lambda succeeded twice; a subsequent real Terraform plan found no drift.
  Real browser tests passed both without AI and with exactly two paid OpenAI requests.
  Extraction, confirmation, reconciliation, suggestion, manual assignment, CSV deduplication,
  XLSX export and mobile layout worked through CloudFront/API Gateway/Lambda/SQS/Data API.
- Verified two-client document/job/run/report isolation, CSRF/Origin enforcement,
  fixture-only uploads, no-store responses and denied anonymous S3 object access.
  Test sessions were removed; synthetic S3 objects expire through the configured lifecycle.
- AI ledger records 1,234 input / 487 output tokens, EUR 0.00040359 estimated cost,
  both calls completed and no outstanding reservations. No ambiguous paid request repeated.
- All functions active, queues/DLQ empty, no ERROR/timeout records in the inspected Lambda
  logs. Budget amount, credit exclusion, 80-percent threshold and selected recipient verified.
- Post-deployment plan query remains ACTIVE FREE, positive credits, expiry <private-plan-expiry>.
  No Paid/Advanced upgrade, DNS change or GitHub publication occurred. Keys, email,
  Terraform state and private acceptance receipts remain outside Git.
- Auto-pause/resume acceptance is still pending. Aurora instance logs report service
  maintenance/continuous backup lag; quiet-demo cost estimates remain conditional until
  zero-ACU idle behavior is observed. Deployment documentation records this limitation.

## 2026-11-15 11:51 CET — Zero-ACU pause and browser resume verified

- CloudWatch recorded minimum/maximum 0 ACU for the full 11:44 CET minute. The final
  idle check used metrics only; direct instance-log diagnostics can themselves wake
  an instance or delay pause, as now documented in the runbook.
- A fresh public browser at 11:49 CET loaded six synthetic invoices 23.92 seconds after
  Demo starten. Existing startup handling recovered from two temporary 503 responses;
  subsequent session and seed calls succeeded, with no page errors or paid AI calls.
  The acceptance session was removed. Long pauses exceeding 24 hours were not tested.
- Updated README, architecture, runbook and cost notes to reflect successful idle/resume
  acceptance. The owner explicitly requested keeping AWS reachable for personal tests.
  Local health/config still pass with OpenAI enabled. Documentation diff checks passed;
  no application or infrastructure configuration changed after their validated deployment.

## 2026-11-16 20:03 CET — GPU benchmark foundation

- Added isolated GPU lease/request tables, a Decimal budget ledger, signed rental labels,
  fixed synthetic workloads, provider adapter, operator authentication and admission rules.
- Added server-only configuration and pinned the official Vast.ai SDK with hashed runtime
  dependencies. Paid GPU execution defaults to disabled; no provider calls or rentals ran.
- Validation: 12 focused protocol, transport, budget, concurrency, privacy and adapter tests
  passed; Ruff passed. Integration checks use a separate local benchmark test database.
- Applied the additive migration locally. No AWS deployment, push or publication occurred.

## 2026-11-16 20:24 CET — GPU runner, API and independent cleanup

- Added authenticated runner callbacks, at-most-once claims, scoped progress/results,
  public standard reports, private prompt controls and session deletion scrubbing.
- Added the standalone Ollama runner with pinned model/runtime digests, real streaming
  counters, monotonic latency measurement and sampled NVIDIA telemetry. The runner ZIP
  generator is deterministic and performs no upload or rental.
- Added durable SQS rental processing and provider-label reconciliation. Independent
  cleanup survives unavailable SQL, ignores foreign instances and confirms disappearance
  before releasing the concurrency slot. Budget debits remain deliberately conservative.
- Validation: all 70 Python tests passed, including existing invoice integration tests;
  Ruff passed. Runner/bootstrap imports and Zstandard/TLS availability passed inside the
  pinned Python 3.14 container. No real GPU, Vast credential or AWS mutation was used.

## 2026-11-16 20:33 CET — GPU dashboard and AWS delivery preparation

- Added GPU selection, fixed/live prompt controls, operator login, lifecycle feedback,
  budget visibility, filtered comparisons and detailed measurement reports to the existing
  responsive React interface. Empty state explicitly contains no invented measurements.
- Added the existing-stack watchdog Lambda/Scheduler, scoped S3/secret access, failure
  alarm and deployment workflow updates. Paid admission stays off by default and cannot
  be enabled with missing runner/secret configuration. No AWS changes were applied.
- Bounded comparison queries for Data API and fixed the SDK inventory/Decimal compatibility
  boundary. Added public-versus-private report tests and plain-text output browser coverage.
- Added docs/GPU_BENCHMARKS.md covering setup, conservative budget debits, reproducibility,
  live acceptance, monitoring and rollback; updated architecture and README.
- Final validation: 71 Python tests passed; the strengthened runner/security subset passed
  again after its additional assertions. Ruff check/format, TypeScript and frontend build
  passed. Four browser tests passed on the isolated local stack, including the existing
  invoice workflow and mobile layout, using installed Chromium 1248. Terraform validate
  and all six mocked app-stack tests passed. Two independently packaged runner ZIPs had
  identical SHA-256 b09ac4a06a7884d6e6c790602a6e4aad64fc48c1e9e5a5137b9ab66a2efbfb22.
- Hardware acceptance remains pending: no Vast credentials were present, no GPU was rented,
  and no real benchmark results were produced. No push, publication or AWS deployment.

## 2026-11-16 20:36 CET — Close GPU admission recovery gap

- Persisted the S3 recovery record before committing admission so a pre-dispatch crash
  cannot strand the one-GPU slot. A failed control write rolls back the budget reservation.
- Added a grace period before deleting controls with no visible SQL row, covering a
  concurrent reaper observing an uncommitted admission.
- Validation: all 18 focused GPU tests passed, including both new fault-injection cases;
  Ruff check/format and git diff checks passed. Frontend and Terraform are unchanged.
- Temporary isolated API/worker/browser preview services were stopped after verification.

## 2026-11-16 21:27 CET — Public GitHub publication preparation

- The owner requested a public application portfolio repository without private data.
  Reviewed all 14 existing commits, every reachable file version, commit metadata and
  both screenshots. Gitleaks 8.30.1 found no credentials; exact comparisons against
  private local key values also found no matches. No private environment, state or
  customer document files were tracked.
- Prepared public GitHub-username attribution and the account's numeric-ID noreply
  address. Removed private operator identifiers/billing snapshots from documentation
  and regenerated the two screenshots using synthetic fixtures with no paid AI calls.
  The historical copies will receive the same cleanup before the first upload.
- Preserved the complete original history in an ignored mode-0600 local Git bundle.
  Added a full-history, checksum-pinned Gitleaks CI job and clarified that the newer
  GPU benchmark source has not been deployed or tested on rented hardware.
- Verification: 48 unit/adapter tests and 25 integration tests passed. Integration
  used a temporary local database that was removed afterward and mocked dispatch;
  the existing application and budget ledger were preserved. Ruff check/format,
  TypeScript/production build, invoice browser flow, eight mocked Terraform plans,
  Terraform formatting, CI YAML parsing and diff checks passed.
- No AWS deployment, paid AI/GPU call or provider credential upload is part of this
  publication step. Final rewritten-history scan and GitHub CI follow before handoff.

## 2026-11-16 21:34 CET — Public repository and CI trust store

- Published the sanitized 15-commit history to the owner-approved public repository:
  https://github.com/wasiliy-strecker/reconflow. All milestones remain present; historical
  author metadata, documentation and screenshots use the same public-data rules.
- A fresh remote clone matched the audited local history exactly. Gitleaks and literal
  private-value checks found no leaks across all reachable commits and 204 file versions.
  GitHub secret scanning and push protection are enabled; no deployment secrets were uploaded.
- The first hosted CI run passed the secret scan and all eight infrastructure tests.
  Python reported 72 passes and one failure because uv's managed Python did not discover
  Ubuntu's CA bundle. Set SSL_CERT_FILE explicitly for the application job, retaining
  certificate and hostname verification and the existing real-database integration test.
- Verification before the follow-up push: workflow parsing, certificate-path resolution,
  loading the system trust store, Ruff check/format and diff checks passed. The full
  hosted application and browser suite will run again with this environment correction.

## 2026-11-16 21:36 CET — Public GitHub acceptance complete

- GitHub CI run [43951172100](https://github.com/wasiliy-strecker/reconflow/actions/runs/43951172100)
  passed for revision `d6990dd`: all 73 Python tests, four browser scenarios, eight mocked
  Terraform tests, Ruff, TypeScript/production build and the full-history credential scan.
- The repository is public, all sanitized milestones are pushed, and GitHub attribution
  uses the public username and noreply email. Original private history backups and
  runtime configuration remain ignored and local. No AWS resources, live deployment,
  paid AI requests or GPU rentals were changed by publication or CI.

## 2026-11-24 07:56 CET — Invoice readability and original downloads

- Increased text contrast across the invoice workspace and review dialog. Enlarged
  table headings, invoice data and supporting labels on desktop and mobile.
- Added an original-file download under the invoice number, also available for
  documents awaiting extraction. The download reads the session's stored document,
  keeps its filename and leaves the list open. The row still opens the comparison view.
- Verified the rebuilt local frontend with Chromium. PDF, PNG and JPEG downloads
  matched the fixture bytes and filenames. The review, reconciliation and Excel export
  flow passed. At widths of 390 and 1440 pixels the download was in view and the
  sampled workspace text had a minimum measured contrast of 5.09:1.
- TypeScript, the production build, Ruff and the document session-isolation integration
  test passed. Recorded the owner's preference to commit each completed task.

## 2026-11-24 08:12 CET — Standing demo release instruction

- The owner authorized publishing each validated demo change to the existing AWS
  environment after commit. Recorded the target and verification step in the project rules.
- Prepared frontend release `84920a1` from the AWS-compatible base `71b6540` and
  the invoice change `9e3adad`. Its production build matched the locally tested
  release files byte for byte. The browser test covered PDF, PNG and JPEG downloads,
  invoice review, reconciliation, Excel export and mobile layout.

## 2026-11-24 08:26 CET — Independent GPU Compare application

- Moved this checkout and its linked release worktree into the Python portfolio directory. Preserved existing Compose project and volume names.
- Extracted benchmarking into its own repository. Removed the GPU dashboard, API integration, worker dispatch, provider dependency and GPU infrastructure from the invoice application. Kept the checksum-protected historical SQL migration for existing databases.
- Verified 55 Python tests, Ruff, TypeScript, the production frontend build, application Terraform tests and the invoice browser flow including original downloads and Excel export.

## 2026-11-25 08:15 CET — Example files for manual demo tests

- Added the six synthetic original invoices and payment CSV to `docs/beispiele/` and
  linked the folder from the README. All seven files matched the public demo's example
  downloads byte for byte. Git preserves their exact bytes on checkout.

## 2026-11-25 17:28 CET — Demo startup feedback

- Replace empty counts and the empty invoice list with four metric placeholders and six
  placeholder rows during demo startup. Show a screen-reader status message in place
  of the start card, including while the database resumes. Respect reduced motion.
- Verified the production frontend locally against the API. Desktop browser coverage
  includes loading, populated results, original downloads, reconciliation, export and
  session reset. Mobile coverage checks reduced motion and recovery after a failed start.
- TypeScript, production build, Ruff and 29 focused Python tests passed. AWS preflight
  verified the existing Stockholm website and the active Free Plan with positive credits.

## 2026-11-25 17:29 CET — AWS demo startup verified

- Published the static frontend from `0402062` to the existing demo. CloudFront's
  entry page, JavaScript and CSS matched the tested build after invalidation.
- Both browser scenarios passed on the public URL. Confirmed the wait message was
  inside the viewport after clicking Start at 1440 and 390 pixels. The live session
  loaded six invoices and payments, completed the invoice workflow and reset its
  own test data. The mobile failure scenario used a simulated response.

## 2026-11-25 17:46 CET — Immediate reconciliation and action feedback

- Starting a reconciliation immediately opens and focuses the results. The pending
  table and its two derived metrics show placeholders until the refreshed workspace
  arrives. A failed rerun displays the error alongside the previous completed result.
- Pending imports, confirmations, AI jobs, decisions, downloads, status checks and
  resets now show the action in a viewport-visible status, including in dialogs.
  Restoring a session and opening a document preview also provide loading feedback.
- Verified the production build in Chromium with controlled network delays for
  confirmation, refresh and reconciliation, plus a failed rerun. The invoice,
  reconciliation, download, export, reset and mobile checks passed without paid AI.
  Ruff, TypeScript and 29 focused Python tests passed.

## 2026-11-25 17:47 CET — Public reconciliation feedback release verified

- Released frontend commit `4999944` to the existing CloudFront demo. Verified the
  public HTML, JavaScript and CSS against the tested artifacts. Both public browser
  scenarios passed, including the immediate view switch during a held request, dialog
  feedback, refresh and recovery from a simulated failed rerun.
- Additional local mobile checks confirmed the KI progress status with a simulated
  provider response, reduced motion and navigation away during reconciliation. The
  completed job preserved the visitor's selected view.

## 2026-11-25 18:02 CET — Explain unassigned payments

- The payment review now shows the payer, incoming amount and bank reference
  alongside possible invoices. It explains why a payment needs a decision and
  why an amount-based candidate appears. Only actual invoice amounts are shown.
- Visitors can assign the payment to a named invoice or leave it open. The
  optional AI suggestion is secondary. Successful assignment identifies the
  payment amount and invoice number.
- Both local browser tests passed, including leaving the payment open and then
  assigning it. Verified the dialog and actions at 320 and 390 pixels. TypeScript,
  the production build, Ruff and 29 focused Python tests passed.

## 2026-11-25 18:04 CET — Public payment review verified

- Published frontend commit `f1fe94c` to the existing AWS demo. Its public
  entry page, JavaScript and CSS matched the tested build.
- Both Chromium scenarios passed on the public URL and the local container.
  Verified that leaving the Mira Kunsthandel payment open preserves the case,
  then assigning it to RE-2026-1005 yields three matched invoices.
- The first live check timed out while the reconciliation job was still running.
  The browser test now gives asynchronous results up to 60 seconds to arrive.
  The verification used synthetic data in its own session and made no AI requests.

## 2026-11-25 18:14 CET — Inspect an original invoice from payment review

- Each payment candidate with a linked document opens its session-authorized
  original in a separate browser tab. Closing the tab returns the visitor to
  the same payment decision. A candidate without a document explains this inline.
- Verified in local Chromium that the Mira Kunsthandel original renders, matches
  the bundled JPEG byte for byte and can be closed before assigning the payment.
  Checked the link on a 390-pixel viewport and a simulated document-free candidate.
  Both browser tests, TypeScript, the frontend build, Ruff and 30 Python checks passed.

## 2026-11-25 18:15 CET — Public original invoice link verified

- Published frontend commit `9eaae98` to the existing AWS demo. The public HTML,
  JavaScript and CSS matched the locally tested build. Both public browser tests
  passed, including opening the correct original for RE-2026-1005, closing its
  tab and assigning the payment in the original dialog.

## 2026-11-25 18:26 CET — Guide the demo through three steps

- Numbered the shared desktop and mobile navigation: invoices, incoming payments,
  then reconciliation. Each of the first two tables links to the next step.
  The activity log remains independently accessible.
- Scoped import actions to their respective steps. Starting or repeating a
  reconciliation and exporting its report are available in step three. Updated
  empty states, demo startup, session reset and the README walkthrough.
- Both local Chromium scenarios passed. The workflow check verified that moving
  between steps creates no reconciliation job, then exercised the explicit start,
  review, export and reset. Navigation fit at 320, 390 and 768 pixels and on
  desktop. TypeScript, the frontend build, Ruff and 29 focused Python tests passed.

## 2026-11-25 18:27 CET — Guided workflow verified on AWS

- Published frontend commit `4e8e71f`. The CloudFront entry page, JavaScript
  and CSS matched the local build. Both public browser tests passed, covering
  the three-step journey, explicit reconciliation, manual assignment, Excel
  export, responsive navigation and reset of the isolated test session.

## 2026-11-25 21:25 CET — Portfolio repository update

- Updated the English project title for the existing public GitHub repository.
  Checked the publication history against the project's privacy rules and private
  file fingerprints. Gitleaks found no secrets, commit identities use GitHub
  noreply addresses, and the six example invoices and payment CSV match the
  synthetic fixture generator byte for byte.
