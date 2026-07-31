output "ipv4" {
  description = "Static external IP — this is the VM_HOST environment secret."
  value       = google_compute_address.this.address
}

output "id" {
  value = google_compute_instance.this.id
}
