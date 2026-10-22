# platform

Shared CI/CD for the `arteamis-system` repositories. Backend (VM), web (mirror) and landing (Vercel) call `_dispatch.yml`; web also runs `ci-browser.yml`. Desktop uses `ci-desktop.yml` and `release-desktop.yml`; product uses `docs-check.yml` and has no application runtime. The organization profile has no workflow.
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
  4. **`build-scan-sign.yml`** (deploying `vm` targets only): buildx to GHCR, trivy image scan (fails on CRITICAL), syft SBOM, cosign signing. An image already built for the same commit is re-tagged, not rebuilt.
  5. **`deploy-vm.yml`, `deploy-vercel.yml` or `deploy-mirror.yml`**, each recording the release as a GitHub deployment (`task=release`) with the image or mirror, the source commit and the platform revision.
  6. **Optional soak:** `tester-agent.yml`.
  7. **Summary.**
- **The environment is chosen from the ref** (`actions/load-manifest/parse.sh`):
  - `trigger: push` (the default): a push or manual run on the environment's branch deploys to it.
  - `trigger: dispatch`: only a manual run on that branch whose `deploy_environment` input names the environment deploys. Production from `main` uses this, so a merge to `main` runs the gates without releasing.
  - A pull request never deploys.
  - Soak runs only after a staging deploy, and only when the tester is enabled. No Arteamis manifest enables it.
- **Production entry points differ by caller.** Landing's manual `release.yml` calls `_dispatch.yml` with `deploy_environment: production`, so every gate runs. Backend's and web's manual `release.yml` call `load-manifest` (production, main and `workflow_dispatch` only) and then only `build-scan-sign.yml` + `deploy-vm.yml` (backend) or `deploy-mirror.yml` (web). They do not repeat the security/test stages, by owner direction on 2026-10-16; those gates run in each repo's `ci.yml`.
- **`deploy-vm.yml` steps:**
  1. Validate the environment's secrets, then verify the image signature with cosign; an unverifiable image fails the deploy.
  2. Preflight-pull the digest on the VM (after reclaiming disk), then run the manifest's `deploy.preflight` command there. A failed preflight leaves the VM unchanged.
  3. Ship the compose file, `deploy.ship` paths, the `.env` (from `actions/inject-secrets`) and `.env.infra` (from the `VM_ENV_INFRA` secret, never part of `.env`). A `platform:<path>` compose file is read from the platform revision running the deploy, e.g. `environments/production/backend.compose.yml`; backend still ships its own `docker-compose.prod.yml`.
  4. Pin the image digest.
  5. Without `deploy.phases`: `up -d --no-deps --force-recreate <service>`, wait for health, roll back to the previous image on failure.
  6. With `deploy.phases`: stop `deploy.services`, run the phases and services in compose dependency order, wait for health. A failure before `deploy.migration_phase` starts rolls the services back; after it, services stay stopped for a person, because a container swap does not undo a migration.
  7. Record the release.

## Other folders

- `dev-tools/git-ui/`: portable Ungit launcher for local commit graphs and diffs. Run `./git-ui.sh`, verify HTTP health, then provide http://127.0.0.1:8449. It discovers Git checkouts beside platform; `--root` and repeated `--repo` select other layouts. Follow `dev-tools/git-ui/README.md` for requirements and checks.
- Client/document workflows: `ci-desktop.yml`, `release-desktop.yml`, `ci-browser.yml` and `docs-check.yml`. Application repositories keep pinned entry points. Desktop release is manual, main-only and runs on hosted `macos-15` (no AWS fallback). It defaults to an unsigned/ad-hoc build saved as a 14-day review artifact; `publish: true` also creates an internal GitHub pre-release.
- `ci-runner/`: the ephemeral AWS runner fallback (Python/CloudFormation controller, reaper, AMI bake, provisioning and qualification). Read `ci-runner/README.md`, then the dated `LIVE.md` operating record, before changing it or any `runs-on`. Its workflows are `ci-runner-canary.yml` (secretless qualification), `ci-hosted-probe.yml` (hosted recovery probe) and `ci-runner-tests.yml`. `ci-runner/.build/` and `generated/` are ignored local review artifacts.
- **Linux job routing:** every Linux `runs-on` uses the `vars.ARTEAMIS_CI_RUNNERS` selector expression, which stays on hosted `ubuntu-24.04` for platform's own jobs, fork PRs and an absent variable. Copy that expression and a `timeout-minutes` of at most 45 into any new Linux job. `ci-runner/routing.py check` (from the ci-runner venv) verifies this across the sibling workspace checkouts; macOS jobs and the fixed hosted probe are exempt.
- `environments/`: Terraform roots. `production/` imports the existing AWS host, security group, Elastic IP and data volume and holds the canonical `backend.compose.yml` assembly; `bootstrap/` proposes the remote-state bucket. Neither has been applied.
- `ops/`: `check-production.py` (read-only production checks), `check-compose.py`, and `restore-backup.sh` (restores only into a new disposable container); `production-inventory.json` records dated read-only checks.
- `releases/`: `DEPLOYMENT_HANDOFF.md` and the dated 2026-10-14 source-integration, feature and branch inventories. Add new dated records; do not rewrite old evidence.
- `scripts/check_internal_pins.py`: resolves every internal `uses:` pin (selftest runs it).
- `actions/`: composite actions: `load-manifest`, `setup-runtime`, `coverage-gate`, `ai-review`, `inject-secrets`, `cloud-oidc-login`, `docs-check`, `report-findings` (Node).
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
- **`selftest.yml` checks** (its aggregate `selftest` job requires all four jobs):
  - actionlint, and resolution of every internal action/workflow SHA and path
  - documentation checker and `ops/` tests, `restore-backup.sh` syntax, and the production compose assembly check
  - shellcheck on `actions/*/*.sh` and `ops/*.sh`
  - manifest-parser cases
  - the tester-agent build and tests
  - findings-routing tests
  - report-schema acceptance/rejection cases
  - Terraform format and validation for every module and environment root
