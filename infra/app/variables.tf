terraform {
  backend "s3" {}
  required_version = ">= 1.13, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
variable "region" {
  type    = string
  default = "eu-north-1"
  validation {
    condition     = var.region == "eu-north-1"
    error_message = "ReconFlow resources must use the project's selected Region eu-north-1."
  }
}
variable "name" {
  default = "reconflow"
  validation {
    condition     = var.name == "reconflow"
    error_message = "This test stack binds the explicitly prepared reconflow database and secrets."
  }
}
variable "image_uri" {
  type        = string
  description = "ECR image URI pinned with @sha256: digest, built for linux/amd64."
  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.eu-north-1\\.amazonaws\\.com/reconflow@sha256:[a-f0-9]{64}$", var.image_uri))
    error_message = "Use a Stockholm reconflow ECR image pinned to an immutable sha256 digest."
  }
}
variable "database_secret_arn" {
  type        = string
  description = "Secrets Manager ARN for the SQL user prepared by scripts/prepare_aws_demo.py. No secret value."
  validation {
    condition     = can(regex("^arn:aws:secretsmanager:eu-north-1:[0-9]{12}:secret:reconflow/db-", var.database_secret_arn))
    error_message = "Use the reconflow/db secret ARN in Stockholm."
  }
}
variable "openai_secret_arn" {
  type = string
  validation {
    condition     = can(regex("^arn:aws:secretsmanager:eu-north-1:[0-9]{12}:secret:reconflow/openai-", var.openai_secret_arn))
    error_message = "Use the reconflow/openai secret ARN in Stockholm."
  }
}
variable "session_secret_arn" {
  type = string
  validation {
    condition     = can(regex("^arn:aws:secretsmanager:eu-north-1:[0-9]{12}:secret:reconflow/session-", var.session_secret_arn))
    error_message = "Use the reconflow/session secret ARN in Stockholm."
  }
}
variable "enable_github_deploy" {
  type        = bool
  default     = false
  description = "Opt in only after GitHub publication and project OIDC permissions are separately approved."
}
variable "github_repository" { default = "wasiliy-strecker/reconflow" }
variable "existing_github_oidc_arn" {
  type    = string
  default = ""
}
variable "budget_email" {
  type        = string
  description = "Recipient chosen by the operator when deployment is authorized."
}
variable "monthly_aws_alert_usd" { default = 15 }
provider "aws" {
  region = var.region
  default_tags { tags = { Project = var.name, Environment = "portfolio-demo" } }
}
data "aws_caller_identity" "current" {}
locals {
  account = data.aws_caller_identity.current.account_id
  functions = {
    api     = { handler = "reconflow.api.handler", timeout = 25, memory = 512 }
    worker  = { handler = "reconflow.worker.handler", timeout = 180, memory = 1024 }
    migrate = { handler = "reconflow.migrate.handler", timeout = 180, memory = 512 }
  }
}
