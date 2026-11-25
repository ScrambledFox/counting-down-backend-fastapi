output "function_name" {
  value = aws_lambda_function.jobs.function_name
}

output "live_alias_arn" {
  value = aws_lambda_alias.live.arn
}

output "heroku_wakeup_function_name" {
  description = "Value for JOB_WAKEUP_LAMBDA_FUNCTION_NAME on Heroku."
  value       = "${aws_lambda_function.jobs.function_name}:${aws_lambda_alias.live.name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.jobs.repository_url
}

output "github_deploy_role_arn" {
  description = "Value for the AWS_JOBS_DEPLOY_ROLE_ARN variable of the GitHub environment."
  value       = aws_iam_role.github_deploy.arn
}

output "heroku_wakeup_user" {
  description = "Create its access key manually; never through OpenTofu."
  value       = aws_iam_user.heroku_wakeup.name
}

output "ssm_parameter_path" {
  value = local.ssm_parameter_path
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
