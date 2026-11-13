terraform {
  required_version = ">= 1.13, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
variable "region" { default = "eu-central-1" }
provider "aws" { region = var.region }
data "aws_caller_identity" "current" {}
resource "aws_ecr_repository" "app" {
  name                 = "reconflow"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_ecr_repository_policy" "lambda" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "lambda.amazonaws.com" },
    Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
    Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } }
  }] })
}
output "repository_url" { value = aws_ecr_repository.app.repository_url }
resource "aws_s3_bucket" "state" {
  bucket = "reconflow-state-${data.aws_caller_identity.current.account_id}-${var.region}"
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
output "state_bucket" { value = aws_s3_bucket.state.id }
