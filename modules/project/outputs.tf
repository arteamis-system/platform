output "vm_hosts" {
  description = "environment => public IP. Copy these into each repo's VM_HOST environment secret."
  value       = { for env, vm in local.vm : env => vm.ipv4 }
}

output "hostnames" {
  description = "Every DNS name this project owns."
  value       = module.dns.hostnames
}

output "registry_instructions" {
  value = module.registry.instructions
}
