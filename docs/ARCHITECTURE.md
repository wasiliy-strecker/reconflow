# ReconFlow architecture

ReconFlow is an independent Python portfolio project for wasiliy-strecker. It extracts
outgoing invoices with OpenAI and reconciles confirmed invoice data against incoming payments.
The first release is a demonstration, not a bookkeeping service or payment processor.

## Runtime boundaries

The Python domain module is deterministic and contains no network or database dependencies.
FastAPI coordinates imports, confirmation, jobs and reports. A Python worker processes
SQS messages. Both use the same application image with separate entrypoints.
React/TypeScript is a static frontend. All API credentials stay on the server.

Local Compose starts PostgreSQL 17, Moto for S3/SQS, a one-shot setup container, API,
worker and the built frontend behind nginx. Ports bind to loopback only.
AWS uses S3/CloudFront, API Gateway, container-based Lambda functions, SQS and Aurora
PostgreSQL Serverless v2 Express via Data API. AWS networking does not require a customer
VPC or NAT gateway. The Express internet gateway authenticates administration with IAM;
the application uses a separate SQL login through Data API.
OpenAI is a separate external processor. No Bedrock integration is implemented.

## Database

SQL is application-authored and parameterized. Local Psycopg and the Data API adapter
share the same SQL contract. Data API returns monetary decimals as strings. There is
no ORM dialect dependency. Versioned SQL files replace the earlier briefing's optional
Alembic proposal to keep the Data API transport independent of unsupported ORM dialects.
Migration checksums prevent editing already-applied migrations. Advisory transaction
locks serialize migrations and demo admission. Sessions serialize changes affecting
reconciliation snapshots. Optimistic invoice versions prevent stale editor updates.

## AI and trust boundary

`gpt-6-luna` is the configured starting model, not an automatically selected fallback.
The Responses API receives inline PDF/image data and a Pydantic structured-output schema.
Calls use `store=False`, no tools and no automatic SDK retries. `store=False` does not
promise zero provider retention. No Files API uploads or persistent conversations are used.
Documents are treated as untrusted data. Missing fields stay null. Extraction never
confirms an invoice. Human confirmation requires required fields and arithmetic checks.
Suggestions are constrained to server-selected candidate IDs and still need confirmation.

Budget reservations use an atomic monthly ledger in Europe/Berlin. The configured EUR
budget defaults to 10. A conservative USD/EUR multiplier of 1.10 and full model-context
reservation include the long-context price multiplier. After a response, actual input
and output token usage replaces the reservation. Unknown outcomes retain their reservation.
Explicit cache mode without breakpoints disables prompt-cache reads/writes for these
one-shot documents. Standard service tier is selected explicitly. Prices and exchange assumptions are
configuration, not live billing data. Other applications using the same API key are outside
this ledger. Changing model requires reviewing its limits and updating the configured prices.

## Processing and consistency

Jobs are persisted before sending their ID to SQS. A repeated pending request re-dispatches
the same ID. A durable pending-to-running claim ensures duplicate delivery does not cause a
second paid call. A running job is never automatically re-executed. Interrupted jobs become
failed on status inspection and can be retried only through the explicit retry operation.
OpenAI calls happen outside database transactions. The worker checks invoice versions before
applying an extraction result. Each successful AI extraction creates an unconfirmed revision.

Only unambiguous references with matching currency allocate payments automatically.
Multiple referenced partial payments may settle one invoice. Amount-only similarity proposes
review candidates. Overpayments and possible repeated payments remain visible. Unsupported
refunds, fees and many-invoice settlement are not silently allocated. Amounts use Decimal.
Manual choices create an audit event and a fresh reconciliation snapshot. XLSX export rejects
stale snapshots and stores user text as text, preventing spreadsheet formula injection.

## Demo and files

