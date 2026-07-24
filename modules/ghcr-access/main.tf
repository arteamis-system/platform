# Read-only registry access for the VMs. Images are public by default in this
# organisation; this module exists for the projects that keep theirs private.

terraform {
  required_version = ">= 1.9"
}

variable "project" { type = string }

variable "packages" {
  description = "GHCR package names this project's VMs may pull."
  type        = list(string)
  default     = []
}

output "instructions" {
  description = "How the VM authenticates to GHCR."
  value       = <<-EOT
    Create a fine-grained token with read:packages scoped to:
      ${join(", ", var.packages)}
    then store it as the GHCR_PULL_TOKEN environment secret in each ${var.project} repo.
    Leave it unset when the packages are public.
  EOT
}
