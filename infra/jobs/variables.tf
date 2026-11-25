variable "project" {
  description = "Project tag and name prefix."
  type        = string
  default     = "bibi"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "Region for the jobs function, schedule and monitoring."
  type        = string
  default     = "eu-west-1"
}

variable "initial_image_tag" {
  description = "Image tag used only when the function is first created (e.g. sha-<commit>). CI owns later image updates."
  type        = string
}

variable "memory_mb" {
  description = "Jobs function memory."
  type        = number
  default     = 512
}

variable "schedule_enabled" {
  description = "Whether the every-minute schedule invokes the jobs function. Off until cutover (secrets set, first version deployed); set false again to roll back to Heroku."
  type        = bool
  default     = false
}

variable "s3_bucket_name" {
  description = "Existing S3 bucket with gallery images (the same bucket the Heroku app uses)."
  type        = string
}

variable "s3_bucket_region" {
  description = "Region of the existing S3 bucket. Independent of aws_region."
  type        = string
  default     = "eu-west-1"
}

variable "s3_image_prefix" {
  description = "Key prefix of original images."
  type        = string
  default     = "images/"
}

variable "s3_thumbnail_prefix" {
  description = "Key prefix of thumbnails; the only prefix the jobs function may write."
  type        = string
  default     = "thumbnails/"
}

variable "mongo_app_name" {
  description = "MongoDB database name used by production."
  type        = string
}

variable "web_push_vapid_public_key" {
  description = "Public VAPID key (not secret); must match the Heroku app."
  type        = string
}

variable "web_push_vapid_subject" {
  description = "VAPID subject (mailto: or https:); must match the Heroku app."
  type        = string
}

variable "extra_environment" {
  description = "Further non-secret settings mirrored from Heroku (e.g. OPENAI_MODEL_XIAOBAO, THUMBNAIL_SIZE)."
  type        = map(string)
  default     = {}

  validation {
    condition = length(setintersection(keys(var.extra_environment), [
      "MONGO_URL", "OPENAI_API_KEY", "XIAOBAO_WEB_PUSH_VAPID_PRIVATE_KEY",
      "XIAOBAO_WEB_PUSH_SUBSCRIPTION_ENCRYPTION_KEY", "AWS_ACCESS_KEY", "AWS_SECRET_KEY",
    ])) == 0
    error_message = "Secrets belong in SSM Parameter Store, not in extra_environment."
  }
}

variable "budget_email" {
  description = "Email address for the AWS budget alerts."
  type        = string
}

variable "budget_forecast_alert_usd" {
  description = "Alert when forecasted monthly spend exceeds this amount."
  type        = number
  default     = 2
}

variable "budget_actual_alert_usd" {
  description = "Alert when actual monthly spend exceeds this amount."
  type        = number
  default     = 5
}

variable "github_repository" {
  description = "owner/name of the repository allowed to deploy the jobs image."
  type        = string
  default     = "ScrambledFox/counting-down-backend-fastapi"
}

variable "github_environment" {
  description = "GitHub environment whose workflow runs may assume the deploy role."
  type        = string
  default     = "jobs-production"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false if the account already has one."
  type        = bool
  default     = true
}

variable "ecr_retained_images" {
  description = "Deployed images kept for rollback. Must exceed the Lambda versions CI may roll back to."
  type        = number
  default     = 10
}
