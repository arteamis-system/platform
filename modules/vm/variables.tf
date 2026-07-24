variable "project" { type = string }

variable "environment" {
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "region" {
  type    = string
  default = "sgp1"
}

variable "size" {
  type    = string
  default = "s-2vcpu-4gb"
}

variable "image" {
  type    = string
  default = "ubuntu-24-04-x64"
}

variable "ssh_key_fingerprints" {
  description = "Fingerprints of keys allowed to log in interactively."
  type        = list(string)
  default     = []
}

variable "deploy_public_key" {
  description = "Public half of the key CI uses for deploys (VM_SSH_KEY)."
  type        = string
  default     = ""
}

variable "ssh_allowed_cidrs" {
  description = "Who may reach port 22. Narrow this to your egress ranges."
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}
