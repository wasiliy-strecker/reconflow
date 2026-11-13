terraform {
  backend "s3" {}
  required_version = ">= 1.13, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
variable "region" { default = "eu-central-1" }
variable "name" { default = "reconflow" }
variable "image_uri" {
  type        = string
  description = "ECR image URI pinned with @sha256: digest, built for linux/amd64."
  validation {
    condition     = can(regex("@sha256:[a-f0-9]{64}$", var.image_uri))
    error_message = "Use an immutable ECR digest, not a tag."
  }
}
variable "engine_version" { default = "17.7" }
variable "openai_secret_arn" { type = string }
variable "session_secret_arn" { type = string }
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
data "aws_availability_zones" "available" { state = "available" }
locals {
  account = data.aws_caller_identity.current.account_id
  functions = {
    api     = { handler = "reconflow.api.handler", timeout = 25, memory = 512, concurrency = 2 }
    worker  = { handler = "reconflow.worker.handler", timeout = 180, memory = 1024, concurrency = 2 }
    migrate = { handler = "reconflow.migrate.handler", timeout = 180, memory = 512, concurrency = 1 }
  }
}
