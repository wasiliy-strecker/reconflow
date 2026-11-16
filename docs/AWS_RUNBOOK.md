# AWS deployment and operations

Status: owner-approved Stockholm Free Plan test deployment completed on 2026-11-15.
Test URL: **https://d33v3exmdsu4yz.cloudfront.net**. Real browser workflows, OpenAI
and access-isolation checks passed. Zero-ACU pause and browser resume were verified;
initial service/diagnostic activity delayed the first pause. GitHub publication,
Paid/Advanced upgrades, DNS changes and Marketplace submission remain outside scope.

## Selected project and verified access — 2026-11-15

- New AWS experience, selected portfolio project, selected Region **eu-north-1
  (Stockholm)**, local CLI profile **portfolio**. The profile is a reusable login
  label, not an application name.
- AWS CLI 2.40.3, Terraform 1.13.5, locked AWS provider 6.73.0. Browser login and STS
  succeeded. The post-deployment Free Plan query confirmed ACTIVE with positive credits.
  Exact credit balances and plan expiry are private operator information; query them
  before deployment rather than relying on a published snapshot.
- Aurora PostgreSQL 17.7 is available with zero-ACU support. Express does not accept
  an engine version pin: the current default is **17.9**, also supporting zero ACUs.
  The preparation command resolves and checks the current default on every new setup.
- Lambda has 10 total/unreserved concurrent executions and three active functions.
  Application functions therefore use the shared pool; SQS maximum concurrency is 2.
  Reserving five slots would fail because AWS requires 100 slots to remain unreserved.
- Listing IAM OIDC providers was denied by a managed SCP, including at the global
  endpoint. GitHub OIDC resources are disabled by default. No policies were changed.
- The initial inventory was empty. ReconFlow now owns one Express cluster/writer,
  three secrets, the six bootstrap resources and 34 application Terraform resources.

## Deployment verification — 2026-11-15

- Distribution `<distribution-id>`, all regional application resources in Stockholm.
  Obtain the actual distribution ID from `terraform output -raw distribution_id`.
  Runtime source revision `4cd28b39a6f8081d29d82c9d029ce106508d835e`; later commits
  changed operator tooling, infrastructure and documentation only. Immutable image:
  `sha256:8c1cde0c613604fcfbb7537598c7636294679c0d67ce155ccd7438f871873039`.
  The recorded runtime revision predates the publication privacy rewrite; its original
  ECR tag and immutable digest remain unchanged even though public Git commit IDs differ.
- Migration Lambda invoked twice successfully: `{"ok":true}`, 4.72 s then 0.41 s
  measured from the operator. A subsequent real Terraform plan reports no changes.
- Public browser flow passed without AI (25.2 s), then with one extraction and one
  suggestion (36.7 s), including confirmation, reconciliation, manual assignment,
  CSV import, XLSX and mobile layout. No paid request was retried.
- Both real AI calls completed. Ledger: EUR 0.00040359 estimated token cost,
  zero outstanding reservations. Local and AWS budget ledgers remain independent.
- CloudWatch recorded a complete zero-ACU minute at 11:44 CET. A fresh browser at
  11:49 CET loaded all six invoices in 23.92 s after clicking Demo starten. Two
  temporary 503 responses were handled by the existing startup retry UI, followed
  by successful session creation and seed. No browser errors or paid calls occurred;
  the test session was deleted. This measures a short pause, not deep sleep over 24 h.
- Two isolated clients verified document/job/run/report isolation, secure cookies,
  Origin and CSRF checks, fixture enforcement, no-store API/original responses and
  blocked unauthenticated access to actual objects in both S3 buckets.
- All three Lambda functions are active; queues/DLQ are empty. The inspected Lambda
  logs contain no ERROR or timeout records. The USD 15 / 80-percent budget and the
  operator-selected email recipient are confirmed through the AWS API.
