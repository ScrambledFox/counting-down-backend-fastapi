# --- HTTP API on Lambda (ADR 0001, Phase 3) ---------------------------------------------------
# FastAPI runs behind the Lambda Web Adapter on a public, response-streaming Function URL. There
# is no API Gateway: CORS, login brute-force limits and AI budgets are enforced by the
# application. Reserved concurrency caps how many instances an attack (or a bug) can start.
# Like the jobs function, OpenTofu owns configuration and CI owns code (image and `live` alias).

locals {
  api_name               = "${var.project}-api"
  api_ssm_parameter_path = "/${var.project}/${var.environment}/api"

  api_secret_parameters = [
    "MONGO_URL",
    "OPENAI_API_KEY",
    "ACCESS_KEY_DANFENG",
    "ACCESS_KEY_JORIS",
    "AERODATABOX_API_KEY",
    "XIAOBAO_WEB_PUSH_VAPID_PRIVATE_KEY",
    "XIAOBAO_WEB_PUSH_SUBSCRIPTION_ENCRYPTION_KEY",
  ]

  api_environment = merge(var.extra_environment, {
    APP_ENV                           = "prod"
    LOG_FORMAT                        = "json"
    ENSURE_INDEXES_ON_STARTUP         = "false"
    IMAGE_WORKER_ENABLED              = "false"
    MEDIATION_WORKER_ENABLED          = "false"
    XIAOBAO_IN_PROCESS_JOBS_ENABLED   = "false"
    MONGO_APP_NAME                    = var.mongo_app_name
    MONGO_MAX_POOL_SIZE               = "5"
    AWS_S3_BUCKET                     = var.s3_bucket_name
    AWS_S3_REGION                     = var.s3_bucket_region
    AWS_S3_IMAGE_FOLDER               = var.s3_image_prefix
    AWS_S3_THUMBNAIL_FOLDER           = var.s3_thumbnail_prefix
    SSM_PARAMETER_PATH                = local.api_ssm_parameter_path
    FRONTEND_URLS                     = join(",", var.frontend_origins)
    XIAOBAO_WEB_PUSH_ENABLED          = "true"
    XIAOBAO_WEB_PUSH_VAPID_PUBLIC_KEY = var.web_push_vapid_public_key
    XIAOBAO_WEB_PUSH_VAPID_SUBJECT    = var.web_push_vapid_subject
    # Wake the jobs function with this function's role: no static AWS keys.
    JOB_WAKEUP_MODE                 = "lambda"
    JOB_WAKEUP_LAMBDA_FUNCTION_NAME = "${aws_lambda_function.jobs.function_name}:${aws_lambda_alias.live.name}"
    JOB_WAKEUP_LAMBDA_REGION        = var.aws_region
  })
}

resource "aws_ecr_repository" "api" {
  name                 = local.api_name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy     = aws_ecr_lifecycle_policy.jobs.policy
}

resource "aws_ssm_parameter" "api_secret" {
  for_each = toset(local.api_secret_parameters)

  name  = "${local.api_ssm_parameter_path}/${each.key}"
  type  = "SecureString"
  value = "set-out-of-band"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.api_name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name                  = local.api_name
  role                           = aws_iam_role.api.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.api.repository_url}:${var.api_initial_image_tag}"
  architectures                  = ["arm64"]
  memory_size                    = var.api_memory_mb
  timeout                        = 300 # longest request: a streamed Xiao Bao reply
  reserved_concurrent_executions = var.api_reserved_concurrency
  publish                        = false

  environment {
    variables = local.api_environment
  }

  logging_config {
    log_format = "Text" # the application already writes one JSON object per line
    log_group  = aws_cloudwatch_log_group.api.name
  }

  lifecycle {
    ignore_changes = [image_uri]
  }

  depends_on = [
    aws_iam_role_policy.api,
    aws_cloudwatch_log_group.api,
  ]
}

resource "aws_lambda_alias" "api_live" {
  name             = "live"
  function_name    = aws_lambda_function.api.function_name
  function_version = "$LATEST" # until the first CI deployment publishes a version

  lifecycle {
    ignore_changes = [function_version]
  }
}

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  qualifier          = aws_lambda_alias.api_live.name
  authorization_type = "NONE" # the application authenticates every protected route
  invoke_mode        = "RESPONSE_STREAM"
}

# Public Function URLs need both permissions since October 2025: InvokeFunctionUrl, and
# InvokeFunction restricted to calls that arrive through the Function URL.
resource "aws_lambda_permission" "api_url" {
  statement_id           = "PublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  qualifier              = aws_lambda_alias.api_live.name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "api_url_invoke" {
  statement_id             = "PublicFunctionUrlInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.api.function_name
  qualifier                = aws_lambda_alias.api_live.name
  principal                = "*"
  invoked_via_function_url = true
}

# Browsers upload photos straight to the existing bucket with presigned POST forms. This only
# manages the bucket's CORS rules (it had none); the bucket itself is not managed here.
resource "aws_s3_bucket_cors_configuration" "images" {
  count  = var.manage_bucket_cors ? 1 : 0
  bucket = var.s3_bucket_name

  cors_rule {
    allowed_methods = ["POST", "GET", "HEAD"]
    allowed_origins = var.frontend_origins
    allowed_headers = ["*"]
    max_age_seconds = 3600
  }
}
