output "workload_identity_provider" {
  description = "Full resource name for google-github-actions/auth's workload_identity_provider input. Set as the GCP_WIF_PROVIDER variable."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "service_account_email" {
  description = "The deploy SA the pipeline impersonates. Set as the GCP_DEPLOY_SA variable."
  value       = google_service_account.deploy.email
}
