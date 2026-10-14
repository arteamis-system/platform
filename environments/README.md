# Arteamis environments

`production/` adopts the observed AWS EC2 host, security group, Elastic IP and
attached data volume through explicit imports. The read-only plan on 2026-10-14
contained five imports and no resource changes. This root has not been applied.
Its S3 backend uses native lockfiles and encryption; copy `backend.hcl.example`
and supply the reviewed state bucket after bootstrap. Do not commit Terraform
state, plan files or credentials.

`bootstrap/` proposes the remote-state bucket, with versioning, encryption,
public-access blocking, TLS-only access and destruction protection. It is an
explicit future infrastructure change. Its initial state must be protected and
migrated into the remote backend after creation. The current offsite database
backup provider is retained.

Run `terraform init -backend=false` and `terraform validate` for static validation.
A plan requires authenticated AWS access to account 779035457064. The production
import plan was generated with a temporary local backend so no state bucket or
production resource was modified. Review the final authenticated plan before
any future apply. Do not apply a plan that would replace the host or data disk.

Staging is deferred by the owner. Runtime inventory, restore procedures and
release prerequisites are in [the deployment handoff](../releases/DEPLOYMENT_HANDOFF.md).
