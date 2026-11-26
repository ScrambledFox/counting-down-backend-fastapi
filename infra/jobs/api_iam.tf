resource "aws_iam_role" "api" {
  name               = local.api_name
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }

  statement {
    sid     = "ReadOwnParameters"
    actions = ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"]
    resources = [
      "arn:${local.partition}:ssm:${var.aws_region}:${local.account_id}:parameter${local.api_ssm_parameter_path}",
      "arn:${local.partition}:ssm:${var.aws_region}:${local.account_id}:parameter${local.api_ssm_parameter_path}/*",
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

  # Read for downloads and presigned GETs; write for presigned upload forms (originals) and
  # advent thumbnails. No delete: the application never deletes stored images.
  statement {
    sid     = "ReadWriteImagesAndThumbnails"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [
      "arn:${local.partition}:s3:::${var.s3_bucket_name}/${var.s3_image_prefix}*",
      "arn:${local.partition}:s3:::${var.s3_bucket_name}/${var.s3_thumbnail_prefix}*",
    ]
  }

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

  statement {
    sid       = "WakeJobs"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_alias.live.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = local.api_name
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}
