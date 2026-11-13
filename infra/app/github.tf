resource "aws_iam_openid_connect_provider" "github" {
  count          = var.existing_github_oidc_arn == "" ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
resource "aws_iam_role" "deploy" {
  name = "${var.name}-github-deploy"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity",
    Principal = { Federated = var.existing_github_oidc_arn != "" ? var.existing_github_oidc_arn : aws_iam_openid_connect_provider.github[0].arn },
    Condition = { StringEquals = {
      "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:aws-demo"
    } }
  }] })
}
resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = "arn:aws:ecr:${var.region}:${local.account}:repository/${var.name}" },
    { Effect = "Allow", Action = ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"], Resource = [for fn in aws_lambda_function.functions : fn.arn] },
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.functions["migrate"].arn },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.buckets["web"].arn },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.buckets["web"].arn}/*" },
    { Effect = "Allow", Action = ["cloudfront:CreateInvalidation"], Resource = aws_cloudfront_distribution.app.arn }
  ] })
}
