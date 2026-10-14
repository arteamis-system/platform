# platform

Shared CI/CD used by the brain backend and website frontend in `arteamis-system`. Plane has its own desktop workflows, and the product-docs repo has no application pipeline.
- It is a fork of `devsecops-playground-org/platform`.
- It lives in this org because GitHub passes empty secrets to a reusable workflow in a different org.
- **Its shared workflows are production dependencies for their callers. A bad change can break every caller's pipeline.**

Work from `main`, read the workspace guide, and preserve local commits. Use a topic branch for changes unless the user explicitly asks to finish on `main`; documentation-only work may use `docs/<topic>`. Run commands from this repo or the named package below.

## How an app repo uses it

- **The app repo carries two files:**
  - `.platform.yml`: the manifest. Its schema and defaults are in `actions/load-manifest/`.
  - `.github/workflows/ci.yml`: a stub that calls `.github/workflows/_dispatch.yml`, pinned to a commit.
- **`_dispatch.yml` runs these stages in order:**
  1. **manifest**
  2. **`security-gate.yml`:** gitleaks over the full history, semgrep, trivy fs (fails on HIGH/CRITICAL), checkov.
  3. **`ci-test.yml`:** the manifest's `test.lint`, then `test.command`, then the coverage gate, then an optional AI review.
  4. **`build-scan-sign.yml`:** buildx to GHCR, trivy image scan (fails on CRITICAL), syft SBOM, cosign signing. An image already built for the same commit is re-tagged, not rebuilt.
  5. **`deploy-vm.yml`, `deploy-vercel.yml` or `deploy-mirror.yml`**, each recording the release as a GitHub deployment (`task=release`) with the image or mirror, the source commit and the platform revision.
  6. **Optional soak:** `tester-agent.yml`.
  7. **Summary.**
- **The environment is chosen from the ref** (`actions/load-manifest/parse.sh`):
  - `trigger: push` (the default): a push or manual run on the environment's branch deploys to it.
  - `trigger: dispatch`: only a manual run on that branch whose `deploy_environment` input names the environment deploys. Production from `main` uses this, so a merge to `main` runs the gates without releasing.
  - A pull request never deploys.
  - Soak runs only after a staging deploy, and only when the tester is enabled. Neither app repo enables it.
- **`deploy-vm.yml` steps:**
  1. Validate the environment's secrets, then verify the image signature with cosign; an unverifiable image fails the deploy.
  2. Preflight-pull the digest on the VM (after reclaiming disk).
  3. Ship the compose file, `deploy.ship` paths, the `.env` (from `actions/inject-secrets`) and `.env.infra` (from the `VM_ENV_INFRA` secret, never part of `.env`).
  4. Pin the image digest.
  5. Without `deploy.phases`: `up -d --no-deps --force-recreate <service>`, wait for health, roll back to the previous image on failure.
  6. With `deploy.phases`: stop `deploy.services`, run the phases and services in compose dependency order, wait for health. A failure before `deploy.migration_phase` starts rolls the services back; after it, services stay stopped for a person, because a container swap does not undo a migration.
  7. Record the release.

## Other folders

- `actions/`: composite actions: `load-manifest`, `setup-runtime`, `coverage-gate`, `ai-review`, `inject-secrets`, `cloud-oidc-login`, `report-findings` (Node).
- `modules/`: Terraform.
  - VMs: `vm` (DigitalOcean), `vm-aws`, `vm-gcp`.
  - Also: `aws-oidc`, `gcp-oidc`, `cloudflare-dns`, `ghcr-access`, `project`.
  - `terraform-apply.yml` is a reusable workflow; its caller decides when it runs. It plans first and applies only when the caller sets `apply: true`, subject to the selected environment's gate. It does not independently trigger on a merge.
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
  - report-schema acceptance/rejection cases
  - Terraform format and validation for every module
- **Run the same checks locally:**
  ```bash
  actionlint -shellcheck=
  shellcheck actions/*/*.sh
  (cd tester-agent && npm ci && npm run typecheck && npm run test:ci && npm run build)
  (cd actions/report-findings && node --test)
  node policy/schemas/validate.mjs            # needs Ajv 8 available; CI installs it
  terraform fmt -check -recursive modules/
  ```
  - Manifest-parser cases are inline in `.github/workflows/selftest.yml`, not a standalone test script. They require mikefarah `yq` v4 (CI uses 4.44.3), temporary manifest/output files and explicit event/ref/repo variables. Reproduce service/production, PR/no-deploy and invalid-manifest cases when changing the parser.
  - For Terraform changes, also run `terraform init -backend=false -input=false` and `terraform validate` inside each affected `modules/<name>/`. Local module validation is not a cloud plan/apply or rollout.
  - Keep dependency directories, generated manifests and test output out of commits. Guidance-only changes need path/command verification and `git diff --check`, not deployment or cloud mutation.
- **To release a platform change:**
  1. Merge the component change to `main` and verify `selftest`.
  2. In a second change, repoint `_dispatch.yml`'s internal `uses:` (and nested action pins) at that `main` commit, then merge it.
  3. App repos bump the `_dispatch.yml@<sha>` pin in their `ci.yml` deliberately, after reading the diff.
  - Pins are commit SHAs, not `v1`: a tag can be moved silently and every caller inherits secrets. `v1` remains for older callers only.
- **`CODEOWNERS`:** @FromSunNews owns everything.
- **`.pre-commit-config.yaml`** is the same file the scaffolder seeds into new repos. It runs:
  - gitleaks
  - private-key and merge-conflict checks
  - whitespace and end-of-file fixes
  - YAML checks
  - a check for files over 2 MB

## Branch state (checked 2026-10-14)

- PRs #1 (signature enforcement), #2 (registry build cache), #4 (guidance) and #5 (GHCR auth and disk reclaim, previously deployed from `fix/reclaim-disk-before-pull`) are merged into `main`. Their branches are kept until callers re-pin.
- Tag `v1` = `30b465c` is unchanged.
