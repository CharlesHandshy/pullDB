// Minimal Terraform example (guidance only) — apply in production account
resource "aws_iam_role" "pulldb_cross_account" {
  name = "pulldb-cross-account-readonly"
  assume_role_policy = file("${path.module}/../policies/pulldb-prod-trust.json")
}

resource "aws_iam_policy" "pulldb_prod_policy" {
  name   = "pulldb-prod-policy"
  policy = file("${path.module}/../policies/pulldb-prod-policy.json")
}

resource "aws_iam_role_policy_attachment" "attach_prod_policy" {
  role       = aws_iam_role.pulldb_cross_account.name
  policy_arn = aws_iam_policy.pulldb_prod_policy.arn
}

// Note: run `terraform init` and `terraform plan` in the production account with proper AWS provider config
