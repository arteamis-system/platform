# A project's application VM: the droplet plus the firewall that fronts it.
# Components share the box; each one lands in /opt/<project>/<component> and is
# rolled independently by the deploy-vm workflow.

terraform {
  required_version = ">= 1.9"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

resource "digitalocean_droplet" "this" {
  name     = "${var.project}-${var.environment}"
  image    = var.image
  region   = var.region
  size     = var.size
  ssh_keys = var.ssh_key_fingerprints

  monitoring = true
  backups    = var.environment == "production"

  tags = ["project:${var.project}", "env:${var.environment}", "managed-by:terraform"]

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    project    = var.project
    deploy_key = var.deploy_public_key
  })

  lifecycle {
    ignore_changes = [image] # rebuilding the box is a deliberate act, not a drift fix
  }
}

resource "digitalocean_firewall" "this" {
  name        = "${var.project}-${var.environment}"
  droplet_ids = [digitalocean_droplet.this.id]

  # SSH is restricted to the addresses that are allowed to deploy.
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.ssh_allowed_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "53"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
