# GitHub Actions authenticates with OIDC: no AWS keys stored anywhere.
#   deploy role:  only the repository's "production" environment (deploy.yml) may assume it.
#   ci role:      only workflows on main; it can reach the scratch DSQL cluster (as admin, and as
#                 the app role the tests map to it) and nothing else.
#   pull role:    any of the repository's workflows; it can only log in to ECR Public, whose
#                 anonymous pulls from GitHub's shared runners keep hitting the data limit.

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_arn = (var.create_github_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
  : data.aws_iam_openid_connect_provider.github[0].arn)

  github_trust = {
    for role, subject in {
      deploy = "${var.github_subject_prefix}:environment:${var.github_environment}"
      ci     = "${var.github_subject_prefix}:ref:refs/heads/main"
      pull   = "${var.github_subject_prefix}:*"
    } :
    role => jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = { Federated = local.github_oidc_arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
          StringLike   = { "token.actions.githubusercontent.com:sub" = subject }
        }
      }]
    })
  }
}

resource "aws_iam_role" "deploy" {
  name               = "arena-deploy"
  assume_role_policy = local.github_trust["deploy"]
}

resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "EcrLogin", Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      local.ecr_public_login,
      {
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload",
          "ecr:DescribeImages", "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload",
          "ecr:PutImage", "ecr:UploadLayerPart",
        ]
        Resource = aws_ecr_repository.api.arn
      },
      {
        Sid    = "Functions"
        Effect = "Allow"
        Action = [
          "lambda:GetAlias", "lambda:GetFunction", "lambda:GetFunctionConfiguration",
          "lambda:InvokeFunction", "lambda:ListVersionsByFunction", "lambda:PublishVersion",
          "lambda:UpdateAlias", "lambda:UpdateFunctionCode",
        ]
        Resource = [
          aws_lambda_function.api.arn, "${aws_lambda_function.api.arn}:*",
          aws_lambda_function.tasks.arn, "${aws_lambda_function.tasks.arn}:*",
        ]
      },
      { Sid = "SiteList", Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.web.arn },
      {
        Sid      = "SiteFiles"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.web.arn}/*"
      },
      {
        Sid      = "Invalidate"
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
        Resource = aws_cloudfront_distribution.site.arn
      },
    ]
  })
}

resource "aws_iam_role" "ci" {
  name               = "arena-ci"
  assume_role_policy = local.github_trust["ci"]
}

resource "aws_iam_role_policy" "ci" {
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["dsql:DbConnectAdmin", "dsql:DbConnect"], Resource = aws_dsql_cluster.ci.arn }]
  })
}

locals {
  # A token for pulling ECR Public images with an account's (much higher) allowance.
  ecr_public_login = {
    Sid      = "EcrPublicLogin"
    Effect   = "Allow"
    Action   = ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"]
    Resource = "*"
  }
}

resource "aws_iam_role" "ci_pull" {
  name               = "arena-ci-pull"
  assume_role_policy = local.github_trust["pull"]
}

resource "aws_iam_role_policy" "ci_pull" {
  role   = aws_iam_role.ci_pull.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [local.ecr_public_login] })
}
