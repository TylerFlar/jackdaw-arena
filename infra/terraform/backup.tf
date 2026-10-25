# Daily AWS Backup of the arena cluster, kept a week. Episodes are append-only and the engine is
# deterministic, so a day-old restore loses at most a day of play, never correctness.

resource "aws_backup_vault" "arena" {
  name = "arena"
}

resource "aws_backup_plan" "daily" {
  name = "arena-daily"
  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.arena.name
    schedule          = "cron(0 10 * * ? *)" # 10:00 UTC, 2-3 a.m. Pacific
    start_window      = 60
    completion_window = 360
    lifecycle {
      delete_after = 7
    }
  }
}

resource "aws_iam_role" "backup" {
  name = "arena-backup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_iam_role_policy_attachment" "restore" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores"
}

resource "aws_backup_selection" "arena" {
  name         = "arena-dsql"
  plan_id      = aws_backup_plan.daily.id
  iam_role_arn = aws_iam_role.backup.arn
  resources    = [aws_dsql_cluster.arena.arn]
}
