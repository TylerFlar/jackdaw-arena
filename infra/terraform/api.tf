# The API image in ECR, and the two Lambda functions that run it.

resource "aws_ecr_repository" "api" {
  name                 = "arena-api"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 5 images, for rollbacks"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/arena-api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "tasks" {
  name              = "/aws/lambda/arena-tasks"
  retention_in_days = 14
}

# --- IAM -------------------------------------------------------------------------------------

locals {
  lambda_assume = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  ssm_read = {
    Effect   = "Allow"
    Action   = ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"]
    Resource = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter${local.ssm_path}", "arn:aws:ssm:${var.region}:${local.account_id}:parameter${local.ssm_path}/*"]
  }
}

resource "aws_iam_role" "api" {
  name               = "arena-api"
  assume_role_policy = local.lambda_assume
}

resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.api.arn}:*" },
      # The api connects as the least-privilege database role "arena_app", never as admin.
      { Effect = "Allow", Action = ["dsql:DbConnect"], Resource = aws_dsql_cluster.arena.arn },
      local.ssm_read,
    ]
  })
}

resource "aws_iam_role" "tasks" {
  name               = "arena-tasks"
  assume_role_policy = local.lambda_assume
}

resource "aws_iam_role_policy" "tasks" {
  role = aws_iam_role.tasks.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.tasks.arn}:*" },
      # Migrations change the schema and map the api's IAM role to arena_app: admin.
      { Effect = "Allow", Action = ["dsql:DbConnectAdmin"], Resource = aws_dsql_cluster.arena.arn },
      local.ssm_read,
    ]
  })
}

# --- functions -------------------------------------------------------------------------------

locals {
  api_env = {
    ARENA_ENV           = "prod"
    ARENA_DB            = "dsql"
    ARENA_DSQL_ENDPOINT = local.dsql_endpoint
    ARENA_DSQL_USER     = "arena_app"
    ARENA_AWS_REGION    = var.region
    ARENA_SSM_PATH      = local.ssm_path
    ARENA_PUBLIC_URL    = local.site_url
    ARENA_ADMIN_LOGINS  = jsonencode(var.admin_logins)
  }
}

resource "aws_lambda_function" "api" {
  function_name = "arena-api"
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  image_uri     = var.api_image_uri
  architectures = ["x86_64"] # the observation encoder's floats match Linux x86_64 training bit for bit
  memory_size   = var.api_memory_mb
  timeout       = 30
  publish       = true

  reserved_concurrent_executions = var.api_max_concurrency == null ? -1 : var.api_max_concurrency

  environment {
    variables = merge(local.api_env, { ARENA_ROLE = "api" })
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.api.name
  }

  lifecycle {
    # Deploys update the code (and publish versions) outside Terraform.
    ignore_changes = [image_uri]
  }
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.api.function_name
  function_version = aws_lambda_function.api.version
  lifecycle {
    # A deploy moves the alias to the version it published; rollback moves it back.
    ignore_changes = [function_version]
  }
}

# The Function URL is public, but the API refuses any request without CloudFront's secret
# header. (CloudFront's OAC for Lambda would make every POST carry a body hash, which agents
# and browsers don't send.)
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  qualifier          = aws_lambda_alias.live.name
  authorization_type = "NONE"
  invoke_mode        = "BUFFERED"
}

# A public URL needs both statements; the second only covers invocations through the URL.
resource "aws_lambda_permission" "url" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  qualifier              = aws_lambda_alias.live.name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "url_invoke" {
  statement_id             = "FunctionURLAllowInvokeAction"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.api.function_name
  qualifier                = aws_lambda_alias.live.name
  principal                = "*"
  invoked_via_function_url = true
}

resource "aws_lambda_function" "tasks" {
  function_name = "arena-tasks"
  role          = aws_iam_role.tasks.arn
  package_type  = "Image"
  image_uri     = var.api_image_uri
  architectures = ["x86_64"]
  memory_size   = var.api_memory_mb
  timeout       = 900

  environment {
    variables = merge(local.api_env, {
      ARENA_ROLE              = "tasks"
      ARENA_DSQL_APP_ROLE_ARN = aws_iam_role.api.arn
    })
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.tasks.name
  }

  lifecycle {
    ignore_changes = [image_uri]
  }
}
