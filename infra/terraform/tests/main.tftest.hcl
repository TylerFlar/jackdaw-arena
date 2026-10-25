# Offline tests of the stack's security and cost properties: `terraform test`. Both providers
# are mocked (nothing reaches AWS, no credentials needed), and every run is a plan: mocked
# values are known while planning, the way the real provider's are, so assertions can see them.

mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
  }
  mock_resource "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
  }
  mock_resource "aws_lambda_function_url" {
    defaults = { function_url = "https://abcdefghijklmnopqrstuvwxyz012345.lambda-url.us-west-2.on.aws/" }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = {
      id             = "E2EXAMPLE0ABCD"
      arn            = "arn:aws:cloudfront::123456789012:distribution/E2EXAMPLE0ABCD"
      domain_name    = "d111111abcdef8.cloudfront.net"
      hosted_zone_id = "Z2FDTNDATAQYW2"
    }
  }
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
      domain_validation_options = [{
        domain_name           = "arena.tylerflar.com"
        resource_record_name  = "_0123.arena.tylerflar.com."
        resource_record_type  = "CNAME"
        resource_record_value = "_4567.acm-validations.aws."
      }]
    }
  }
  mock_resource "aws_dsql_cluster" {
    defaults = { identifier = "abcdefghijklmnopqrstuvwxyz", arn = "arn:aws:dsql:us-west-2:123456789012:cluster/abcdefghijklmnopqrstuvwxyz" }
  }
  # override_during reaches only types with a mock block: the rest would stay unknown.
  mock_resource "aws_acm_certificate_validation" {}
  mock_resource "aws_backup_plan" {}
  mock_resource "aws_backup_selection" {}
  mock_resource "aws_backup_vault" {}
  mock_resource "aws_budgets_budget" {}
  mock_resource "aws_cloudfront_cache_policy" {}
  mock_resource "aws_cloudfront_function" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:function/arena-spa-routes" }
  }
  mock_resource "aws_cloudfront_origin_access_control" {}
  mock_resource "aws_cloudfront_response_headers_policy" {}
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-west-2:123456789012:log-group:mock" }
  }
  mock_resource "aws_cloudwatch_metric_alarm" {}
  mock_resource "aws_ecr_lifecycle_policy" {}
  mock_resource "aws_ecr_repository" {
    defaults = { arn = "arn:aws:ecr:us-west-2:123456789012:repository/arena-api", repository_url = "123456789012.dkr.ecr.us-west-2.amazonaws.com/arena-api" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_iam_role_policy" {}
  mock_resource "aws_iam_role_policy_attachment" {}
  mock_resource "aws_lambda_alias" {
    defaults = { arn = "arn:aws:lambda:us-west-2:123456789012:function:mock:live" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:us-west-2:123456789012:function:mock", version = "1" }
  }
  mock_resource "aws_lambda_permission" {}
  mock_resource "aws_route53_record" {}
  mock_resource "aws_route53_zone" {
    defaults = { zone_id = "Z0123456789ABCDEFGHIJ" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::jackdaw-arena-web-123456789012", bucket_regional_domain_name = "jackdaw-arena-web-123456789012.s3.us-west-2.amazonaws.com" }
  }
  mock_resource "aws_s3_bucket_ownership_controls" {}
  mock_resource "aws_s3_bucket_policy" {}
  mock_resource "aws_s3_bucket_public_access_block" {}
  mock_resource "aws_s3_bucket_server_side_encryption_configuration" {}
  mock_resource "aws_scheduler_schedule" {}
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:us-west-2:123456789012:arena-alerts" }
  }
  mock_resource "aws_sns_topic_subscription" {}
  mock_resource "aws_ssm_parameter" {}
}

mock_provider "random" {
  override_during = plan
  mock_resource "random_password" {}
}

# Distinct from the arena cluster, so the CI-isolation assertion means something.
override_resource {
  target          = aws_dsql_cluster.ci
  override_during = plan
  values = {
    identifier = "zyxwvutsrqponmlkjihgfedcba"
    arn        = "arn:aws:dsql:us-west-2:123456789012:cluster/zyxwvutsrqponmlkjihgfedcba"
  }
}

variables {
  api_image_uri = "123456789012.dkr.ecr.us-west-2.amazonaws.com/arena-api:test"
}

run "defaults" {
  command = plan
  # --- HTTPS and the edge ---
  assert {
    condition = alltrue(concat(
      [aws_cloudfront_distribution.site.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"],
      [for b in aws_cloudfront_distribution.site.ordered_cache_behavior : b.viewer_protocol_policy == "redirect-to-https"],
    ))
    error_message = "Every behavior must redirect HTTP to HTTPS."
  }
  assert {
    condition     = aws_cloudfront_distribution.site.viewer_certificate[0].minimum_protocol_version == "TLSv1.2_2021"
    error_message = "Viewers must use TLS 1.2 or newer."
  }
  assert {
    condition     = aws_acm_certificate.site.region == "us-east-1" && aws_acm_certificate.site.validation_method == "DNS"
    error_message = "CloudFront needs a us-east-1 certificate; DNS validation lets ACM renew it unattended."
  }
  assert {
    condition     = length(aws_route53_record.cert_validation) == 1 && aws_acm_certificate_validation.site.validation_record_fqdns == toset([aws_route53_record.cert_validation["arena.tylerflar.com"].fqdn])
    error_message = "The certificate must be validated through the zone's record."
  }
  assert {
    condition = alltrue([for t in ["A", "AAAA"] :
      aws_route53_record.site[t].alias[0].name == aws_cloudfront_distribution.site.domain_name &&
      aws_route53_record.site[t].alias[0].zone_id == aws_cloudfront_distribution.site.hosted_zone_id
    ])
    error_message = "The site name must ALIAS (IPv4 and IPv6) to the distribution."
  }
  assert {
    condition     = toset(aws_route53_record.caa.records) == toset(["0 issue \"amazon.com\"", "0 issuewild \";\""])
    error_message = "CAA must allow only Amazon's CA and forbid wildcards."
  }
  assert {
    condition     = strcontains(aws_cloudfront_response_headers_policy.site.security_headers_config[0].content_security_policy[0].content_security_policy, "default-src 'self'")
    error_message = "The SPA must be served with a same-origin CSP."
  }
  assert {
    condition     = aws_cloudfront_response_headers_policy.site.security_headers_config[0].strict_transport_security[0].access_control_max_age_sec >= 31536000
    error_message = "HSTS for at least a year."
  }

  # --- the site bucket is private; only this distribution reads it ---
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.web.block_public_acls,
      aws_s3_bucket_public_access_block.web.block_public_policy,
      aws_s3_bucket_public_access_block.web.ignore_public_acls,
      aws_s3_bucket_public_access_block.web.restrict_public_buckets,
    ])
    error_message = "The site bucket must block all public access."
  }
  assert {
    condition     = jsondecode(aws_s3_bucket_policy.web.policy).Statement[0].Condition.StringEquals["AWS:SourceArn"] == aws_cloudfront_distribution.site.arn
    error_message = "Only this distribution may read the bucket."
  }

  # --- the API is reachable only through CloudFront, and per-caller traffic is never cached ---
  assert {
    condition = nonsensitive(one([
      for o in aws_cloudfront_distribution.site.origin : one(o.custom_header).value if o.origin_id == "api"
    ]) == aws_ssm_parameter.origin_verify_secret.value)
    error_message = "CloudFront must send the secret header the API checks."
  }
  assert {
    condition     = contains([for o in aws_cloudfront_distribution.site.origin : o.domain_name], "abcdefghijklmnopqrstuvwxyz012345.lambda-url.us-west-2.on.aws")
    error_message = "The API origin must be the Function URL's host."
  }
  assert {
    condition = alltrue([
      for b in aws_cloudfront_distribution.site.ordered_cache_behavior :
      b.cache_policy_id == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" if b.path_pattern != "/api/*"
    ])
    error_message = "Agent, account, auth and health routes must never be cached."
  }
  assert {
    condition = toset([for b in aws_cloudfront_distribution.site.ordered_cache_behavior : b.path_pattern]) == toset([
      "/api/v1/*", "/api/me", "/api/me/*", "/api/admin/*", "/auth/*", "/healthz", "/healthz/*", "/api/*",
    ])
    error_message = "Unexpected set of cache behaviors."
  }
  assert {
    condition     = aws_cloudfront_distribution.site.ordered_cache_behavior[length(aws_cloudfront_distribution.site.ordered_cache_behavior) - 1].path_pattern == "/api/*"
    error_message = "The public catch-all must come after every private path (first match wins)."
  }
  assert {
    condition     = aws_cloudfront_cache_policy.public_api.parameters_in_cache_key_and_forwarded_to_origin[0].cookies_config[0].cookie_behavior == "none"
    error_message = "Public API caching must never key on (or forward) cookies."
  }
  assert {
    condition     = aws_lambda_function_url.api.authorization_type == "NONE" && aws_lambda_function_url.api.qualifier == "live"
    error_message = "The Function URL serves the live alias."
  }
  assert {
    condition     = aws_lambda_permission.url_invoke.invoked_via_function_url == true
    error_message = "Public InvokeFunction must be limited to calls through the Function URL."
  }

  # --- data and secrets ---
  assert {
    condition     = aws_dsql_cluster.arena.deletion_protection_enabled == true && aws_dsql_cluster.ci.deletion_protection_enabled == false
    error_message = "The arena cluster is protected from deletion; the CI scratch cluster isn't."
  }
  assert {
    condition     = !strcontains(aws_iam_role_policy.api.policy, "DbConnectAdmin") && strcontains(aws_iam_role_policy.tasks.policy, "DbConnectAdmin")
    error_message = "Only the tasks function connects to the database as admin."
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["ARENA_DSQL_ENDPOINT"] == "abcdefghijklmnopqrstuvwxyz.dsql.us-west-2.on.aws"
    error_message = "The API must point at the arena cluster's endpoint."
  }
  assert {
    condition     = aws_ssm_parameter.session_secret.value_wo_version == 1 && aws_ssm_parameter.session_secret.type == "SecureString"
    error_message = "The session secret is a write-only SecureString."
  }
  assert {
    condition     = one(aws_backup_selection.arena.resources) == aws_dsql_cluster.arena.arn && one(aws_backup_plan.daily.rule).lifecycle[0].delete_after == 7
    error_message = "The arena cluster is backed up daily and kept a week."
  }

  # --- defaults: cheap, no reservation, keep-warm on, no alerts ---
  assert {
    condition     = aws_lambda_function.api.reserved_concurrent_executions == -1
    error_message = "No reserved concurrency unless asked for."
  }
  assert {
    condition     = length(aws_scheduler_schedule.keep_warm) == 1 && aws_scheduler_schedule.janitor.schedule_expression == "rate(15 minutes)"
    error_message = "The janitor and keep-warm schedules exist by default."
  }
  assert {
    condition     = length(aws_sns_topic.alerts) == 0 && length(aws_cloudwatch_metric_alarm.lambda) == 0 && length(aws_budgets_budget.monthly) == 0
    error_message = "No alert_email, no alerts."
  }
  assert {
    condition     = aws_cloudwatch_log_group.api.retention_in_days == 14 && aws_cloudwatch_log_group.tasks.retention_in_days == 14
    error_message = "Logs expire after two weeks."
  }
  assert {
    condition     = aws_ecr_repository.api.image_tag_mutability == "IMMUTABLE"
    error_message = "Image tags are immutable, so a tag always means the same build."
  }

  # --- GitHub Actions ---
  assert {
    condition     = jsondecode(aws_iam_role.deploy.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:TylerFlar@18598509/jackdaw-arena@1432824252:environment:production"
    error_message = "Only the repository's production environment may deploy."
  }
  assert {
    condition     = jsondecode(aws_iam_role.ci.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:TylerFlar@18598509/jackdaw-arena@1432824252:ref:refs/heads/main"
    error_message = "Only workflows on main may use the CI role."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.ci.policy).Statement[0].Resource == aws_dsql_cluster.ci.arn
    error_message = "CI reaches the scratch cluster only."
  }
}

run "alerts_and_limits" {
  command = plan
  variables {
    alert_email         = "alerts@example.com"
    api_max_concurrency = 50
    keep_warm           = false
  }
  assert {
    condition     = aws_sns_topic_subscription.alerts[0].endpoint == "alerts@example.com" && aws_sns_topic_subscription.alerts_use1[0].region == "us-east-1"
    error_message = "Alerts go to the address, from both regions."
  }
  assert {
    condition     = toset(keys(aws_cloudwatch_metric_alarm.lambda)) == toset(["api-errors", "tasks-errors", "api-throttles"])
    error_message = "Errors of both functions and API throttling are alarmed."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.cdn_5xx[0].region == "us-east-1" && aws_cloudwatch_metric_alarm.cdn_5xx[0].alarm_actions == toset([aws_sns_topic.alerts_use1[0].arn])
    error_message = "The CloudFront alarm lives with CloudFront's metrics and notifies the us-east-1 topic."
  }
  assert {
    condition     = alltrue([for n in aws_budgets_budget.monthly[0].notification : contains(tolist(n.subscriber_email_addresses), "alerts@example.com")])
    error_message = "Budget alerts go to the address."
  }
  assert {
    condition     = aws_lambda_function.api.reserved_concurrent_executions == 50
    error_message = "api_max_concurrency reserves (and caps) concurrency."
  }
  assert {
    condition     = length(aws_scheduler_schedule.keep_warm) == 0
    error_message = "keep_warm = false removes the schedule."
  }
}

run "existing_github_oidc_provider" {
  command = plan
  variables {
    create_github_oidc_provider = false
  }
  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0
    error_message = "Reuse the account's provider instead of creating a second one."
  }
  assert {
    condition     = jsondecode(aws_iam_role.deploy.assume_role_policy).Statement[0].Principal.Federated == data.aws_iam_openid_connect_provider.github[0].arn
    error_message = "The roles must trust the existing provider."
  }
}

run "rejects_bad_inputs" {
  command = plan
  variables {
    domain              = "Arena.Example.com"
    alert_email         = "not-an-email"
    api_memory_mb       = 128
    api_max_concurrency = 0
  }
  expect_failures = [var.domain, var.alert_email, var.api_memory_mb, var.api_max_concurrency]
}
