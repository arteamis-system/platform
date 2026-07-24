# DNS as code. Every hostname the organisation owns is a reviewable line in git
# rather than a click in a dashboard nobody can audit.

terraform {
  required_version = ">= 1.9"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

resource "cloudflare_dns_record" "this" {
  for_each = { for r in var.records : "${r.type}-${r.name}" => r }

  zone_id = var.zone_id
  name    = each.value.name
  type    = each.value.type
  content = each.value.value
  ttl     = each.value.proxied ? 1 : each.value.ttl
  proxied = each.value.proxied
  comment = "managed by devsecops-playground-org/infra"
}
