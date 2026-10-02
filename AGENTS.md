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
  5. **`deploy-vm.yml` or `deploy-vercel.yml`**
  6. **Optional soak:** `tester-agent.yml`.
  7. **Summary.**
- **The environment is chosen from the pushed branch** (`actions/load-manifest/parse.sh`):
  - A push or manual run on a branch listed under `deploy.environments` deploys to that environment.
  - A pull request never deploys.
  - Soak runs only after a staging deploy, and only when the tester is enabled. Neither app repo enables it.
- **`deploy-vm.yml` steps:**
  1. Validate the environment's secrets.
  2. Attempt the configured cosign image check (the current `main` check has the blocking caveats listed below; do not claim it enforces verification).
  3. Ship the compose file and a `.env`. The `.env` comes from `actions/inject-secrets`, using Infisical or GitHub environment secrets.
  4. Pin the image digest.
  5. Run `docker compose pull`, then `up -d --no-deps --force-recreate <service>`.
  6. Wait for the health check.
  7. On failure, roll back to the previous image.
- **Backend migrations require a separate release sequence.** The VM workflow's service-only `--no-deps` rollout does not run the brain backend's bootstrap/migration/helper-finalization phases or restart its worker. Read `../arteamis-backend/docs/rls-test-provisioning.md`; a release with schema/helper changes must complete those phases before traffic/workers, with the release image digest pinned throughout.

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
- **To release:**
  1. Merge to `main` and verify.
  2. Move the tag: `git tag -f v1 && git push -f origin v1`.
  3. App repos then bump the pinned SHA in their `ci.yml` deliberately, after reading the diff.
- **Caveat:** on `main`, `_dispatch.yml` calls its stages with `@v1`, so a pinned dispatcher still runs whatever `v1` points at. Branch `fix/reclaim-disk-before-pull` pins the stages by SHA instead.
  - Inspect nested reusable workflows and composite-action pins too before describing the entire dependency tree as immutable. Moving `v1` affects existing callers even before their dispatcher SHA is bumped; agree a platform release explicitly.
- **`CODEOWNERS`:** @FromSunNews owns everything.
- **`.pre-commit-config.yaml`** is the same file the scaffolder seeds into new repos. It runs:
  - gitleaks
  - private-key and merge-conflict checks
  - whitespace and end-of-file fixes
  - YAML checks
  - a check for files over 2 MB

## Branch state (checked 2026-10-02 after fetching origin)

- **Tag `v1` = `30b465c`.** Backend and frontend `dev` and `main` pin it. `main` can be ahead of `v1`, because the tag moves only when you release.
- **`fix/reclaim-disk-before-pull`:** 6 commits, including `fix/ghcr-deploy-auth-preflight`. Backend `deploy/prod` pins `033d7e4` on this branch. It is not merged.
- **PR #1, `fix/cosign-verify-actually-verifies`:** open. On `main`, the signature check has three problems:
  - `continue-on-error: true`
  - no registry login
  - an identity pattern that can never match
- **PR #2, `perf/registry-build-cache`:** open.
- Before this refresh, local `main` at `b67ad8b` was two guidance commits ahead of `origin/main`; those commits and this refresh do not move `v1`. Recheck refs/pins and PR state before relying on this snapshot.
