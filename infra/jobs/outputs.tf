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

output "api_function_name" {
  value = aws_lambda_function.api.function_name
}

output "api_url" {
  description = "Base URL of the API. The frontend's VITE_API_BASE_URL is this plus api/v1."
  value       = aws_lambda_function_url.api.function_url
}

output "api_ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "api_ssm_parameter_path" {
  value = local.api_ssm_parameter_path
}
