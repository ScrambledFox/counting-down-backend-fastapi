locals {
  name               = "${var.project}-jobs"
  ssm_parameter_path = "/${var.project}/${var.environment}/jobs"

  # Secrets are created as placeholders and set out of band, so values never enter state.
  secret_parameters = [
    "MONGO_URL",
    "OPENAI_API_KEY",
    "XIAOBAO_WEB_PUSH_VAPID_PRIVATE_KEY",
    "XIAOBAO_WEB_PUSH_SUBSCRIPTION_ENCRYPTION_KEY",
  ]

  environment = merge(var.extra_environment, {
    APP_ENV                           = "prod"
    AUTH_ACCESS_KEYS_REQUIRED         = "false"
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
    SSM_PARAMETER_PATH                = local.ssm_parameter_path
    XIAOBAO_WEB_PUSH_ENABLED          = "true"
    XIAOBAO_WEB_PUSH_VAPID_PUBLIC_KEY = var.web_push_vapid_public_key
    XIAOBAO_WEB_PUSH_VAPID_SUBJECT    = var.web_push_vapid_subject
  })

  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}
