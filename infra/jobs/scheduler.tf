resource "aws_scheduler_schedule" "jobs" {
  name        = local.name
  description = "Run due background work every minute"
  state       = var.schedule_enabled ? "ENABLED" : "DISABLED"

  schedule_expression = "rate(1 minute)"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_alias.live.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ source = "schedule" })

    # The next tick supersedes a missed one.
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 60
    }
  }
}
