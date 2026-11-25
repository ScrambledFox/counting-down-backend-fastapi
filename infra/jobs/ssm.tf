# Placeholders only: real values are written with `aws ssm put-parameter --overwrite` and are
# ignored here, so secrets never enter OpenTofu state or plans. The function fails closed at cold
# start until real values are set (push settings are validated in production).
resource "aws_ssm_parameter" "secret" {
  for_each = toset(local.secret_parameters)

  name  = "${local.ssm_parameter_path}/${each.key}"
  type  = "SecureString"
  value = "set-out-of-band"

  lifecycle {
    ignore_changes = [value]
  }
}
