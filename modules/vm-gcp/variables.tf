variable "project" { type = string }

variable "environment" {
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "gcp_project_id" {
  description = "The GCP project id the instance is created in."
  type        = string
}

variable "region" {
  type    = string
  default = "asia-southeast1"
}

variable "zone" {
  type    = string
  default = "asia-southeast1-a"
}

# Machine type is GCP's equivalent of an AWS instance_type. Named `machine_type`
# so the project module can pass the same `vm.size` string to whichever cloud.
variable "machine_type" {
  type    = string
  default = "e2-small"
}

variable "disk_gb" {
  type    = number
  default = 20
}

variable "image" {
  description = "Boot image family. Canonical's Ubuntu 24.04 LTS by default."
  type        = string
  default     = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
}

variable "deploy_public_key" {
  description = "Public half of the key CI deploys with (VM_SSH_KEY is the private half)."
  type        = string
  default     = ""
}

variable "ssh_allowed_cidrs" {
  description = "Who may reach port 22. Narrow this to your egress ranges."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
