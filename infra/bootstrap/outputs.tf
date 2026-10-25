output "state_bucket" {
  description = "The S3 bucket holding the main stack's state."
  value       = aws_s3_bucket.state.bucket
}

output "backend_config" {
  description = "Pass to `terraform init -backend-config=...` in ../terraform"
  value       = "bucket=${aws_s3_bucket.state.bucket}"
}
