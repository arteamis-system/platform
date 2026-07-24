output "role_arn" {
  description = "Set this as the AWS_ROLE_ARN variable in the infra repo (and app repos that need AWS)."
  value       = aws_iam_role.deploy.arn
}

output "oidc_provider_arn" {
  value = local.oidc_provider_arn
}
