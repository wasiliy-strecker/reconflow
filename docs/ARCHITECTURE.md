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
PostgreSQL Serverless v2 via Data API. AWS networking does not require a NAT gateway.
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

The implementation request authorizes local development and bounded OpenAI evaluation.
It does not yet authorize paid AWS provisioning, DNS changes, GitHub publication or Marketplace
submission. Prepare and validate these artifacts locally. Obtain approval only after the
release and its cost estimate are concrete. AWS budget alerts are not a hard billing cap.
