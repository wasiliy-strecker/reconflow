# Remains active when enable_gpu_benchmarks=false: disabling admission must never
# disable cleanup of existing external rentals. Same image and existing resources.
resource "aws_iam_role" "gpu_schedule" {
  name = "${var.name}-gpu-schedule"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnEquals = { "aws:SourceArn" = "arn:aws:scheduler:${var.region}:${local.account}:schedule-group/default" } }
  }] })
}
resource "aws_iam_role_policy" "gpu_schedule" {
  role = aws_iam_role.gpu_schedule.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.functions["gpu_watchdog"].arn },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.dead.arn }
  ] })
}
resource "aws_scheduler_schedule" "gpu_watchdog" {
  name                = "${var.name}-gpu-watchdog"
  schedule_expression = "rate(1 minute)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.functions["gpu_watchdog"].arn
    role_arn = aws_iam_role.gpu_schedule.arn
    input    = "{}"
    retry_policy {
      maximum_event_age_in_seconds = 120
      maximum_retry_attempts       = 1
    }
    dead_letter_config { arn = aws_sqs_queue.dead.arn }
  }
  depends_on = [aws_iam_role_policy.gpu_schedule]
}
resource "aws_cloudwatch_metric_alarm" "gpu_watchdog" {
  alarm_name          = "${var.name}-gpu-cleanup-failed"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.functions["gpu_watchdog"].function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "GPU cleanup failed. New leases fail closed when the S3 watchdog heartbeat expires. Inspect Vast instances immediately."
}
