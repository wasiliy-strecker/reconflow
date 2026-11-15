# Cost assumptions — reviewed 2026-11-15

ReconFlow was deployed to the selected AWS project on 2026-11-15. The following is a planning estimate,
not an AWS quote or a guaranteed monthly cap. USD amounts exclude tax, currency changes,
free-tier allowances and account credits. OpenAI billing is separate.

## Free Plan and payment boundary

The owner wants AWS testing without an AWS payment while continuing to use paid OpenAI.
The authenticated post-deployment 2026-11-15 query confirmed ACTIVE FREE, positive credits remaining,
expiry <private-plan-expiry>. This is a snapshot, not an ongoing balance guarantee.
While the Free Plan is active, eligible usage consumes credits/free allowances rather
than producing a payable AWS bill. It ends at expiry or credit exhaustion. No upgrade
to Paid or Advanced is performed by the scripts. Check AWS Settings > Billing and
`aws freetier get-account-plan-state --profile portfolio --region eu-north-1` before deployment.
See the [AWS Free Tier FAQ](https://aws.amazon.com/free/free-tier-faqs/).

## AWS demo

Architecture: one Aurora PostgreSQL Serverless v2 Express writer, minimum 0 / maximum 1 ACU,
auto-pause after 300 seconds; Lambda with public service endpoints; no NAT gateway, load
balancer, always-on ECS service or provisioned concurrency. CloudFront serves static
assets; the first screen does not query the database.

Stockholm planning inputs (catalog publication 2026-11-13T21:52:33Z) taken from the [AWS RDS regional price catalog](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/eu-north-1/index.json):
Aurora Standard serverless capacity USD 0.14/ACU-hour, storage USD 0.11/GB-month,
I/O USD 0.21/million requests. Re-fetch the current catalog before applying.

Assume each isolated visitor keeps the database active for five minutes, followed by
five idle minutes before pause. Use the full 1 ACU ceiling for these ten minutes:

| Isolated visits/month | Active hours | Estimated database compute |
| --- | ---: | ---: |
| 0 | 0 | USD 0.00 |
| 20 | 3.33 | USD 0.47 |
| 100 | 16.67 | USD 2.33 |
| Never pauses, 730 hours | 730 | USD 102.20 |

Storage remains metered while paused. Express on the Free Plan permits up to 1 GB of
data; at the catalog storage rate that is USD 0.11/month. Until actual Express metering
is checked, the estimate conservatively reserves USD 1.10 for storage (10 GB equivalent).
This allowance does not increase the Free Plan's 1 GB storage limit.
Three Secrets Manager secrets (SQL login, session and OpenAI) at USD 0.40 each add approximately USD 1.20/month,
plus API calls. Two standard alarms add approximately USD 0.20/month. Budget further
usage for S3, state versions, ECR, CloudFront transfer, Lambda, HTTP API, SQS, logs and I/O.
For a very quiet demo a provisional **USD 3–7/month AWS credit-consumption allowance** is plausible under
these assumptions; it is not a promise. More traffic, abusive callers or activity that
prevents pause can cost substantially more. Account costs unrelated to ReconFlow are excluded.

Initial deployment observation: service/diagnostic activity and continuous backup lag
delayed the first pause. CloudWatch then confirmed a complete zero-ACU minute at
11:44 CET; the fresh browser's next Demo starten took 23.92 seconds. The quiet-demo
estimate remains workload-dependent, and maintenance can extend active periods.
Diagnostic instance-log reads can themselves delay pause; observe idle behavior with
CloudWatch metrics rather than repeatedly listing/downloading instance logs.

Official references: [Aurora auto-pause](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html),
[Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/),
[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/),
[AWS Pricing Calculator](https://calculator.aws/).

Terraform includes a USD 15 **account-wide** monthly awareness budget, alerting at 80%.
It intentionally includes all account usage so existing unrelated services also appear.
Credits and refunds are excluded from the calculation, so they do not conceal metered
usage. This alert amount is not the payable Free Plan invoice amount. See
[AWS Budgets cost types](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CostTypes.html).
This sends notifications only; it does not stop charges. API throttles and maximum ACUs
limit load but do not impose a fixed invoice maximum.

## OpenAI

OpenAI stays enabled locally and in the prepared AWS configuration. The existing local
key is reused only through the private preparation command, stored in Secrets Manager
for AWS, and never returned to the browser. OpenAI invoices are separate from AWS's
Free Plan. Local and AWS databases maintain independent application ledgers, so their
EUR 10 budgets do not constitute one shared provider-wide cap.

Default: `gpt-6-luna`, configured standard input USD 0.10/million tokens and output
USD 0.50/million tokens. Above 272,000 input tokens, reservation pricing doubles input
and multiplies output by 1.5. Configuration must be reviewed against the current
[model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
and [API pricing](https://developers.openai.com/api/docs/pricing) before launch.

The application uses a conservative USD-to-EUR multiplier of 1.10, not a live exchange
rate. Explicit cache mode without breakpoints avoids cache writes; the Standard tier
is selected explicitly. See [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).
It reserves against 1,050,000 input tokens plus 4,000 output tokens before each
call (EUR 0.2343), then replaces that reservation with observed token usage. Unknown
outcomes keep the reservation. The application's monthly budget is EUR 10 and is
serialized in PostgreSQL; repeated SQS delivery does not repeat a paid call.

Measured three-document smoke evaluation: **EUR 0.00135355 estimated token cost**,
using 6,070 input and 1,247 output tokens. See the saved usage report. Additional browser
checks made separate bounded calls. This is a model of token cost, not a downloaded
provider invoice. Real files and different models can cost more.

The first AWS browser acceptance on 2026-11-15 completed exactly two paid calls
(extraction and suggestion): 1,234 input / 487 output tokens, **EUR 0.00040359**
estimated cost. The AWS ledger has zero outstanding reservations after this test.

The ledger covers ReconFlow only. It cannot stop other applications using the same
OpenAI key, and deleting the database resets its local accounting. Use a dedicated
provider project for the public demo and inspect actual billing after deployment.
