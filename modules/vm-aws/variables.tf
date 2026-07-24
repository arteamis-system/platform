variable "project" { type = string }

variable "environment" {
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "disk_gb" {
  type    = number
  default = 20
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
