# A project's application VM on AWS EC2. Mirrors modules/vm (DigitalOcean) so the
# project module can target either cloud. Components share the box; each lands in
# /opt/<project>/<component> and is rolled independently by deploy-vm.yml.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

# Latest Ubuntu 24.04 LTS AMI, owned by Canonical — never a hardcoded AMI id.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Default VPC/subnet keep the module self-contained for a playground; a real
# deployment would pass in a dedicated VPC.
data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "this" {
  name        = "${var.project}-${var.environment}"
  description = "managed by devsecops-playground-org/infra"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Project   = var.project
    Env       = var.environment
    ManagedBy = "terraform"
  }
}

# SSH is restricted to the addresses allowed to deploy.
resource "aws_vpc_security_group_ingress_rule" "ssh" {
  for_each          = toset(var.ssh_allowed_cidrs)
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  description       = "ssh (deploy)"
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "http"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "https"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound"
}

resource "aws_instance" "this" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.this.id]

  # The deploy user + docker are provisioned by cloud-init, so a fresh instance
  # is deployable the moment terraform apply finishes.
  user_data = templatefile("${path.module}/cloud-init.yaml", {
    project    = var.project
    deploy_key = var.deploy_public_key
  })

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_size = var.disk_gb
    volume_type = "gp3"
    encrypted   = true
  }

  monitoring = var.environment == "production"

  tags = {
    Name      = "${var.project}-${var.environment}"
    Project   = var.project
    Env       = var.environment
    ManagedBy = "terraform"
  }

  # Rebuilding the box is a deliberate act, not a drift fix.
  lifecycle {
    ignore_changes = [ami]
  }
}

resource "aws_eip" "this" {
  instance = aws_instance.this.id
  domain   = "vpc"

  tags = {
    Name    = "${var.project}-${var.environment}"
    Project = var.project
  }
}
