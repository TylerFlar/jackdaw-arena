output "name_servers" {
  description = "Delegate var.domain to these: one NS record each, at the parent domain's DNS host."
  value       = aws_route53_zone.arena.name_servers
}

output "site_url" {
  description = "The site's address."
  value       = local.site_url
}

output "function_url" {
  description = "The API's Function URL. Called directly (not through CloudFront) it answers 403."
  value       = aws_lambda_function_url.api.function_url
}

output "ecr_repository_url" {
  description = "Where deploys push the API image."
  value       = aws_ecr_repository.api.repository_url
}

output "dsql_endpoint" {
  description = "The arena cluster's endpoint (IAM auth only)."
  value       = local.dsql_endpoint
}

output "dsql_ci_endpoint" {
  description = "The CI scratch cluster's endpoint (IAM auth only)."
  value       = local.dsql_ci_endpoint
}

output "github_variables" {
  description = "Repository variables the workflows read (Settings > Secrets and variables > Actions > Variables). None of them is secret."
  value = {
    AWS_REGION          = var.region
    AWS_DEPLOY_ROLE_ARN = aws_iam_role.deploy.arn
    AWS_CI_ROLE_ARN     = aws_iam_role.ci.arn
    ECR_REPOSITORY      = aws_ecr_repository.api.repository_url
    API_FUNCTION        = aws_lambda_function.api.function_name
    TASKS_FUNCTION      = aws_lambda_function.tasks.function_name
    WEB_BUCKET          = aws_s3_bucket.web.bucket
    DISTRIBUTION_ID     = aws_cloudfront_distribution.site.id
    SITE_URL            = local.site_url
    DSQL_CI_ENDPOINT    = local.dsql_ci_endpoint
  }
}
