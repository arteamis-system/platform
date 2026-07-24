output "ipv4" {
  description = "Public address — this is the VM_HOST environment secret."
  value       = digitalocean_droplet.this.ipv4_address
}

output "id" {
  value = digitalocean_droplet.this.id
}
