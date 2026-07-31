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
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
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

  # Which cloud each environment lands on. `vm_cloud` is the default for all envs;
  # `vm_cloud_overrides` lets an environment differ — e.g. staging on gcp, prod on
  # aws. Split into per-cloud sets so each provider module only builds its envs.
  cloud_of         = { for e in var.environments : e => try(var.vm_cloud_overrides[e], var.vm_cloud) }
  aws_environments = { for e, _ in local.vm_environments : e => e if local.cloud_of[e] == "aws" }
  gcp_environments = { for e, _ in local.vm_environments : e => e if local.cloud_of[e] == "gcp" }

  # One VM plane, any cloud. Exactly one of these is non-empty (gated on vm_cloud);
  # merging their outputs gives a single { env => { ipv4 } } map the rest of the
  # module reads without caring which provider stood the box up.
  vm = merge(
    { for e, m in module.vm_aws : e => m },
    { for e, m in module.vm_gcp : e => m },
  )

  # Service hostnames point at the VM; frontend hostnames point at Vercel.
  service_records = flatten([
    for env, _ in local.vm_environments : [
      for component in var.vm_components : {
        name    = env == "production" ? "${component}.${var.domain}" : "${component}.${env}.${var.domain}"
        type    = "A"
        value   = local.vm[env].ipv4
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

# The VM plane is cloud-agnostic and can be mixed per environment. Each provider
# module builds only the environments assigned to it (local.aws/gcp_environments);
# both expose the same `ipv4`, merged into local.vm above. modules/vm (DigitalOcean)
# remains in the tree as a third option to wire in the same way.
module "vm_aws" {
  source   = "../vm-aws"
  for_each = local.aws_environments

  project           = var.project
  environment       = each.value
  instance_type     = each.value == "production" ? var.vm.size : var.vm.staging_size
  deploy_public_key = var.deploy_public_key
  ssh_allowed_cidrs = var.ssh_allowed_cidrs
}

module "vm_gcp" {
  source   = "../vm-gcp"
  for_each = local.gcp_environments

  project           = var.project
  environment       = each.value
  gcp_project_id    = var.gcp_project_id
  region            = var.gcp_region
  zone              = var.gcp_zone
  machine_type      = each.value == "production" ? var.vm.size : var.vm.staging_size
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
