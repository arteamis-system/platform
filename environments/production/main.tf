# Adopt the existing host and disk. This root does not provision a replacement.
# Initial import must be reviewed as an import-only plan before application.
resource "aws_instance" "api" {
  ami                    = "ami-0ed6a65b84536f6ce"
  instance_type          = "t3.medium"
  subnet_id              = "subnet-0d1f585f6efd9727e"
  private_ip             = "172.31.5.149"
  key_name               = "arteamis-backend"
  vpc_security_group_ids = [aws_security_group.api.id]
  ebs_optimized          = false
  monitoring             = false

  credit_specification {
    cpu_credits = "unlimited"
  }
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    http_protocol_ipv6          = "disabled"
    instance_metadata_tags      = "disabled"
  }
  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    iops                  = 3000
    throughput            = 125
    encrypted             = true
    delete_on_termination = true
  }
  tags = {
    Name       = "arteamis-backend"
    app        = "arteamis"
    managed-by = "deploy/aws-provision.sh"
  }
  lifecycle {
    prevent_destroy = true
    # Preserve the existing bootstrap and AMI on adoption. Replacing this host is
    # a separately reviewed operation with a tested data-disk recovery plan.
    ignore_changes = [ami, user_data, user_data_base64]
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = "ap-southeast-1c"
  size              = 20
  type              = "gp3"
  iops              = 3000
  throughput        = 125
  encrypted         = true
  tags = {
    Name = "arteamis-data"
    app  = "arteamis"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.api.id
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_eip" "api" {
  domain   = "vpc"
  instance = aws_instance.api.id
  tags = {
    Name = "arteamis-backend"
    app  = "arteamis"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_security_group" "api" {
  name        = "arteamis-backend-sg"
  description = "Arteamis backend: ssh, http, https"
  vpc_id      = "vpc-06e76dae623ec5e0c"
  # Preserve the observed access policy during adoption. Restricting SSH is a
  # separate network change; the current CI deployers have dynamic addresses.
  ingress {
    description = "certbot+redirect"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "api"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "github-actions-deploy"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "nathan-2026-08-24"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["42.117.73.234/32"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  lifecycle {
    prevent_destroy = true
  }
}
