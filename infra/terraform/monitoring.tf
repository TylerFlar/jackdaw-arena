# Email alerts: four CloudWatch alarms (inside the free tier's ten) and a monthly cost budget.
# All of it only when alert_email is set. SNS asks the address to confirm each subscription.

locals {
  alerts = var.alert_email != null
}

resource "aws_sns_topic" "alerts" {
  count = local.alerts ? 1 : 0
  name  = "arena-alerts"
}

resource "aws_sns_topic_subscription" "alerts" {
  count     = local.alerts ? 1 : 0
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# CloudFront's metrics are in us-east-1, and an alarm can only notify a topic in its own region.
resource "aws_sns_topic" "alerts_use1" {
  count  = local.alerts ? 1 : 0
  region = "us-east-1"
  name   = "arena-alerts"
}

resource "aws_sns_topic_subscription" "alerts_use1" {
  count     = local.alerts ? 1 : 0
  region    = "us-east-1"
  topic_arn = aws_sns_topic.alerts_use1[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  lambda_alarms = {
    api-errors = {
      function    = aws_lambda_function.api.function_name
      metric      = "Errors"
      description = "The API function failed (crashed, timed out or ran out of memory); visitors saw 5xx. See the /aws/lambda/arena-api logs."
    }
    tasks-errors = {
      function    = aws_lambda_function.tasks.function_name
      metric      = "Errors"
      description = "A task failed: migration, idle janitor or house run. See the /aws/lambda/arena-tasks logs."
    }
    api-throttles = {
      function    = aws_lambda_function.api.function_name
      metric      = "Throttles"
      description = "The API hit its concurrency limit and turned requests away (clients retry). If this is real traffic, raise api_max_concurrency, or the account's Lambda concurrency quota."
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda" {
  for_each            = local.alerts ? local.lambda_alarms : {}
  alarm_name          = "arena-${each.key}"
  alarm_description   = each.value.description
  namespace           = "AWS/Lambda"
  metric_name         = each.value.metric
  dimensions          = { FunctionName = each.value.function }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

# Any 5xx the site returned, from the API or S3: more than 5% of requests in two of three
# 5-minute windows (so one stray error at 3 a.m. doesn't page anybody).
resource "aws_cloudwatch_metric_alarm" "cdn_5xx" {
  count               = local.alerts ? 1 : 0
  region              = "us-east-1"
  alarm_name          = "arena-cloudfront-5xx"
  alarm_description   = "More than 5% of requests to ${var.domain} failed with 5xx."
  namespace           = "AWS/CloudFront"
  metric_name         = "5xxErrorRate"
  dimensions          = { DistributionId = aws_cloudfront_distribution.site.id, Region = "Global" }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts_use1[0].arn]
  ok_actions          = [aws_sns_topic.alerts_use1[0].arn]
}

resource "aws_budgets_budget" "monthly" {
  count        = local.alerts ? 1 : 0
  name         = "arena-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    notification_type          = "ACTUAL"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    notification_type          = "FORECASTED"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }
}
