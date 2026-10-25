# Jackdaw Arena on AWS, serverless: nothing runs (or bills by the hour) while nobody plays.
#
#   CloudFront (arena.tylerflar.com) ─┬─ default ─────────▶ S3: the React SPA
#                                     ├─ /api/* (GET) ───▶ Lambda "arena-api", edge-cached per Cache-Control
#                                     └─ /api/v1, /api/me, /auth, /healthz ─▶ the same Lambda, never cached
#   Lambda "arena-tasks" (no URL): migrations, the idle janitor (EventBridge Scheduler), house runs
#   Aurora DSQL (IAM auth): the data · SSM Parameter Store: secrets · ECR: the image

data "aws_caller_identity" "current" {}

locals {
  tags       = { Project = "jackdaw-arena", ManagedBy = "terraform" }
  account_id = data.aws_caller_identity.current.account_id
  ssm_path   = "/arena/prod"
  site_url   = "https://${var.domain}"
}
