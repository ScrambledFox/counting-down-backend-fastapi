resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_actual_alert_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "cost_filter" {
    for_each = var.budget_project_tag_only ? [1] : []
    content {
      name   = "TagKeyValue"
      values = ["user:Project$${var.project}"]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "FORECASTED"
    threshold                  = var.budget_forecast_alert_usd
    threshold_type             = "ABSOLUTE_VALUE"
    subscriber_email_addresses = [var.alarm_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = var.budget_actual_alert_usd
    threshold_type             = "ABSOLUTE_VALUE"
    subscriber_email_addresses = [var.alarm_email]
  }
}
