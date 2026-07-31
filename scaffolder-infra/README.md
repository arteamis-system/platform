# scaffolder-infra — the "stand up a project" form

Onboard a whole project's infrastructure and wire its CI/CD in three commands,
instead of hand-copying a per-project deploy kit. This is the infrastructure twin
of [`../scaffolder`](../scaffolder) (which stamps app **repos**): that form makes a
repo know how to build itself; this one makes the **cloud** ready to receive it.

It replaces the manual loop the infra README describes — *"`terraform output vm_hosts`
prints the addresses to copy into each repo's `VM_HOST` secret"* — with a generator
plus one script that does the copying for you.

```
answer the form ──► infra/projects/<name>/   (Terraform: 1 VM/env + DNS + GHCR grant)
                         │
                    terraform apply           (provision on AWS + Cloudflare, keyless)
                         │
              wire-deploy-secrets.sh          (VM_HOST/USER/SSH_KEY → every repo's envs)
                         │
                    git push deploy/staging   (the platform pipeline deploys onto the VM)
```

## 1. Generate the infra declaration

```bash
# from the infra repo root
copier copy --trust \
  gh:devsecops-playground-org/platform//scaffolder-infra \
  projects/novaria \
  --data project=novaria \
  --data domain=novaria.dev \
  --data 'vm_components=["api"]'
```

This writes `projects/novaria/{main.tf,variables.tf,backend.tf,outputs.tf,terraform.tfvars.example}`
— a valid call to the shared [`project`](../modules/project) module. Then two edits by hand:

- add `novaria` to the matrix in `infra/.github/workflows/terraform.yml`
- `cp terraform.tfvars.example terraform.tfvars` and fill `dns_zone_id` + `deploy_public_key`

**The form's questions** (see [`copier.yml`](copier.yml)): `project`, `domain`,
`environments`, `needs_vm`, `vm_components`, `vercel_domains`, `vm_size`,
`vm_staging_size`, `ssh_allowed_cidrs`. Frontend-only projects answer `needs_vm=false`
and get DNS + Vercel records with no VM.

## 2. Provision

Open a PR; the infra pipeline runs `fmt → validate → plan` and comments the plan.
Merge to `main` and the same reviewed plan is applied behind the `production`
approval gate. (Locally: `terraform -chdir=projects/novaria apply`.) Nothing is
applied from a laptop in the real flow.

## 3. Wire the deploy secrets — the handoff, automated

The deploy key is a keypair you generate once per project: the **public** half goes
in `deploy_public_key` (step 1, baked into the VM by cloud-init); the **private**
half becomes the `VM_SSH_KEY` secret this script sets.

```bash
# generate the deploy keypair once
ssh-keygen -t ed25519 -f ~/.ssh/novaria-deploy -C ci-deploy@novaria -N ''
# ...put ~/.ssh/novaria-deploy.pub into terraform.tfvars deploy_public_key, apply, then:

./wire-deploy-secrets.sh --project novaria --key ~/.ssh/novaria-deploy
# preview without writing anything:
./wire-deploy-secrets.sh --project novaria --key ~/.ssh/novaria-deploy --dry-run
```

It reads `terraform output vm_hosts`, finds every `novaria-*` repo whose
`.platform.yml` says `target: vm`, and sets `VM_HOST` / `VM_USER` / `VM_SSH_KEY`
on that repo's **environment** secrets, per environment. After it runs, deploys are
hands-off — a push to `deploy/staging` or `deploy/prod` deploys onto the VM.

Flags: `--user` (VM login, default `ubuntu`), `--org`, `--infra-dir`, `--dry-run`.
Requires `gh` (authenticated, repo-admin scope), `terraform`, `jq`.

## What this does and does not do

- **Does:** generate the per-project Terraform, and close the infra→CI secret handoff
  for VM deploys (the part that was manual copy-paste).
- **Does not:** create the app repos (that's [`../scaffolder`](../scaffolder)), mint
  app-runtime secrets (DB password, JWT, API keys — those belong in the secrets
  manager / per-repo, not here), or move nameservers to Cloudflare (a one-time
  registrar step that cannot be Terraformed).

## Relation to the hand-rolled arteamis deploy kit

`arteamis-system/deploy` is the imperative, single-project version of this: shell +
Terraform that provisions one droplet and a `bootstrap.sh` that hardcodes one
project's repo secrets. This form is the reusable, declarative equivalent — the
same day-0 outcome, discovered from manifests so project #100 costs what #10 did.
