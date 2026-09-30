# platform

Shared CI/CD for every `arteamis-system` repo.
- It is a fork of `devsecops-playground-org/platform`.
- It lives in this org because GitHub passes empty secrets to a reusable workflow in a different org.
- **This repo is production for every other repo. A bad change breaks everyone's pipeline.**

## How an app repo uses it

- **The app repo carries two files:**
  - `.platform.yml`: the manifest. Its schema and defaults are in `actions/load-manifest/`.
  - `.github/workflows/ci.yml`: a stub that calls `.github/workflows/_dispatch.yml`, pinned to a commit.
- **`_dispatch.yml` runs these stages in order:**
  1. **manifest**
  2. **`security-gate.yml`:** gitleaks over the full history, semgrep, trivy fs (fails on HIGH/CRITICAL), checkov.
  3. **`ci-test.yml`:** the manifest's `test.lint`, then `test.command`, then the coverage gate, then an optional AI review.
  4. **`build-scan-sign.yml`:** buildx to GHCR, trivy image scan (fails on CRITICAL), syft SBOM, cosign signing. An image already built for the same commit is re-tagged, not rebuilt.
  5. **`deploy-vm.yml` or `deploy-vercel.yml`**
  6. **Optional soak:** `tester-agent.yml`.
  7. **Summary.**
- **The environment is chosen from the pushed branch** (`actions/load-manifest/parse.sh`):
  - A push or manual run on a branch listed under `deploy.environments` deploys to that environment.
  - A pull request never deploys.
  - Soak runs only after a staging deploy, and only when the tester is enabled. Neither app repo enables it.
- **`deploy-vm.yml` steps:**
  1. Validate the environment's secrets.
  2. Verify the image with cosign.
  3. Ship the compose file and a `.env`. The `.env` comes from `actions/inject-secrets`, using Infisical or GitHub environment secrets.
  4. Pin the image digest.
  5. Run `docker compose pull`, then `up -d --no-deps --force-recreate <service>`.
  6. Wait for the health check.
  7. On failure, roll back to the previous image.

## Other folders

- `actions/`: composite actions: `load-manifest`, `setup-runtime`, `coverage-gate`, `ai-review`, `inject-secrets`, `cloud-oidc-login`, `report-findings` (Node).
- `modules/`: Terraform.
  - VMs: `vm` (DigitalOcean), `vm-aws`, `vm-gcp`.
  - Also: `aws-oidc`, `gcp-oidc`, `cloudflare-dns`, `ghcr-access`, `project`.
  - `terraform-apply.yml` plans on pull requests and applies on merge.
- `scaffolder/`, `scaffolder-infra/`: copier templates for a new repo and for its infrastructure.
- `policy/`: gitleaks baseline, branch-protection JSON, OPA deploy rules, tester report schema.
- `shared-services/`: Traefik (automatic HTTPS) and Postgres 16, shared by every component on a project VM.
- `tester-agent/`: the soak and monitor agent. It has its own `AGENTS.md`.

## Changing the platform

- **Every internal `uses:` must point at `arteamis-system/platform`.** After rebasing on upstream, re-apply that rewrite.
- **`selftest.yml` checks:**
  - actionlint
  - shellcheck on `actions/*/*.sh`
  - manifest-parser cases
  - the tester-agent build and tests
  - findings-routing tests
- **Run the same checks locally:**
  ```bash
  actionlint
  shellcheck actions/*/*.sh
  (cd tester-agent && npm ci && npm run typecheck && npm run test:ci && npm run build)
  (cd actions/report-findings && node --test)
  ```
- **To release:**
  1. Merge to `main` and verify.
  2. Move the tag: `git tag -f v1 && git push -f origin v1`.
  3. App repos then bump the pinned SHA in their `ci.yml` deliberately, after reading the diff.
- **Caveat:** on `main`, `_dispatch.yml` calls its stages with `@v1`, so a pinned dispatcher still runs whatever `v1` points at. Branch `fix/reclaim-disk-before-pull` pins the stages by SHA instead.
- **`CODEOWNERS`:** @FromSunNews owns everything.
- **`.pre-commit-config.yaml`** is the same file the scaffolder seeds into new repos. It runs:
  - gitleaks
  - private-key and merge-conflict checks
  - whitespace and end-of-file fixes
  - YAML checks
  - a check for files over 2 MB

## Branch state (checked 2026-09-30)

- **`main` = tag `v1` = `30b465c`.** Backend and frontend `dev` and `main` pin it.
- **`fix/reclaim-disk-before-pull`:** 6 commits, including `fix/ghcr-deploy-auth-preflight`. Backend `deploy/prod` pins `033d7e4` on this branch. It is not merged.
- **PR #1, `fix/cosign-verify-actually-verifies`:** open. On `main`, the signature check has three problems:
  - `continue-on-error: true`
  - no registry login
  - an identity pattern that can never match
- **PR #2, `perf/registry-build-cache`:** open.
