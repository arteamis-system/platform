# A project's application VM on GCP Compute Engine. Mirrors modules/vm-aws
# (AWS EC2) and modules/vm (DigitalOcean) so the project module can target any
# cloud through one interface: same `deploy` user, same /opt/<project> layout,
# same `ipv4` output that becomes the VM_HOST secret.

terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# A static external IP, so rebuilding the instance keeps the same address — the
# GCP equivalent of the AWS Elastic IP.
resource "google_compute_address" "this" {
  project = var.gcp_project_id
  name    = "${var.project}-${var.environment}"
  region  = var.region
}

resource "google_compute_instance" "this" {
  project      = var.gcp_project_id
  name         = "${var.project}-${var.environment}"
  machine_type = var.machine_type
  zone         = var.zone

  tags = ["${var.project}-${var.environment}", "http-server", "https-server"]

  boot_disk {
    initialize_params {
      image = var.image
      size  = var.disk_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.this.address
    }
  }

  # cloud-init provisions the deploy user + docker, exactly like the other clouds.
  # OS Login is disabled so the cloud-init `deploy` user's key is the login path,
  # keeping deploy-vm.yml identical across clouds.
  metadata = {
    user-data = templatefile("${path.module}/cloud-init.yaml", {
      project    = var.project
      deploy_key = var.deploy_public_key
    })
    enable-oslogin = "FALSE"
  }

  labels = {
    project    = var.project
    env        = var.environment
    managed_by = "terraform"
  }

  # Rebuilding the box is a deliberate act, not a drift fix.
  lifecycle {
    ignore_changes = [boot_disk[0].initialize_params[0].image]
  }
}

# SSH restricted to the deploy addresses; HTTP/HTTPS open. Scoped to this
# instance by network tag so it never touches other projects on the network.
resource "google_compute_firewall" "ssh" {
  project = var.gcp_project_id
  name    = "${var.project}-${var.environment}-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = var.ssh_allowed_cidrs
  target_tags   = ["${var.project}-${var.environment}"]
}

resource "google_compute_firewall" "web" {
  project = var.gcp_project_id
  name    = "${var.project}-${var.environment}-web"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["${var.project}-${var.environment}"]
}
