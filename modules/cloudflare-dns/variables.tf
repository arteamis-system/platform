variable "zone_id" {
  description = "Cloudflare zone the records belong to."
  type        = string
}

variable "records" {
  description = "Records to manage in this zone."
  type = list(object({
    name    = string
    type    = string
    value   = string
    proxied = optional(bool, true)
    ttl     = optional(number, 300)
  }))
  default = []
}
