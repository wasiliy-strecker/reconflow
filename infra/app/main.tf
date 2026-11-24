# Express creation is owned by the explicit operator preparation script.
# Terraform must never replace it with a full-configuration (Paid Plan) cluster.
data "aws_rds_cluster" "db" {
  cluster_identifier = var.name
  lifecycle {
    postcondition {
      condition     = self.engine == "aurora-postgresql" && self.iam_database_authentication_enabled && self.deletion_protection && lookup(self.tags, "ManagedBy", "") == "reconflow-free-demo"
      error_message = "Use the protected Aurora PostgreSQL Express cluster created by prepare_aws_demo.py."
    }
  }
}
resource "aws_s3_bucket" "buckets" {
  for_each = toset(["web", "documents"])
  bucket   = "${var.name}-${each.key}-${local.account}-${var.region}"
}
resource "aws_s3_bucket_public_access_block" "private" {
  for_each                = aws_s3_bucket.buckets
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "encrypted" {
  for_each = aws_s3_bucket.buckets
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.buckets["web"].id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.buckets["documents"].id
  rule {
    id     = "expire-demo-documents"
    status = "Enabled"
    filter { prefix = "sessions/" }
    expiration { days = 1 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
resource "aws_sqs_queue" "dead" {
  name                      = "${var.name}-dead"
  message_retention_seconds = 345600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "jobs" {
  name                       = "${var.name}-jobs"
  visibility_timeout_seconds = 1080
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dead.arn, maxReceiveCount = 3 })
}
resource "aws_iam_role" "runtime" {
  for_each = local.functions
  name     = "${var.name}-${each.key}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_iam_role_policy" "runtime" {
  for_each = local.functions
  role     = aws_iam_role.runtime[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.functions[each.key].arn}:*" },
    { Effect = "Allow", Action = ["rds-data:ExecuteStatement", "rds-data:BeginTransaction", "rds-data:CommitTransaction", "rds-data:RollbackTransaction"], Resource = data.aws_rds_cluster.db.arn },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.database_secret_arn, var.openai_secret_arn, var.session_secret_arn] }
    ], each.key == "migrate" ? [] : [
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.buckets["documents"].arn}/sessions/*" },
    { Effect = "Allow", Action = each.key == "api" ? ["sqs:SendMessage"] : ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.jobs.arn }
  ]) })
}
resource "aws_cloudwatch_log_group" "functions" {
  for_each          = local.functions
  name              = "/aws/lambda/${var.name}-${each.key}"
  retention_in_days = 7
}
resource "aws_lambda_function" "functions" {
  for_each      = local.functions
  function_name = "${var.name}-${each.key}"
  role          = aws_iam_role.runtime[each.key].arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["x86_64"]
  timeout       = each.value.timeout
  memory_size   = each.value.memory
  # The Free Plan currently has a total concurrency quota of 10.
  # Reserving capacity requires leaving 100 unreserved; use the shared pool.
  reserved_concurrent_executions = -1
  image_config { command = [each.value.handler] }
  environment {
    variables = {
      APP_MODE                  = "demo"
      DB_DRIVER                 = "data-api"
      DB_CLUSTER_ARN            = data.aws_rds_cluster.db.arn
      DB_SECRET_ARN             = var.database_secret_arn
      SESSION_SECRET_ARN        = var.session_secret_arn
      OPENAI_SECRET_ARN         = var.openai_secret_arn
      OPENAI_MODEL              = "gpt-6-luna"
      AI_MONTHLY_BUDGET_EUR     = "10"
      AI_INPUT_USD_PER_MILLION  = "0.10"
      AI_OUTPUT_USD_PER_MILLION = "0.50"
      AI_USD_TO_EUR             = "1.10"
      AI_CONTEXT_TOKEN_CEILING  = "1050000"
      S3_BUCKET                 = aws_s3_bucket.buckets["documents"].id
      SQS_QUEUE_URL             = aws_sqs_queue.jobs.url
      PUBLIC_ORIGIN             = "https://${aws_cloudfront_distribution.app.domain_name}"
      MAX_DOCUMENTS             = "6"
      MAX_CSV_ROWS              = "100"
      MAX_JOBS_PER_SESSION      = "20"
      MAX_SESSIONS_PER_HOUR     = "30"
    }
  }
  depends_on = [aws_iam_role_policy.runtime]
  lifecycle {
    ignore_changes = [image_uri]
    precondition {
      condition = startswith(var.image_uri, "${local.account}.dkr.ecr.${var.region}.amazonaws.com/") && alltrue([
        for arn in [var.database_secret_arn, var.openai_secret_arn, var.session_secret_arn] :
        startswith(arn, "arn:aws:secretsmanager:${var.region}:${local.account}:secret:")
      ])
      error_message = "The image and all secrets must belong to the authenticated project in Stockholm."
    }
  }
}
resource "aws_lambda_event_source_mapping" "jobs" {
  event_source_arn        = aws_sqs_queue.jobs.arn
  function_name           = aws_lambda_function.functions["worker"].arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  scaling_config { maximum_concurrency = 2 }
}
resource "aws_apigatewayv2_api" "api" {
  name          = var.name
  protocol_type = "HTTP"
}
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }
}
resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.functions["api"].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}
resource "aws_apigatewayv2_route" "all" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}
resource "aws_lambda_permission" "gateway" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.functions["api"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
