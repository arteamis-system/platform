variable "gcp_project_id" {
  description = "GCP project id the pool and deploy service account live in."
  type        = string
}

variable "org" {
  description = "GitHub organisation. Only tokens from this org's repos may use the pool."
  type        = string
  default     = "devsecops-playground-org"
}

variable "pool_id" {
  type    = string
  default = "github-actions"
}

variable "provider_id" {
  type    = string
  default = "github"
}

variable "sa_account_id" {
  description = "Account id (local part) of the deploy service account the pipeline impersonates."
  type        = string
  default     = "github-actions-deploy"
}

variable "allowed_repositories" {
  description = "Repos allowed to impersonate the deploy SA, e.g. [\"devsecops-playground-org/infra\"]."
  type        = list(string)
  default     = ["devsecops-playground-org/infra"]
}

variable "sa_roles" {
  description = "Project roles granted to the deploy SA — what the infra pipeline needs to provision VMs. Tighten if you want a narrower blast radius."
  type        = list(string)
  default = [
    "roles/compute.admin",         # instances, addresses, firewalls
    "roles/iam.serviceAccountUser" # attach a SA to an instance, if ever needed
  ]
}
