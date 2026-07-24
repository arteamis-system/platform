# platform

The one place deployment logic exists for every repository in this organisation.

An application repo carries a **manifest** describing what it is and a **stub
workflow** that calls this repo. It carries no pipeline logic of its own. Change
how backends deploy, and you change one file here — not one file per repo.

```
security gate  →  test  →  build · scan · sign  →  deploy
   gitleaks         the only          trivy            vm (compose)
   semgrep          per-repo          syft SBOM        or vercel (cli)
   trivy fs         variation         cosign sign
   checkov
```

---

## Onboarding a repository

Two files. That is the whole contract.

```bash
copier copy gh:devsecops-playground-org/platform ./my-new-repo \
  --data project=novaria --data component=backend --data runtime=go
```

Or drop them in by hand:

**`.platform.yml`** — what this repo *is*:

```yaml
project: tasmil
component: ai
type: service        # service | frontend | contract
runtime: python      # node | python | go | rust | solidity
package_manager: poetry

test:
  command: poetry run pytest --cov=app --cov-report=json
  coverage_min: 60
  ai_review: true

build:
  dockerfile: Dockerfile
  context: .

deploy:
  target: vm         # vm | vercel | none
  service: ai
  container_name: tasmil-ai
  compose_file: docker-compose.prod.yml
  health:
    path: /health
    port: 8000
  environments:
    staging:
      branch: deploy/staging
      url: https://ai.staging.tasmil.dev
    production:
      branch: deploy/prod
      url: https://ai.tasmil.dev
```

**`.github/workflows/ci.yml`** — identical in every repo:

```yaml
name: CI/CD
on:
  push:
    branches: [main, deploy/staging, deploy/prod]
  pull_request:
  workflow_dispatch:

jobs:
  pipeline:
    uses: devsecops-playground-org/platform/.github/workflows/_dispatch.yml@v1
    permissions:
      contents: read
      packages: write
      id-token: write
      security-events: write
    secrets: inherit
```

Push. That is the onboarding.

---

## The manifest

| field | required | default | meaning |
|---|---|---|---|
| `project` | yes | — | Project family. Groups components that share a VM and a domain. |
| `component` | yes | — | Name within the project. Also the default compose service name. |
| `type` | no | `service` | `service` (container) · `frontend` (Vercel) · `contract` (build + test only) |
| `runtime` | no | `node` | Selects the toolchain: `node` · `python` · `go` · `rust` · `solidity` |
| `package_manager` | no | per runtime | `npm` · `pnpm` · `uv` · `poetry` · `gomod` · `cargo` · `forge` |
| `test.command` | yes | — | **The only thing that differs between repos.** |
| `test.lint` | no | — | Lint/typecheck command, run before the tests. |
| `test.coverage_min` | no | `0` | Pipeline fails below this line coverage. `0` disables the gate. |
| `test.ai_review` | no | `false` | Run the AI reviewer over the diff. |
| `build.dockerfile` / `build.context` | no | `Dockerfile` / `.` | Image build inputs. |
| `build.image` | no | `ghcr.io/<owner>/<repo>` | Override the image name. |
| `deploy.target` | no | `none` | `vm` · `vercel` · `none` |
| `deploy.service` | no | `component` | Compose service to recreate. |
| `deploy.container_name` | no | `project-component` | Container the health check watches. |
| `deploy.compose_file` | no | `docker-compose.prod.yml` | Shipped to the VM as `docker-compose.yml`. |
| `deploy.remote_path` | no | `/opt/<project>/<component>` | Deploy directory on the VM. |
| `deploy.environments.<env>.branch` | yes\* | — | Pushing this branch deploys to `<env>`. |
| `deploy.environments.<env>.url` | no | — | Shown on the GitHub deployment. |

\* required for any environment you want to deploy to.

Branches decide environments. A pull request never deploys.

---

## What lives here

```
.github/workflows/
  _dispatch.yml        the brain — reads the manifest, runs the right stages
  security-gate.yml    gitleaks · semgrep · trivy fs · checkov
  ci-test.yml          the standardised test contract
  build-scan-sign.yml  buildx → trivy → syft SBOM → cosign sign + attest
  deploy-vm.yml        ship compose → pull → recreate one service → health → rollback
  deploy-vercel.yml    vercel pull · build · deploy --prebuilt · alias
  terraform-apply.yml  fmt → validate → plan on PR → apply on merge
actions/
  load-manifest/       the manifest schema, in one script
  setup-runtime/       node · python · go · rust · solidity toolchains
  coverage-gate/       reads any coverage format, enforces the floor
  cloud-oidc-login/    aws · gcp · azure · digitalocean behind one interface
  inject-secrets/      runtime secrets from Infisical
  ai-review/           opt-in AI review of the diff
modules/               terraform: cloudflare-dns · vm · ghcr-access · project
scaffolder/            copier template for a new repo
policy/                gitleaks baseline · branch protection · OPA deploy rules
```

---

## Secrets

Two tiers. Neither of them is "paste a key into a repo".

**Cloud access is keyless.** Workflows request a short-lived OIDC token from
GitHub and exchange it for temporary cloud credentials. The trust policy lives in
the cloud and is scoped to `repo:devsecops-playground-org/<repo>:environment:production`,
so a staging run cannot touch production infrastructure.

**Application secrets come from a manager.** `inject-secrets` pulls them from
Infisical, scoped by project and environment. Where Infisical is not configured,
the platform falls back to GitHub Environment secrets.

**Environments are the enforcement point.** Secret names are identical in every
repo — `VM_HOST`, `VM_USER`, `VM_SSH_KEY`, `VERCEL_TOKEN` — and are scoped to the
`staging` or `production` environment. Production carries a required reviewer, so
a push to `deploy/prod` pauses for a human before anything changes.

| secret | scope | needed by |
|---|---|---|
| `VM_HOST` `VM_USER` `VM_SSH_KEY` | environment | every `target: vm` repo |
| `VM_PORT` | environment | optional, defaults to 22 |
| `GHCR_PULL_TOKEN` | environment | only if the image package is private |
| `VERCEL_TOKEN` `VERCEL_ORG_ID` `VERCEL_PROJECT_ID` | environment | every `target: vercel` repo |
| `INFISICAL_CLIENT_ID` `INFISICAL_CLIENT_SECRET` | organisation | optional secrets manager |
| `ANTHROPIC_API_KEY` | organisation | only when `ai_review: true` |
| `SOPS_AGE_KEY` | infra repo | decrypting Terraform variables |

Nothing here is ever committed. Three gates make sure of it: the pre-commit hook
on the developer's machine, GitHub push protection at the organisation level, and
gitleaks over full history in the security gate.

---

## Selective deploys

Components are separate repositories, so pushing `deploy/prod` on `tasmil-ai`
triggers only the AI pipeline. On a shared VM each component owns
`/opt/<project>/<component>` and is recreated with `--no-deps`, so rolling the AI
service leaves `backend` and `mcp` running untouched. Image pruning is restricted
to dangling layers for the same reason.

## Promotion

An image is built once per commit. When that commit reaches `deploy/prod`, the
build stage finds the existing digest and re-tags it rather than rebuilding, so
production runs exactly the bytes that passed staging.

---

## Changing the platform

This repository is production for every other repository. A bad change here
breaks everyone's deploys.

- Stubs pin `@v1`. Never point a stub at `@main`.
- Merge to `main`, verify, then move the tag deliberately:
  ```bash
  git tag -f v1 && git push -f origin v1
  ```
- `CODEOWNERS` requires review on workflows, actions, modules and policy.
