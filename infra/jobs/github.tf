# GitHub Actions deploys new images through OIDC: no long-lived AWS keys in GitHub.
# Only workflow runs in the protected GitHub environment var.github_environment may assume the
# role, which also keeps pull requests from forks of this public repository out.

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = (
    var.create_github_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
    : data.aws_iam_openid_connect_provider.github[0].arn
  )
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.github_environment}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${local.name}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600
}

# CI owns code only: push images, update code, publish versions, smoke-test a version and move
# the alias. It cannot change configuration, permissions, the schedule or delete anything.
data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "PushJobsImages"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.jobs.arn]
  }

  statement {
    sid = "DeployCode"
    actions = [
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:ListVersionsByFunction",
      "lambda:PublishVersion",
      "lambda:UpdateFunctionCode",
    ]
    resources = [aws_lambda_function.jobs.arn]
  }

  statement {
    sid       = "SmokeTestPublishedVersions"
    actions   = ["lambda:InvokeFunction"]
    resources = ["${aws_lambda_function.jobs.arn}:*"]
  }

  # Lambda authorizes alias reads and updates against the function ARN, not the alias ARN.
  # The function has a single alias (live), so this still covers only that alias.
  statement {
    sid       = "MoveLiveAlias"
    actions   = ["lambda:GetAlias", "lambda:UpdateAlias"]
    resources = [aws_lambda_function.jobs.arn, aws_lambda_alias.live.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "deploy-jobs-code"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
