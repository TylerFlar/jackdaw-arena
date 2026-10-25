# The site's own zone. The parent domain's DNS (Squarespace, for tylerflar.com) delegates the
# name to it with four NS records: the name_servers output.

resource "aws_route53_zone" "arena" {
  name    = var.domain
  comment = "Jackdaw Arena, delegated from the parent domain's DNS"
}

resource "aws_route53_record" "site" {
  for_each = toset(["A", "AAAA"])
  zone_id  = aws_route53_zone.arena.zone_id
  name     = var.domain
  type     = each.key
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

# Only Amazon's CA may issue certificates for this name, and nobody may issue a wildcard.
resource "aws_route53_record" "caa" {
  zone_id = aws_route53_zone.arena.zone_id
  name    = var.domain
  type    = "CAA"
  ttl     = 3600
  records = ["0 issue \"amazon.com\"", "0 issuewild \";\""]
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for o in aws_acm_certificate.site.domain_validation_options : o.domain_name => o
  }
  zone_id         = aws_route53_zone.arena.zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  ttl             = 300
  records         = [each.value.resource_record_value]
  allow_overwrite = true
}
