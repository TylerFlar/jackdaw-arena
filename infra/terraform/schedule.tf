# EventBridge Scheduler: the idle janitor, and an optional keep-warm ping (both free tier).

resource "aws_iam_role" "scheduler" {
  name = "arena-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = [aws_lambda_function.tasks.arn, aws_lambda_alias.live.arn]
    }]
  })
}

resource "aws_scheduler_schedule" "janitor" {
  name                = "arena-janitor"
  schedule_expression = "rate(15 minutes)"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.tasks.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ task = "janitor" })
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}

resource "aws_scheduler_schedule" "keep_warm" {
  count               = var.keep_warm ? 1 : 0
  name                = "arena-keep-warm"
  schedule_expression = "rate(5 minutes)"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_alias.live.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ task = "warm" })
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
