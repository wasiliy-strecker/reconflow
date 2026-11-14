# AWS deployment and operations

Status: configuration validated locally, no AWS resources created. Use this runbook
only after the owner approves the reviewed deployment and cost assumptions.
There is no Marketplace submission or public GitHub repository yet.

## Selected AWS project and local access — 2026-11-14

The owner selected the new AWS experience and the existing project **the selected portfolio project**
in **eu-north-1 (Stockholm)**. The local AWS CLI profile is **portfolio**, a reusable
login label that can serve multiple applications in this AWS project. Separate AWS
projects can receive additional named profiles later.

AWS CLI 2.40.3 was installed for the local user with the official installer and GPG
signature verification. Browser login and STS identity verification succeeded. The
read-only plan query reported an active Free Plan with positive credits on this date;
this is a point-in-time observation, not a permanent balance or entitlement.

Renew local access through the browser when required:

```bash
aws login --region eu-north-1 --profile portfolio
aws sts get-caller-identity --profile portfolio
```

The Agent Toolkit uses its service endpoint in **us-east-1**, independently of the
project's resource region. Its Codex MCP configuration must set
`AWS_MCP_PROXY_PROFILES=portfolio`. Authentication remains in the local AWS login cache;
no access keys or session tokens belong in this repository.

The installer added 25 default skills under `~/.agents/skills/` and configured Codex
only. The authenticated toolkit catalog returned 123 available skills. A separate MCP
client successfully initialized the configured proxy and listed 8 tools, including
documentation search/read and skill retrieval. These counts describe this setup check.
Restart the Codex session so newly installed MCP tools and skills can be discovered
there. The user prefers short progress messages with questions only for material
ambiguity (`MEDIUM`).

The original `~/.codex/config.toml` was backed up privately before setup. A semantic
comparison confirmed that all pre-existing settings were preserved; only `aws-mcp`
was added, with the profile environment setting above. The configuration remains mode
0600. AWS setup guidance is recorded in `AGENTS.md`, with the upstream license and
notice retained under `docs/licenses/`.

**Deployment preparation below still targets Frankfurt. Do not execute it unchanged
for this Stockholm project.** Before a separately authorized deployment, review the
new-experience/Free-Plan service restrictions and adapt Terraform defaults, workflow
regions, credentials, cost assumptions and commands together. No upgrade to Paid or
Advanced and no application resource provisioning is part of the toolkit setup.

## Prerequisites and preflight

- AWS CLI v2, an AWS account, SSO/operator credentials, Terraform 1.13.5 and Docker Buildx.
- Region eu-central-1. Verify Aurora PostgreSQL 17.7 availability, Data API support,
  and zero-ACU auto-pause in this account/region before applying. Change the reviewed
  engine_version variable if the target region requires a different PostgreSQL 17 patch.
- At least five reservable Lambda concurrency slots. New accounts can have lower quotas.
- Read [COSTS.md](COSTS.md). AWS alarms are notifications, not spending shutdowns.
- Use a dedicated OpenAI project/key for independent provider-side budget visibility
  when publishing. Local reuse of the existing key is not isolation from other apps.

```bash
aws sso login --profile YOUR_PROFILE
export AWS_PROFILE=YOUR_PROFILE
aws sts get-caller-identity
aws rds describe-db-engine-versions --region eu-central-1 \
  --engine aurora-postgresql --engine-version 17.7 \
  --query 'DBEngineVersions[].{Version:EngineVersion,Serverless:ServerlessV2FeaturesSupport}'
aws lambda get-account-settings --region eu-central-1
```

Do not use continuous database health polling: it defeats auto-pause. `/health`
does not access PostgreSQL. API cold/resume behavior must be measured in AWS.

## First deployment

1. In `infra/bootstrap`, run `terraform init`, `terraform plan -out=bootstrap.plan`,
   inspect the plan, then `terraform apply bootstrap.plan`. This creates ECR and a private,
   encrypted, versioned state bucket. Preserve the ignored bootstrap state securely.
   Plan files can contain infrastructure details and belong outside Git.
2. Build and push the first image. The bootstrap repository uses immutable tags.

```bash
RF_REPOSITORY=$(terraform -chdir=infra/bootstrap output -raw repository_url)
RF_REGISTRY=${RF_REPOSITORY%/*}
RF_REVISION=$(git rev-parse HEAD)
aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin "$RF_REGISTRY"
docker buildx build --platform linux/amd64 --provenance=false \
  -f backend/Dockerfile -t "$RF_REPOSITORY:$RF_REVISION" --push .
aws ecr describe-images --region eu-central-1 --repository-name reconflow \
  --image-ids "imageTag=$RF_REVISION" --query 'imageDetails[0].imageDigest' --output text
```

3. Create two Secrets Manager **plaintext** secrets in the AWS console:
   `reconflow/openai` containing only the API key and `reconflow/session` containing
   a newly generated random secret of at least 32 characters. Do not use the console's
   default JSON key/value form. Do not put secret values in tfvars, CLI arguments or state.
