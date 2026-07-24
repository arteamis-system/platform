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

variable "vm" {
  type = object({
    region       = optional(string, "sgp1")
    size         = optional(string, "s-2vcpu-4gb")
    staging_size = optional(string, "s-1vcpu-2gb")
  })
  default = {}
}

variable "ssh_key_fingerprints" {
  type    = list(string)
  default = []
}

variable "deploy_public_key" {
  type    = string
  default = ""
}

variable "ssh_allowed_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0", "::/0"]
}
