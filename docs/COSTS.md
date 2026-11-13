# Cost assumptions — reviewed 2026-11-13

No AWS account has been provisioned for ReconFlow. The following is a planning estimate,
not an AWS quote or a guaranteed monthly cap. USD amounts exclude tax, currency changes,
free-tier allowances and account credits. OpenAI billing is separate.

## AWS demo

Architecture: one Aurora PostgreSQL Serverless v2 writer, minimum 0 / maximum 1 ACU,
auto-pause after 300 seconds; Lambda outside the database VPC; no NAT gateway, load
balancer, always-on ECS service or provisioned concurrency. CloudFront serves static
assets; the first screen does not query the database.

Frankfurt planning inputs taken from the [AWS RDS regional price catalog](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/eu-central-1/index.json):
Aurora Standard serverless capacity USD 0.14/ACU-hour, storage USD 0.119/GB-month,
I/O USD 0.22/million requests. Re-fetch the current catalog before applying.

Assume each isolated visitor keeps the database active for five minutes, followed by
five idle minutes before pause. Use the full 1 ACU ceiling for these ten minutes:

| Isolated visits/month | Active hours | Estimated database compute |
| --- | ---: | ---: |
| 0 | 0 | USD 0.00 |
| 20 | 3.33 | USD 0.47 |
| 100 | 16.67 | USD 2.33 |
| Never pauses, 730 hours | 730 | USD 102.20 |

Storage remains billable while paused. A 10 GB storage assumption adds USD 1.19/month.
Three Secrets Manager secrets at USD 0.40 each add approximately USD 1.20/month,
plus API calls. Two standard alarms add approximately USD 0.20/month. Budget further
usage for S3, state versions, ECR, CloudFront transfer, Lambda, HTTP API, SQS, logs and I/O.
For a very quiet demo a provisional **USD 3–6/month AWS allowance** is plausible under
these assumptions; it is not a promise. More traffic, abusive callers or activity that
prevents pause can cost substantially more. Account costs unrelated to ReconFlow are excluded.

Official references: [Aurora auto-pause](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html),
[Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/),
[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/),
[AWS Pricing Calculator](https://calculator.aws/).

Terraform includes a USD 15 **account-wide** monthly awareness budget, alerting at 80%.
It intentionally includes all account usage so existing unrelated services also appear.
This sends notifications only; it does not stop charges. API throttles and maximum ACUs
limit load but do not impose a fixed invoice maximum.

## OpenAI

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

The ledger covers ReconFlow only. It cannot stop other applications using the same
OpenAI key, and deleting the database resets its local accounting. Use a dedicated
provider project for the public demo and inspect actual billing after deployment.
