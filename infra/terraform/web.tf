# The site: one CloudFront distribution in front of the React build (private S3, OAC) and the
# API's Function URL. Only GETs of public data are cached at the edge, for as long as the API's
# Cache-Control says (s-maxage); anything per-caller passes straight through.

resource "aws_s3_bucket" "web" {
  bucket        = "jackdaw-arena-web-${local.account_id}"
  force_destroy = true # build output only: git is the source
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "arena-web"
  description                       = "CloudFront reads the site bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudFrontReads"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.web.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
      {
        Sid       = "TLSOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.web]
}

# Client-side routes (/agents/x, /episodes/y) all serve the SPA shell; files keep their path.
resource "aws_cloudfront_function" "spa" {
  name    = "arena-spa-routes"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite extensionless paths to /index.html"
  publish = true
  code    = file("${path.module}/spa-routes.js")
}

# --- headers -----------------------------------------------------------------------------

locals {
  csp = join("; ", [
    "default-src 'self'",
    "img-src 'self' data: https://avatars.githubusercontent.com",
    "style-src 'self'",
    "script-src 'self'",
    "connect-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ])
}

resource "aws_cloudfront_response_headers_policy" "site" {
  name    = "arena-site"
  comment = "The SPA: strict CSP plus the standard security headers"
  security_headers_config {
    content_security_policy {
      content_security_policy = local.csp
      override                = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
      override = true
    }
  }
}

# The API's responses: the same, minus the CSP (JSON needs none, and /api/docs is Swagger UI,
# which loads from a CDN).
resource "aws_cloudfront_response_headers_policy" "api" {
  name    = "arena-api"
  comment = "API responses: security headers without a CSP"
  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

# --- caching -----------------------------------------------------------------------------

locals {
  # AWS-managed policies (their IDs are fixed).
  caching_optimized      = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  caching_disabled       = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  all_viewer_except_host = "b689b0a8-53d0-40ab-baf2-68738e2966ac"

  api_origin_host = trimsuffix(trimprefix(aws_lambda_function_url.api.function_url, "https://"), "/")
  all_methods     = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
  # Everything else under /api/ is a public read.
  private_api_paths = ["/api/v1/*", "/api/me", "/api/me/*", "/api/admin/*", "/auth/*", "/healthz", "/healthz/*"]
  # The query parameters the public endpoints take; anything else is dropped at the edge.
  public_api_query_parameters = ["track", "season", "before", "limit", "from"]
}

# Public reads, cached for exactly as long as the API's s-maxage (default 0: no header, no
# cache). Never keyed on cookies or headers: these endpoints don't read them.
resource "aws_cloudfront_cache_policy" "public_api" {
  name        = "arena-public-api"
  comment     = "Public API reads: TTL from the origin's s-maxage"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 31536000
  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "whitelist"
      query_strings {
        items = local.public_api_query_parameters
      }
    }
  }
}

# --- distribution ------------------------------------------------------------------------

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "Jackdaw Arena"
  aliases             = [var.domain]
  default_root_object = "index.html"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  price_class         = "PriceClass_100"

  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  origin {
    origin_id   = "api"
    domain_name = local.api_origin_host
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 30
    }
    # The API refuses requests without this: nobody can bypass CloudFront to reach it.
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  default_cache_behavior {
    target_origin_id           = "web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.caching_optimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site.id
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa.arn
    }
  }

  # Per-caller traffic (agents, accounts, sign-in, health): never cached, every header, cookie
  # and query parameter forwarded (except Host, which must be the Function URL's).
  dynamic "ordered_cache_behavior" {
    for_each = local.private_api_paths
    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = "api"
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = local.all_methods
      cached_methods             = ["GET", "HEAD"]
      compress                   = true
      cache_policy_id            = local.caching_disabled
      origin_request_policy_id   = local.all_viewer_except_host
      response_headers_policy_id = aws_cloudfront_response_headers_policy.api.id
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "api"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.public_api.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.api.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
