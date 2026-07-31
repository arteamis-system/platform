variable "project" {
  description = "Project family name — matches `project:` in every component manifest."
  type        = string
}

variable "environments" {
  type    = list(string)
  default = ["staging", "production"]
}

variable "domain" {
  description = "Apex domain for this project."
  type        = string
}

variable "dns_zone_id" {
  type = string
}

variable "vm_components" {
  description = "Components that run as containers on the project VM."
  type        = list(string)
  default     = []
}

variable "vm_cloud" {
  description = "Which cloud stands up the VM plane: aws or gcp."
  type        = string
  default     = "aws"
  validation {
    condition     = contains(["aws", "gcp"], var.vm_cloud)
    error_message = "vm_cloud must be aws or gcp."
  }
}

# Per-environment cloud, overriding vm_cloud for the listed envs. Lets a project
# mix clouds — e.g. { staging = "gcp", production = "aws" }.
variable "vm_cloud_overrides" {
  type    = map(string)
  default = {}
  validation {
    condition     = alltrue([for c in values(var.vm_cloud_overrides) : contains(["aws", "gcp"], c)])
    error_message = "vm_cloud_overrides values must be aws or gcp."
  }
}

# Only read when vm_cloud = \"gcp\". The AWS path sets region on the provider in
# the infra root, so it needs nothing here.
variable "gcp_project_id" {
  description = "GCP project id the instances are created in (vm_cloud = gcp)."
  type        = string
  default     = ""
}

variable "gcp_region" {
  type    = string
  default = "asia-southeast1"
}

variable "gcp_zone" {
  type    = string
  default = "asia-southeast1-a"
}

variable "vercel_domains" {
  description = "Hostnames served by Vercel."
  type        = list(string)
  default     = []
}

variable "needs_vm" {
  description = "False for projects that are frontend-only."
  type        = bool
  default     = true
}

# EC2 instance sizing. `size` is the production instance type, `staging_size` the
# smaller staging one. The AWS region is set on the provider in the infra root.
variable "vm" {
  type = object({
    size         = optional(string, "t3.small")
    staging_size = optional(string, "t3.micro")
  })
  default = {}
}

variable "deploy_public_key" {
  type    = string
  default = ""
}

# EC2 security groups take IPv4 CIDRs; the default VPC path here is IPv4-only.
variable "ssh_allowed_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}
