resource "aws_cloudwatch_log_group" "jobs" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 14
}

# Ownership split (ADR 0001): OpenTofu owns configuration; CI owns code. CI updates the image,
# publishes versions and moves the `live` alias, so image_uri and the alias version are ignored.
resource "aws_lambda_function" "jobs" {
  function_name                  = local.name
  role                           = aws_iam_role.jobs.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.jobs.repository_url}:${var.initial_image_tag}"
  architectures                  = ["arm64"]
  memory_size                    = var.memory_mb
  timeout                        = 900
  reserved_concurrent_executions = 1
  publish                        = false

  environment {
    variables = local.environment
  }

  logging_config {
    log_format = "Text" # the application already writes one JSON object per line
    log_group  = aws_cloudwatch_log_group.jobs.name
  }

  lifecycle {
    ignore_changes = [image_uri]
  }

  depends_on = [
    aws_iam_role_policy.jobs,
    aws_cloudwatch_log_group.jobs,
  ]
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.jobs.function_name
  function_version = "$LATEST" # until the first CI deployment publishes a version

  lifecycle {
    ignore_changes = [function_version]
  }
}

# Wake-ups and scheduled invocations are hints: MongoDB holds the work, and the next tick
# recovers anything a dropped event missed. So asynchronous events are never retried and expire
# after five minutes instead of queueing up behind the single concurrent execution.
resource "aws_lambda_function_event_invoke_config" "live" {
  function_name                = aws_lambda_function.jobs.function_name
  qualifier                    = aws_lambda_alias.live.name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 300
}
