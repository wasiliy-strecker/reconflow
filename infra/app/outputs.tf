output "demo_url" { value = "https://${aws_cloudfront_distribution.app.domain_name}" }
output "web_bucket" { value = aws_s3_bucket.buckets["web"].id }
output "distribution_id" { value = aws_cloudfront_distribution.app.id }
output "deploy_role_arn" { value = aws_iam_role.deploy.arn }
output "database_cluster_arn" { value = aws_rds_cluster.db.arn }
output "functions" { value = { for key, fn in aws_lambda_function.functions : key => fn.function_name } }
