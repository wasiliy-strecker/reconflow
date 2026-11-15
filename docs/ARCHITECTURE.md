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

The implementation request authorizes local development and bounded OpenAI evaluation.
It does not yet authorize paid AWS provisioning, DNS changes, GitHub publication or Marketplace
submission. Prepare and validate these artifacts locally. Obtain approval only after the
release and its cost estimate are concrete. AWS budget alerts are not a hard billing cap.