Public demo mode accepts only byte-identical bundled synthetic documents and payment CSV.
Arbitrary document/CSV uploads are restricted to local mode. Documents are capped at 4 MiB,
five PDF pages and 20 megapixels for images. Only PDF/JPEG/PNG are accepted after content checks.
Each session has a signed HttpOnly cookie, CSRF token, 24-hour expiry and separately scoped IDs.
Expired SQL rows are deleted on later admission. S3 lifecycle handles eventual object cleanup.
Original files are served through the session-authorized API, not public bucket URLs.
Locally, a private Docker document volume provides a fallback after Moto loses its
in-memory objects. Local volumes are retained until explicitly removed by the operator.
The static first screen does not query the database. No keep-alive pinger is used.

## Deployment boundary

The user selected the new AWS experience in Stockholm (`eu-north-1`) on 2026-11-14.
Local access uses the named CLI profile `portfolio` and browser-based `aws login`.
The Agent Toolkit service uses `us-east-1`; application resources belong in Stockholm.
Terraform, workflows, examples and runtime defaults now use Stockholm, with deployment
region validation. The owner chose to remain on the AWS Free Plan while retaining paid
OpenAI use under the existing EUR 10 application budget. AWS credits never pay OpenAI.

The Free Plan requires Aurora Express. Because the locked Terraform provider 6.73.0
cannot create Express clusters, `scripts/prepare_aws_demo.py` checks prerequisites
read-only by default. Its explicit `--apply` path prepares one tagged Express cluster
(0–1 ACU, 300-second pause, deletion protection) and three Secrets Manager secrets.
It checks the active Free Plan, credits, expiry and expected project before mutation.
Express chooses the current default engine version (17.9 on 2026-11-15); preparation
verifies zero-ACU support rather than passing the former 17.7 engine pin.

Express rejects `DatabaseName` during cluster creation. Preparation first connects to
`postgres` over verified TLS with a short-lived IAM administrator token and creates the
`reconflow` database outside a transaction, guarded by a session advisory lock. It then
creates an application SQL login and verifies its stored credentials through Data API.
SQL database creation is not reflected in the RDS cluster's `DatabaseName` metadata.
The SQL user owns the application's tables/migrations and has schema CREATE privileges,
not administrator rights. Application SQL, Decimal handling and API contracts are unchanged.
Secret values remain in SDK process memory and never enter Terraform or Git. Preparation
reuses tagged resources and secrets, rejects foreign resources, and does not automatically
repeat an ambiguous mutation or rotate an existing credential.

Terraform reads the external database and creates the application stack. The Express
cluster and three secrets therefore require separate reviewed cleanup. Lambda uses the
shared concurrency pool because the project currently has only 10 slots; SQS processing
is capped at 2. GitHub OIDC is optional and off by default due to the managed-policy denial.
First deployment is from the local `portfolio` login. See `AWS_RUNBOOK.md` for verification,
release and cleanup procedures. No Paid/Advanced upgrade is automated.

The owner approved the Stockholm AWS test deployment on 2026-11-15 while remaining on
the active Free Plan and retaining bounded OpenAI use. The budget recipient is stored
only in ignored operator configuration. No Paid/Advanced upgrade, DNS changes, GitHub
publication or Marketplace submission is authorized. AWS budget alerts are not a hard cap.
After the deployment tests, the owner explicitly chose to keep the AWS environment
reachable for personal testing. Cleanup requires a later instruction; no automatic
destructive cleanup or plan upgrade is scheduled.
The first AWS acceptance observed zero-ACU pause and a 23.92-second browser startup
from that pause. The UI handled transient 503 responses before creating the session;
no AI request was part of that resume test. Use CloudWatch metrics to measure idle
capacity, because direct instance-log diagnostics can interfere with auto-pause.

## GPU benchmarks

The GPU benchmark extension shares the existing FastAPI, React, SQS, Aurora/Data API,
S3 and Secrets Manager boundaries. Vast.ai supplies single on-demand GPUs; AWS remains
in Stockholm. Paid GPU execution defaults to disabled. The agreed application limits
are EUR 10/month, EUR 1/lease, 30 minutes, 5 minutes idle and one active lease globally.
Public users select bundled synthetic prompts; arbitrary prompts require a short-lived
operator session. GPU accounting is separate from OpenAI and uses Decimal throughout.