- Private deployment plans and acceptance receipts are under
  `artifacts/private/aws-deploy/` (ignored). Secret payloads and recipient email are
  not recorded in these committed documents. Do not delete ignored bootstrap state.
- The owner chose to keep this environment reachable for personal testing. Cleanup
  remains a separately requested operation.

Confirm the selected Region in **AWS Settings > View all projects > Overview >
Additional Info > Region**. Check plan/credit status in **AWS Settings > Billing**.

```bash
# Renew only when needed; complete the browser confirmation.
aws login --region eu-north-1 --profile portfolio
aws sts get-caller-identity --profile portfolio --region eu-north-1
uv run --frozen python scripts/prepare_aws_demo.py
```

The last command is **read-only by default**. It checks identity, active Free Plan,
positive USD credits, expiry, Lambda capacity, existing database ownership and engine
zero-ACU support. It neither reads the local OpenAI key nor creates resources. A
successful preflight does not prove all future create operations are allowed by SCPs.
Unexpected denial stops the deployment; it never triggers a plan upgrade.

Toolkit catalog access uses us-east-1 independently of the application's selected
Region. No AWS MCP tools were available in this session; verification used the AWS CLI
and official documentation. Earlier toolkit installation details remain in CHANGELOG.md.

## Free Plan database boundary

The [Aurora Free Plan](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-free-tier.html)
allows only Express clusters (up to 4 ACUs and 1 GB storage), not the previous
full-configuration VPC cluster. ReconFlow uses a single Express writer at **0–1 ACU**
and **300 seconds auto-pause**. No customer VPC, NAT gateway or additional writer is
created. Express supplies an internet gateway with IAM authentication for the admin.

Provider 6.73.0 has no Express creation field. `prepare_aws_demo.py --apply` owns the
Express cluster and its three secrets; Terraform reads the database through a data
source and owns the application resources. Do not import the Express cluster into
the previous full-configuration resource or assume `terraform destroy` removes it.

The script connects once using a short-lived IAM token and verified TLS, creates the
`reconflow_app` SQL login, and grants CONNECT/CREATE on database `reconflow` plus
USAGE/CREATE on schema `public`. This user owns migrations/application tables, without
administrator rights. Data API uses that user's secret, not the IAM-only admin.
See [Express limitations and Data API setup](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html).

Preparation uses fixed resource names and ownership tags. Repeating it reuses the
cluster and persisted secret values, including after partial failure. An existing
untagged resource is rejected. Existing passwords/keys are never silently rotated.
An ambiguous create request is not retried automatically; inspect the named resource
and rerun the complete preparation after its state is clear. There is no destructive
rollback or upgrade fallback.

## First deployment — only after deployment approval

Prerequisites: authenticated CLI profile, Python/uv dependencies, Docker Buildx,
Terraform, and the private `.env` containing the existing OpenAI key. Read COSTS.md.
The app's EUR 10 OpenAI budget stays enabled; AWS credits do not pay OpenAI bills.

### 1. Recheck and prepare database/secrets

```bash
export AWS_PROFILE=portfolio
export AWS_REGION=eu-north-1
uv run --frozen python scripts/prepare_aws_demo.py
RF_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
# Review the project ID and Free Plan output before this mutating command.
uv run --frozen python scripts/prepare_aws_demo.py --apply \
  --expected-account-id "$RF_ACCOUNT_ID"
```

The preparation creates `reconflow` Express, then creates the SQL database through
the IAM-authenticated `postgres` connection (Express rejects `DatabaseName` at cluster
creation). It enables Data API, verifies `SELECT 1` with the application SQL user, and
creates these secrets:

| Secret | Stored format |
| --- | --- |
| `reconflow/db` | JSON with SQL `username` and generated `password` |
| `reconflow/session` | Newly generated plaintext session secret |
| `reconflow/openai` | Existing local OpenAI key as plaintext |

