output "ipv4" {
  description = "Elastic IP — this is the VM_HOST environment secret."
  value       = aws_eip.this.public_ip
}

output "id" {
  value = aws_instance.this.id
}
