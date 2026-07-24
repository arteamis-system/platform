variable "org" {
  description = "GitHub organisation."
  type        = string
  default     = "devsecops-playground-org"
}

variable "role_name" {
  type    = string
  default = "github-actions-deploy"
}

variable "create_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false if the account already has one."
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of a pre-existing GitHub OIDC provider (when create_oidc_provider = false)."
  type        = string
  default     = ""
}

variable "allowed_subjects" {
  description = "OIDC sub claims allowed to assume the role."
  type        = list(string)
  # infra applies terraform; environment-scoped so only reviewed prod/staging runs qualify.
  default = [
    "repo:devsecops-playground-org/infra:*",
  ]
}
