# Agent workflow

How an agent works on `platform` end to end using the vendored `pstack` method (`arteamis-method`),
validates shared CI/CD and infrastructure changes locally, and hands over a verified branch. People
push, open PRs, merge, and release; agents commit on local branches only.

## 1. Start a session

1. Branch from `main` using a topic branch (`docs/<topic>` for documentation-only changes) unless
   explicitly instructed otherwise.
2. Read [`AGENTS.md`](../AGENTS.md) (and `tester-agent/AGENTS.md` when touching `tester-agent/`).
3. Load the entry skill
   [`.agents/skills/arteamis-method/SKILL.md`](../.agents/skills/arteamis-method/SKILL.md) (also
   linked at `.claude/skills/arteamis-method/SKILL.md` for Claude Code), resolve `<pstack>` via
   `../desktop/plugins/arteamis/pstack/` or `~/.arteamis/plugin/pstack/`, load the harness adapter,
   and pick one playbook.
4. Read `.agent/progress.md` first if it exists; it is the resume point for long-running work.

## 2. Progress file: `.agent/progress.md`

`.agent/` is git-ignored. For tasks spanning multiple turns or sessions, maintain
`.agent/progress.md` with Goal, Decisions, Done, Next, and the exact commands and results run so a
new session can resume cleanly without guessing.

## 3. Fast static gate: `make check`

Run `make check` early and after every meaningful edit:

```bash
make check
```

`make check` runs:

1. `node scripts/check-pstack.mjs` — verifies required harness files exist, zero `"hooks"` keys in
   JSON under `.agents/` or `.claude/` (PRD X-22), and zero internal workflow/action `uses:`
   pointing at upstream `devsecops-playground-org/platform`.
2. `node --test scripts/*.node-tests.mjs` — runs unit tests for the pstack harness checks.
3. `git diff --check` — catches conflict markers and trailing whitespace.
4. Optional local linters when installed on `PATH`: `actionlint -shellcheck=`,
   `shellcheck actions/*/*.sh`, and `terraform fmt -check -recursive modules/`.

## 4. Full verification: `make verify`

Run `make verify` before handing over:

```bash
make verify
```

`make verify` runs `make check` followed by `(cd actions/report-findings && node --test)`.

When touching specific subsystems, also run the matching local `selftest.yml` checks:

- **Internal workflow/action pins:** `python3 scripts/check_internal_pins.py`
- **Documentation checker / ops:** `python3 -m unittest discover -s actions/docs-check -p 'test_*.py'`
  and `python3 -m unittest discover -s ops -p 'test_*.py'`
- **Tester agent:** `(cd tester-agent && npm ci && npm run typecheck && npm run test:ci && npm run build)`
- **Report schema:** `node policy/schemas/validate.mjs` (requires Ajv 8)
- **Terraform modules:** `terraform init -backend=false -input=false && terraform validate` inside
  each touched `modules/<name>/` (local validation only; never run cloud plan/apply)
- **Manifest parser:** reproduce the `actions/load-manifest/parse.sh` cases from
  `.github/workflows/selftest.yml` using mikefarah `yq` v4

## 5. Two-step SHA-pinned workflow releases

Shared workflows in `platform` are production dependencies for every caller (`backend`, `web`,
`desktop`, `landing`, `product`). Follow the two-step release sequence:

1. **Merge component changes first:** land workflow/action changes on `main` and confirm `selftest`
   passes.
2. **Repoint internal SHA pins in a second change:** update `_dispatch.yml`'s internal `uses:` (and
   nested action pins) to that exact 40-character `main` commit SHA, verify with
   `python3 scripts/check_internal_pins.py`, and merge. Never pin internal workflows/actions to
   movable tags such as `v1` (a tag can move silently while callers inherit secrets).
3. **Caller opt-in:** downstream repositories bump `_dispatch.yml@<sha>` in their
   `.github/workflows/ci.yml` deliberately after reviewing the diff.

## 6. Handover and `## Evidence`

Agents commit on local branches and do not push, open PRs, or trigger releases. Before stopping:

1. Write the PR body into `.agent/pr-body.md` with an `## Evidence` section (replacing vendored
   `opening-a-pr.md`'s `## Verification`).
2. List the exact commands run (`make check`, `make verify`, and any subsystem checks) with pass
   counts and `0 failed`, or `Evidence: not applicable (<reason>)` for docs-only changes.
3. If downstream repos must bump pins after merge, state the exact release order (step 1 platform
   merge -> step 2 internal pin bump -> step 3 caller pin bumps).