- Path-filtered workflows add `ci-runner-tests.yml` (unit tests, generated templates, cfn-lint, bake shellcheck, offline cosign signing proof) and `git-ui-tests.yml`.
- **Run the same checks locally:**
  ```bash
  python3 scripts/check_internal_pins.py
  python3 -m unittest discover -s actions/docs-check -p 'test_*.py'
  python3 -m unittest discover -s ops -p 'test_*.py'
  actionlint -shellcheck=
  shellcheck actions/*/*.sh ops/*.sh
  (cd tester-agent && npm ci && npm run typecheck && npm run test:ci && npm run build)
  (cd actions/report-findings && node --test)
  node policy/schemas/validate.mjs            # needs Ajv 8 available; CI installs it
  terraform fmt -check -recursive modules/ environments/
  ```
  - `ci-runner/README.md` lists the ci-runner checks; `dev-tools/git-ui/README.md` lists the Git browser checks.
  - Manifest-parser cases are inline in `.github/workflows/selftest.yml`, not a standalone test script. They require mikefarah `yq` v4 (CI uses 4.44.3), temporary manifest/output files and explicit event/ref/repo variables. Reproduce service/production, PR/no-deploy and invalid-manifest cases when changing the parser.
  - For Terraform changes, also run `terraform init -backend=false -input=false` and `terraform validate` inside each affected `modules/<name>/`. Local module validation is not a cloud plan/apply or rollout.
  - Keep dependency directories, generated manifests and test output out of commits. Guidance-only changes need path/command verification and `git diff --check`, not deployment or cloud mutation.
- **To release a platform change:**
  1. Merge the component change to `main` and verify `selftest`.
  2. In a second change, repoint `_dispatch.yml`'s internal `uses:` (and nested action pins) at that `main` commit, then merge it.
  3. App repos bump the `_dispatch.yml@<sha>` pin in their `ci.yml` deliberately, after reading the diff.
  - Pins are commit SHAs, not `v1`: a tag can be moved silently and every caller inherits secrets. `v1` remains for older callers only.
  - Current pins (checked 2026-10-22): `_dispatch.yml` and its nested stages at assembly `06fdff6` pin component `6e2ed6c`. Backend, web, landing and product pin `06fdff6`; desktop CI pins `6773d5b` and desktop release pins `d5c8c2d`.
- **`CODEOWNERS`:** @FromSunNews owns everything.
- **`.pre-commit-config.yaml`** is the same file the scaffolder seeds into new repos. It runs:
  - gitleaks
  - private-key and merge-conflict checks
  - whitespace and end-of-file fixes
  - YAML checks
  - a check for files over 2 MB

## Branch and runner state (checked 2026-10-22)

- `main` is `d5c8c2d`. PRs #15 (Git browser) and #17–#25 (AWS runner fallback, live runner record, desktop bundle/`lipo` fixes) merged 2026-10-15 to 2026-10-18. #22–#25 were `[skip ci]` merges, so the last successful `selftest` and `CI runner checks` on main ran on `06fdff6` (runs 39095958193, 39095958111).
- Open: #14 quotes phased-release SSH arguments in `deploy-vm.yml`; backend's `release.yml` carries a quoting adapter until it is released. #16 (desktop app retention) is superseded in substance by #24/#25.
- Every historical branch is preserved. Tag `v1` = `30b465c` is unchanged.
- AWS pool (read-only query): zero pool instances and volumes, zero repository runner registrations, `ARTEAMIS_CI_RUNNERS` absent in backend/web/landing/product, controller schedule disabled, reaper enabled. Successful hosted recovery is unverified; on 2026-10-18 hosted jobs were still rejected by GitHub billing before execution. See `ci-runner/LIVE.md`.
