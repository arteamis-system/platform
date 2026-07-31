# Keyless GitHub -> GCP access, the GCP twin of modules/aws-oidc. Creates a
# Workload Identity Federation pool that trusts GitHub's OIDC issuer, plus a
# deploy service account the pipeline impersonates at runtime. No service-account
# JSON key is ever created or stored; GitHub mints a short-lived token per run and
# GCP STS exchanges it for a ~1h SA credential, scoped by repo via the binding.
#
# Applied ONCE by an administrator (see infra/bootstrap/gcp-oidc). Its outputs
# become the GCP_WIF_PROVIDER and GCP_DEPLOY_SA variables.

terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.gcp_project_id
  workload_identity_pool_id = var.pool_id
  display_name              = "GitHub Actions"
  description               = "Keyless GitHub -> GCP for the devsecops pipeline"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.gcp_project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  display_name                       = "GitHub"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
  }

  # Only tokens issued to this org's repos may exchange through the pool at all —
  # the first line of defence, before the per-repo SA binding below.
  attribute_condition = "assertion.repository_owner == '${var.org}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deploy" {
  project      = var.gcp_project_id
  account_id   = var.sa_account_id
  display_name = "GitHub Actions deploy"
}

# What the SA may do in the project: manage the compute the vm-gcp module creates.
resource "google_project_iam_member" "sa_roles" {
  for_each = toset(var.sa_roles)
  project  = var.gcp_project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.deploy.email}"
}

# Which identities may impersonate the SA: only the listed repos, matched on the
# repository attribute of the GitHub token. This is the per-repo scoping.
resource "google_service_account_iam_member" "wif" {
  for_each           = toset(var.allowed_repositories)
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${each.value}"
}
