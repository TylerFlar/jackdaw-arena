terraform {
  # 1.11: write-only arguments, so generated secrets never reach the state file.
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # 6.x: a per-resource `region`, so the few us-east-1 pieces (CloudFront's certificate and
      # metrics) need no second provider.
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Partial configuration: see backend.hcl.example.
  #   terraform init -backend-config=backend.hcl
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = local.tags
  }
}
