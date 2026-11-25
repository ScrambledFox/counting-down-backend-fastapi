# Unencrypted by design: CloudWatch alarms and Budgets cannot publish to a topic encrypted with
# the free AWS-managed key, a customer-managed key costs $1/month, and alerts carry only alarm
# metadata (no personal content).
#trivy:ignore:AVD-AWS-0095
resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  metric_namespace = "${title(var.project)}/Jobs"
  lambda_dimensions = {
    FunctionName = aws_lambda_function.jobs.function_name
  }
}

# Two custom metrics only (cost): failures and timeouts share one, overdue work has its own.
# The job_run_summary log line itself says which queue failed or timed out.
resource "aws_cloudwatch_log_metric_filter" "job_problems" {
  name           = "${local.name}-job-problems"
  log_group_name = aws_cloudwatch_log_group.jobs.name
  pattern        = "{ $.event = \"job_run_summary\" && ($.failed_total > 0 || $.timed_out_total > 0) }"

  metric_transformation {
    name          = "JobProblems"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "overdue_work" {
  name           = "${local.name}-overdue-work"
  log_group_name = aws_cloudwatch_log_group.jobs.name
  pattern        = "{ $.event = \"job_run_summary\" && ($.oldest_overdue_routine_seconds > 600 || $.oldest_pending_push_seconds > 600) }"

  metric_transformation {
    name          = "OverdueWork"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "job_problems" {
  alarm_name          = "${local.name}-failed-or-timed-out-jobs"
  alarm_description   = "Background jobs failed or timed out. Search the log group for event=job_run_summary with failed_total or timed_out_total above 0."
  namespace           = local.metric_namespace
  metric_name         = "JobProblems"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "overdue_work" {
  alarm_name          = "${local.name}-overdue-routines-or-pushes"
  alarm_description   = "A due routine or a pending push has waited more than 10 minutes."
  namespace           = local.metric_namespace
  metric_name         = "OverdueWork"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "function_errors" {
  alarm_name          = "${local.name}-function-errors"
  alarm_description   = "The jobs function itself failed (crash, cold-start or configuration error)."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = local.lambda_dimensions
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# With reserved concurrency 1, an occasional throttle (a wake-up arriving during a run) is
# expected and retried by Lambda; only sustained throttling is a problem.
resource "aws_cloudwatch_metric_alarm" "throttles" {
  alarm_name          = "${local.name}-sustained-throttling"
  alarm_description   = "Invocations are being throttled persistently; a run may be stuck near its timeout."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = local.lambda_dimensions
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 15
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "dropped_events" {
  alarm_name          = "${local.name}-dropped-async-events"
  alarm_description   = "Asynchronous invocations expired or failed without being processed."
  namespace           = "AWS/Lambda"
  metric_name         = "AsyncEventsDropped"
  dimensions          = local.lambda_dimensions
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "event_age" {
  alarm_name          = "${local.name}-async-event-age"
  alarm_description   = "Asynchronous invocations are waiting more than two minutes before running."
  namespace           = "AWS/Lambda"
  metric_name         = "AsyncEventAge"
  dimensions          = local.lambda_dimensions
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  threshold           = 120000 # milliseconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# The schedule invokes the function every minute; silence means the schedule or permissions broke.
resource "aws_cloudwatch_metric_alarm" "no_invocations" {
  count = var.schedule_enabled ? 1 : 0

  alarm_name          = "${local.name}-not-running"
  alarm_description   = "The jobs function was barely invoked in 15 minutes; check the schedule."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = local.lambda_dimensions
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