Secret payloads remain in SDK process memory and kept out of command arguments, logs, Git,
Terraform variables and state. Output contains only identifiers/ARNs. Existing cloud
secrets are reused; updating `.env` does not rotate them. Do not redirect diagnostic
wire logs or database queries containing passwords into release artifacts.

### 2. Bootstrap state and ECR

Terraform 1.13.5's embedded S3-backend SDK does not understand this profile's
`aws login` credentials, although the current provider does. Export the short-lived
credentials into the operator shell before Terraform commands; never print, log or
save the export. Repeat after expiration. The deployment used the equivalent SDK
in-memory environment handoff to Terraform subprocesses.

```bash
eval "$(aws configure export-credentials --profile portfolio --format env)"
terraform -chdir=infra/bootstrap init -input=false -lockfile=readonly
terraform -chdir=infra/bootstrap plan -out=bootstrap.plan
# Inspect the saved plan before applying it.
terraform -chdir=infra/bootstrap apply bootstrap.plan
RF_REPOSITORY=$(terraform -chdir=infra/bootstrap output -raw repository_url)
RF_REGISTRY=${RF_REPOSITORY%/*}
RF_REVISION=$(git rev-parse HEAD)
aws ecr get-login-password --region eu-north-1 | docker login --username AWS --password-stdin "$RF_REGISTRY"
docker buildx build --platform linux/amd64 --provenance=false \
  -f backend/Dockerfile -t "$RF_REPOSITORY:$RF_REVISION" --push .
aws ecr describe-images --repository-name reconflow \
  --image-ids "imageTag=$RF_REVISION" --query 'imageDetails[0].imageDigest' --output text
```

Bootstrap creates ECR and a private, encrypted, versioned state bucket. Preserve its
ignored local state securely. Immutable image tags cannot be overwritten; a failed
release resumes using its existing digest or a newly reviewed commit.

### 3. Review and apply the application

Copy `infra/app/terraform.tfvars.example` to ignored `infra/app/terraform.tfvars`.
Set the image URI with the returned `@sha256:` digest, the three returned secret ARNs,
and the deliberately chosen budget recipient. Keep `enable_github_deploy = false`.
No secret values belong in this file. Terraform rejects other regions and image/secret
identifiers belonging to a different project.

```bash
RF_STATE_BUCKET=$(terraform -chdir=infra/bootstrap output -raw state_bucket)
terraform -chdir=infra/app init \
  -backend-config="bucket=$RF_STATE_BUCKET" \
  -backend-config='key=reconflow/app.tfstate' \
  -backend-config='region=eu-north-1' \
  -backend-config='encrypt=true' -backend-config='use_lockfile=true'
terraform -chdir=infra/app plan -out=app.plan
# Inspect the complete plan before applying it.
terraform -chdir=infra/app apply app.plan
aws lambda invoke --function-name reconflow-migrate \
  --cli-read-timeout 210 /tmp/reconflow-migration.json
```

Check invocation metadata for `FunctionError` and payload for `{"ok":true}`. A zero
CLI exit code alone is insufficient. The checksum-protected transactional migrations
can be repeated after a clearly failed invocation; do not blindly retry paid AI jobs.

### 4. Publish frontend and test

```bash
npm --prefix frontend ci
npm --prefix frontend run build
RF_WEB_BUCKET=$(terraform -chdir=infra/app output -raw web_bucket)
RF_DISTRIBUTION=$(terraform -chdir=infra/app output -raw distribution_id)
RF_DEMO_URL=$(terraform -chdir=infra/app output -raw demo_url)
aws s3 sync frontend/dist/ "s3://$RF_WEB_BUCKET/" --exclude index.html \
  --cache-control 'public,max-age=31536000,immutable'
aws s3 cp frontend/dist/index.html "s3://$RF_WEB_BUCKET/index.html" --cache-control 'no-cache'
aws cloudfront create-invalidation --distribution-id "$RF_DISTRIBUTION" --paths '/' '/index.html'
curl --fail "$RF_DEMO_URL/health"
DEMO_URL="$RF_DEMO_URL" npm --prefix frontend run test:e2e
```

