# "Stand up a project" as a dozen lines. This is the module the scaffolder
# generates a call to, and the reason onboarding project 100 costs the same as
# onboarding project 10.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

locals {
  # Every environment gets its own VM so a staging mistake cannot reach production.
  vm_environments = { for e in var.environments : e => e if var.needs_vm }

  # Service hostnames point at the VM; frontend hostnames point at Vercel.
  service_records = flatten([
    for env, _ in local.vm_environments : [
      for component in var.vm_components : {
        name    = env == "production" ? "${component}.${var.domain}" : "${component}.${env}.${var.domain}"
        type    = "A"
        value   = module.vm[env].ipv4
        proxied = true
        ttl     = 1
      }
    ]
  ])

  frontend_records = [
    for host in var.vercel_domains : {
      name    = host
      type    = "CNAME"
      value   = "cname.vercel-dns.com"
      proxied = false
      ttl     = 300
    }
  ]
}

# The VM plane runs on AWS EC2. modules/vm (DigitalOcean) remains in the tree as
# an alternative, but the project bundle targets AWS per the org's cloud choice.
module "vm" {
  source   = "../vm-aws"
  for_each = local.vm_environments

  project           = var.project
  environment       = each.value
  instance_type     = each.value == "production" ? var.vm.size : var.vm.staging_size
  deploy_public_key = var.deploy_public_key
  ssh_allowed_cidrs = var.ssh_allowed_cidrs
}

module "dns" {
  source = "../cloudflare-dns"

  zone_id = var.dns_zone_id
  records = concat(local.service_records, local.frontend_records)
}

module "registry" {
  source = "../ghcr-access"

  project  = var.project
  packages = [for c in var.vm_components : "${var.project}-${c}"]
}