4. Copy `infra/app/terraform.tfvars.example` to `infra/app/terraform.tfvars` and set
   image URI with `@sha256:...`, secret ARNs, your budget recipient, GitHub repository,
   and existing GitHub OIDC provider ARN if the account already has one. Values are ignored
   by Git. Choose the budget email deliberately; applying the configuration enables alerts.
5. Initialize remote state and review the complete app plan:

```bash
RF_STATE_BUCKET=$(terraform -chdir=infra/bootstrap output -raw state_bucket)
terraform -chdir=infra/app init \
  -backend-config="bucket=$RF_STATE_BUCKET" \
  -backend-config='key=reconflow/app.tfstate' \
  -backend-config='region=eu-central-1' \
  -backend-config='encrypt=true' -backend-config='use_lockfile=true'
terraform -chdir=infra/app plan -out=app.plan
# Apply only the reviewed plan after the authorized deployment decision.
terraform -chdir=infra/app apply app.plan
```

6. Run migrations explicitly. Aurora might first need to resume; repeat only a clearly
   failed migration invocation. Transactional migrations/checksums are safe to repeat.

```bash
aws lambda invoke --region eu-central-1 --function-name reconflow-migrate \
  --cli-read-timeout 210 /tmp/reconflow-migration.json
```

Check both the CLI invocation metadata for `FunctionError` and the payload for `{"ok":true}`.
A successful CLI process alone does not prove the migration succeeded.

7. Build the frontend (`cd frontend && npm ci && npm run build`). Use the deployment
   workflow's S3 commands to upload immutable assets first and `index.html` last.
   Keep old hashed assets for safe rollback. Invalidate `/` and `/index.html`.
8. Open `terraform -chdir=infra/app output -raw demo_url`. It is an HTTPS CloudFront
   address suitable for recruiters; a custom domain is optional and not provisioned.

## GitHub delivery

After separately authorized repository publication, create environment `aws-demo`
with required reviewers and deployment restricted to the main branch. The OIDC role
trusts only this repository/environment. Set environment variables from Terraform:
`DEPLOY_ROLE_ARN`, `WEB_BUCKET`, `DISTRIBUTION_ID`, `DEMO_URL`.

CI tests without paid AI calls. Manually start **Deploy AWS demo** only for a commit
whose push CI succeeded. The workflow builds linux/amd64, pushes an immutable image,
records previous images, migrates, updates worker/API, uploads the frontend and checks
health. The role cannot change infrastructure or read the OpenAI secret. It can update
the authorized functions, which makes protected review of deployment code essential.

Terraform ignores Lambda image_uri after initial creation so subsequent infrastructure
plans do not undo image releases. Code changes flow through the deployment workflow.
Migrations must remain backwards compatible with the previous release.

## AWS acceptance checks before advertising the demo

- Real Data API: migration twice, seed, extraction, confirmation, reconciliation and XLSX.
  Local tests prove the SQL contract, not AWS service parity or latency.
- Two independent browsers cannot read each other's invoices, jobs or reports.
- Direct S3 object access is denied. API responses and originals are not cached by CloudFront.
- Real OpenAI extraction and proposal each run once despite duplicate SQS delivery.
- Verify public fixture-only enforcement, API throttles, concurrency and the AI ledger.
- Let Aurora become idle for more than five minutes. Observe zero ACUs and measure the
  next request's resume/retry path. Confirm no monitoring tool keeps it awake.
- Check Lambda errors, DLQ alarm and account budget in the AWS console.
- Run the browser test against the actual HTTPS URL with `DEMO_URL=...`.
  No synthetic success claim should replace these deployment checks.

## Recovery and shutdown

CloudWatch logs retain seven days and omit invoice content, key values and raw prompts.
Job IDs correlate work; app failures also appear in the activity list. The DLQ receives
infrastructure failures after repeated delivery. Do not blindly replay unknown paid
operations: running claims retain budget and require an explicit user retry.

For an image rollback, use `previous-api.txt` and `previous-worker.txt` from the release
artifact with `aws lambda update-function-code`, then wait for both updates. Restore the
previous `index.html` S3 version and invalidate CloudFront. Old content-hashed assets remain.
Database migrations are forward-only; restore an RDS snapshot into a **new** cluster when
necessary, verify it, then update reviewed configuration. Avoid overwriting a healthy cluster.

Aurora deletion protection and a final snapshot are enabled. Removing the stack requires
an explicit reviewed shutdown: disable deletion protection, choose a unique final snapshot
identifier, drain jobs and empty only the intended S3 buckets when authorized. Retained
snapshots, secrets, ECR images and bootstrap storage can continue to incur charges.
There is no automatic destructive shutdown script.

The demo uses a scoped database per application with RDS-managed administrator credentials.
Separate migration and restricted database users, stronger abuse controls, production
authentication, retention policies and a restore rehearsal are prerequisites for real customers.