The CloudFront HTTPS address is publicly reachable, with fixture-only demo admission
and isolated expiring sessions. No custom domain is required. The first screen and
`/health` do not query SQL. Keep old hashed assets for rollback. No keep-alive monitor
should query the database, because it prevents auto-pause.

## Acceptance before treating AWS as validated

- Data API: migrations twice, seed, one bounded real OpenAI extraction, confirmation,
  reconciliation, manual assignment and XLSX. Tests with mocked AWS are not service parity.
- Two browsers cannot access each other's documents, jobs or reports. Direct S3 access
  is denied; API responses and originals are not cached by CloudFront.
- Fixture-only upload enforcement, CSRF, API throttling, SQS limit and AI reservations
  hold. Duplicate SQS messages and unknown AI outcomes do not automatically repeat a call.
- Let the database idle over five minutes, observe zero ACUs and measure resume behavior.
  Observe only CloudWatch capacity metrics and RDS events during this interval. Do not
  list/download instance log files: those administrative operations can wake a paused
  instance or delay the next pause. After an administrative wake-up, AWS waits at least
  20 minutes before another pause. See [Aurora pause/resume behavior](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html).
  If resumption exceeds the API deadline, inspect the failed request before retrying;
  do not advertise the demo until resume behavior is acceptable.
- Inspect actual credit use, Lambda errors and DLQ metrics. The two CloudWatch alarms
  currently have no notification actions; inspect them in the console. AWS Budgets
  email notifications are separate and do not stop usage.

## Later releases and optional GitHub delivery

For a local release: push a new immutable image, record current image URIs for API,
worker and migrate, update/wait for migrate, invoke and verify the migration, then
update/wait for worker and API. Upload assets before index.html as above. The exact
release sequence is also in `.github/workflows/deploy.yml`. Terraform deliberately
ignores image_uri after initial creation; it must not revert application releases.
Migrations must remain backwards compatible with the previous image.

GitHub delivery requires separately approved publication and working project OIDC
permissions. Then enable `enable_github_deploy`, reuse an existing provider if
appropriate, and create protected environment `aws-demo` with required reviewers and
main-branch restriction. Set `DEPLOY_ROLE_ARN`, `WEB_BUCKET`, `DISTRIBUTION_ID`, `DEMO_URL`.
The manual workflow accepts only a commit with successful push CI. No Paid/Advanced
upgrade is an implicit prerequisite or automatic workaround for an IAM denial.

## Recovery and explicitly approved shutdown

For rollback, restore recorded API/worker image digests and the previous version of
index.html, then invalidate CloudFront. SQL migrations are forward-only; restore a
snapshot into a new reviewed cluster instead of overwriting the current database.

The Express cluster and **all three preparation secrets are outside Terraform state**.
To stop all AWS usage, separately approve and inventory these actions:

1. Drain/stop job processing, retain the chosen export/snapshot, then review the app
   destroy plan. Empty only the intended buckets when explicitly approved.
2. For `reconflow` Express, explicitly disable deletion protection, delete the writer,
   then delete the cluster with a unique final snapshot identifier when retention is
   requested. Do not omit database cleanup after destroying the Terraform app.
3. Delete the three named secrets through their recovery windows when approved.
4. Remove intended ECR images/repository and bootstrap state bucket only after state
   and recovery needs are resolved. Review retained snapshots, S3 versions, secrets
   and images: they can still consume credits after application shutdown.

There is no automatic destructive cleanup. Ask whether to keep or remove the test
resources after the AWS test. Before Free Plan expiry/credit exhaustion, export any
wanted data while access still works; no Paid or Advanced upgrade is automated.

Real customer use needs stronger authentication, separate migration/runtime SQL roles,
retention policies, abuse controls and a restore rehearsal. This remains a portfolio demo.
