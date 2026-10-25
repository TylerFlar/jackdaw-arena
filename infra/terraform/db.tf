resource "aws_dsql_cluster" "arena" {
  deletion_protection_enabled = true
  tags                        = { Name = "arena" }
}

# A scratch cluster for CI's database tests against the real thing.
resource "aws_dsql_cluster" "ci" {
  deletion_protection_enabled = false
  tags                        = { Name = "arena-ci" }
}

locals {
  dsql_endpoint    = "${aws_dsql_cluster.arena.identifier}.dsql.${var.region}.on.aws"
  dsql_ci_endpoint = "${aws_dsql_cluster.ci.identifier}.dsql.${var.region}.on.aws"
}