GPU leases, requests and the budget ledger outlive demo sessions. Session deletion
must scrub private prompt/output payloads and request termination before detaching the
lease. A global SQL admission lock plus a partial unique index protects concurrency;
idempotency keys bind to request fingerprints. A full session allowance is reserved
before renting. Unknown provider outcomes never release reservations or repeat creation.
SDK 1.11.0 uses retry as an attempt count; the adapter additionally enforces exactly one
HTTP attempt, disables redirects and decodes provider prices directly to Decimal.

The runner has no inbound ports and no provider/AWS credentials. A per-lease HMAC
capability authenticates outbound HTTPS callbacks on narrowly exempted machine routes;
browser routes retain Origin/CSRF/session checks. SQS dispatch uses the existing queue
with a separate benchmark message discriminator. A durable claim precedes both rental
creation and inference delivery. A lost inference claim is never automatically replayed.
Sequence-numbered output snapshots and final reports are idempotent. Progress delivery
runs off the inference-reading thread so AWS latency does not distort runner timing.

The separately pinned GPU image is the official amd64 Python 3.14 slim image, with
NVIDIA compute/utility capabilities requested from Vast. Python 3.14 supplies Zstandard
decoding for the checksum-pinned Ollama archive. The AWS backend remains on Python 3.12.
A small deterministic ZIP packages the standalone runner, bootstrap and manifest into
the existing private S3 bucket; short-lived presigned downloads convey no AWS identity.
The two Gemma model manifests are digest-pinned, checked before downloading and again
after pulling. The GPU bootstrap itself still requires live hardware acceptance.

A separate Lambda entrypoint in the same application image runs through EventBridge
Scheduler every minute. Its S3 control records recover SQL-to-SQS dispatch gaps; signed
provider labels recover creation responses lost before instance IDs were saved. It can
destroy owned rentals even when SQL is down, never touches unsigned/foreign instances,
and performs no SQL access when both provider inventory and control prefix are empty.
New admissions require a recent healthy S3 watchdog heartbeat. Turning admission off
does not stop cleanup. Confirmed deletion requires three provider inventory observations
at least 55 seconds apart. Unknown creation retains the reservation through the hard
lease deadline. Delete errors retain ownership and prevent further admission.

The current ledger conservatively debits the full EUR 1 reservation after any attempted
rental until external billing reconciliation is introduced. Planned cost is displayed
separately, never described as the provider's actual invoice. Failures before an attempt
release the reservation. Leases end at the earlier of 30 minutes and the Berlin month
boundary; insufficient pre-boundary startup time rejects admission. Provider outages may
delay destruction: neither the application budget nor AWS alarms promise an absolute
provider-side spending cap. GPU activation requires deployed HTTPS and real private S3;
local Moto endpoints are deliberately ineligible for paid rental.

Public standard reports persist anonymously in Aurora and under benchmarks/reports/,
outside the sessions/ object lifecycle. Raw private prompts and responses remain only
in session-scoped SQL and are scrubbed during explicit/expired-session deletion. The
public protocol uses five fixtures, one excluded warmup, three sequential repetitions,
4096 context tokens, a 512 output-token ceiling and temperature zero. Cache counters are
reported when supplied, otherwise null; cache is not claimed to be disabled. Download
and initial model-load times are separate from local runner TTFT/generation timing.

Comparison/workspace queries return bounded summaries rather than arrays of full sample
outputs, avoiding the Data API response-size ceiling. Individual public/private report
routes enforce their respective visibility before loading one bounded detailed report.
Vast inventory uses the SDK's paginated v1 method with a minimal field selection: the
convenience inventory method performs float arithmetic on timestamps and is incompatible
with Decimal-preserving JSON decoding. Provider inventory never fetches runner environment
values. The dashboard renders model output as plain text.
