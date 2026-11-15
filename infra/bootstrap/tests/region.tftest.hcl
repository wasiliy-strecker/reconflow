mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
}

run "stockholm" {
  command = plan
  assert {
    condition     = aws_s3_bucket.state.bucket == "reconflow-state-123456789012-eu-north-1"
    error_message = "State must stay in Stockholm."
  }
}

run "reject_frankfurt" {
  command = plan
  variables { region = "eu-central-1" }
  expect_failures = [var.region]
}
