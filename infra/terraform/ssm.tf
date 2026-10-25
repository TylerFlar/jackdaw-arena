# Secrets for the API, read once per cold start from /arena/prod/*.
#
# The session secret is write-only: generated ephemerally and never stored in Terraform state.
# The GitHub OAuth client id and secret are not managed here at all: the operator writes them
# with infra/scripts/set-secrets.ps1, so they never pass through Terraform.

ephemeral "random_password" "session" {
  length  = 48
  special = false
}

resource "aws_ssm_parameter" "session_secret" {
  name             = "${local.ssm_path}/session_secret"
  type             = "SecureString"
  value_wo         = ephemeral.random_password.session.result
  value_wo_version = 1 # bump to rotate (signs everyone out)
  description      = "Signs the OAuth handshake cookie"
}

# CloudFront adds this header to every request it forwards to the Function URL; the API refuses
# requests without it. It must also be in CloudFront's configuration, so it lives in state.
resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

resource "aws_ssm_parameter" "origin_verify_secret" {
  name        = "${local.ssm_path}/origin_verify_secret"
  type        = "SecureString"
  value       = random_password.origin_verify.result
  description = "Shared secret between CloudFront and the API's Function URL"
}
