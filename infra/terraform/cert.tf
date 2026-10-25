# The site certificate. CloudFront only takes certificates from us-east-1. It is validated
# through the Route 53 zone, so ACM renews it by itself for as long as the record stays.

resource "aws_acm_certificate" "site" {
  region            = "us-east-1"
  domain_name       = var.domain
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "site" {
  region                  = "us-east-1"
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}
