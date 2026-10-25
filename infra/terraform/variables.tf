variable "region" {
  description = "Where the Lambda functions, DSQL clusters and ECR live."
  type        = string
  default     = "us-west-2"
}

variable "domain" {
  description = "The site's hostname. Terraform creates a Route 53 zone for it; delegate it from the parent domain's DNS with the four name_servers."
  type        = string
  default     = "arena.tylerflar.com"
  validation {
    condition     = can(regex("^([a-z0-9-]+\\.)+[a-z]+$", var.domain))
    error_message = "A lowercase hostname, like arena.example.com."
  }
}

variable "api_image_uri" {
  description = "The API image the functions are created with (ECR URI with tag or digest). Later deploys change the functions' code outside Terraform."
  type        = string
}

variable "alert_email" {
  description = "Where alarms and budget alerts go. Null: no alarms, no budget."
  type        = string
  default     = null
  validation {
    condition     = var.alert_email == null || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "An email address, or null for no alerts."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget; emails at 80% actual and 100% forecast."
  type        = number
  default     = 5
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "A positive amount of US dollars."
  }
}

variable "api_memory_mb" {
  description = "Lambda memory (CPU scales with it)."
  type        = number
  default     = 1024
  validation {
    condition     = var.api_memory_mb >= 512 && var.api_memory_mb <= 10240
    error_message = "Between 512 MB (the engine's floor) and Lambda's 10240 MB."
  }
}

variable "api_max_concurrency" {
  description = "Reserved concurrency for the API: a hard cap on parallel requests (cost and scale knob). Null: none, so the account's limit applies. AWS refuses reservations that leave less than 100 unreserved."
  type        = number
  default     = null
  validation {
    condition     = coalesce(var.api_max_concurrency, 1) >= 1
    error_message = "At least 1, or null for no reservation."
  }
}

variable "keep_warm" {
  description = "Ping the API every 5 minutes so most first requests skip the cold start (free tier)."
  type        = bool
  default     = true
}

variable "admin_logins" {
  description = "GitHub logins with moderation rights."
  type        = list(string)
  default     = ["TylerFlar"]
}

variable "github_repo" {
  description = "owner/name of the repository whose workflows may deploy."
  type        = string
  default     = "TylerFlar/jackdaw-arena"
}

variable "github_environment" {
  description = "The GitHub Actions environment the deploy job runs in (part of the OIDC subject)."
  type        = string
  default     = "production"
}

variable "create_github_oidc_provider" {
  description = "Create the account's GitHub Actions OIDC provider. Set false if the account already has one (there can be only one per URL)."
  type        = bool
  default     = true
}
