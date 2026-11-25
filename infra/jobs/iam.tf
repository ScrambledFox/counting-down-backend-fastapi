# --- Jobs function ----------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "jobs" {
  name               = local.name
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "jobs" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.jobs.arn}:*"]
  }

  statement {
    sid     = "ReadOwnParameters"
    actions = ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"]
    resources = [
      "arn:${local.partition}:ssm:${var.aws_region}:${local.account_id}:parameter${local.ssm_parameter_path}",
      "arn:${local.partition}:ssm:${var.aws_region}:${local.account_id}:parameter${local.ssm_parameter_path}/*",
    ]
  }

  statement {
    sid       = "DecryptParametersViaSsmOnly"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    sid     = "ReadImagesAndThumbnails"
    actions = ["s3:GetObject"]
    resources = [
      "arn:${local.partition}:s3:::${var.s3_bucket_name}/${var.s3_image_prefix}*",
      "arn:${local.partition}:s3:::${var.s3_bucket_name}/${var.s3_thumbnail_prefix}*",
    ]
  }

  statement {
    sid       = "WriteThumbnailsOnly"
    actions   = ["s3:PutObject"]
    resources = ["arn:${local.partition}:s3:::${var.s3_bucket_name}/${var.s3_thumbnail_prefix}*"]
  }

  # Lets HeadObject distinguish "missing" (404) from "forbidden" (403), within the same prefixes.
  statement {
    sid       = "ListImagePrefixes"
    actions   = ["s3:ListBucket"]
    resources = ["arn:${local.partition}:s3:::${var.s3_bucket_name}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.s3_image_prefix}*", "${var.s3_thumbnail_prefix}*"]
    }
  }
}

resource "aws_iam_role_policy" "jobs" {
  name   = local.name
  role   = aws_iam_role.jobs.id
  policy = data.aws_iam_policy_document.jobs.json
}

# --- Scheduler --------------------------------------------------------------------------------

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "invoke_live" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_alias.live.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invoke-live-alias"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.invoke_live.json
}

# --- Heroku wake-ups --------------------------------------------------------------------------
# Invoke-only identity for the Heroku API. Its access key is created manually
# (`aws iam create-access-key`) and set on Heroku, so the secret never enters state.

resource "aws_iam_user" "heroku_wakeup" {
  name = "${local.name}-heroku-wakeup"
}

resource "aws_iam_user_policy" "heroku_wakeup" {
  name   = "invoke-live-alias"
  user   = aws_iam_user.heroku_wakeup.name
  policy = data.aws_iam_policy_document.invoke_live.json
}
