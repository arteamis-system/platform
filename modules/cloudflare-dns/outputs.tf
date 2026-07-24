output "hostnames" {
  description = "Fully qualified names this module manages."
  value       = [for r in cloudflare_dns_record.this : r.name]
}
