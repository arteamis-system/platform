---
name: arteamis-method
description: The one entry skill for every agent session on Arteamis platform. Read it first; it routes the task to a vendored pstack playbook and principles (cursor/plugins 93b916d) and enforces Arteamis's overrides, shared-workflow safety, two-step SHA-pinning discipline, and verification gates.
---

# Arteamis method (`platform`)

One entry skill per session (PRD P1-43): start here, pick one playbook, follow it. The 44 playbooks
and principles under `<pstack>/` are vendored byte for byte from `cursor/plugins` (`93b916d`, MIT);
provenance, review checklist, and SHA-256 hashes live in `<pstack>/VENDORED.md`.

## Before anything

1. Read `AGENTS.md` (the repo map) and `docs/agent-workflow.md` (plus `tester-agent/AGENTS.md` when
   touching `tester-agent/`).
2. Read `.agent/progress.md` if it exists; it is the resume point.
3. Load the harness adapter once per session so Cursor tool/path names in vendored `pstack/` map
   cleanly:
   - **Claude Code:** read `<pstack>/docs/harness/claude-code.md` and
     `<pstack>/../docs/harness-adapters.md`.
   - **Codex CLI, Antigravity (AGY), or Orca workers:** read
     `<pstack>/../docs/harness-adapters.md`.

## Locating vendored `pstack/`

Resolve `<pstack>` in this order (works in multi-repo checkouts, standalone clones, and Orca
worktrees):

1. `../desktop/plugins/arteamis/pstack/` (sibling checkout inside `arteamis-workspace/`)
2. `~/.arteamis/plugin/pstack/` (installed once per Mac via `node desktop/scripts/install-pstack.mjs`)

## Route the task (12 playbooks)

| Task | Playbook (`<pstack>/skills/poteto-mode/playbooks/`) |
| --- | --- |
| Something is broken | `bug-fix.md` |
| New behaviour | `feature.md` |
| A question, no code change | `investigation.md` |
| Same behaviour, better structure | `refactoring.md` |
| Slow | `perf-issue.md` |
| A live process misbehaves | `runtime-forensics.md` |
| A trace or dump already exists | `trace-forensics.md` |
| Must look identical to a reference | `visual-parity.md` |
| A design choice to settle by trying | `prototype.md` |
| Resuming someone's work | `session-pickup.md` |
| Stopping for now | `pause-safely.md` |
| Finishing | `opening-a-pr.md` |

## Other vendored skills & 24 principles

Under `<pstack>/skills/`: `poteto-mode`, `why` (rationale from commits and PRs), `recall` (rebuild
recent context), `create-verification-skill` (only for a repo without `make verify`), and the 24
`principle-*` skills named by the playbooks:

- `principle-attack-the-premise`
- `principle-boundary-discipline`
- `principle-build-the-lever`
- `principle-encode-lessons-in-structure`
- `principle-exhaust-the-design-space`
- `principle-experience-first`
- `principle-explain-the-number`
- `principle-fix-root-causes`
- `principle-foundational-thinking`
- `principle-guard-the-context-window`
- `principle-laziness-protocol`
- `principle-make-operations-idempotent`
- `principle-migrate-callers-then-delete-legacy-apis`
- `principle-minimize-reader-load`
- `principle-model-the-domain`
- `principle-never-block-on-the-human`
- `principle-outcome-oriented-execution`
- `principle-prove-it-works`
- `principle-redesign-from-first-principles`
- `principle-separate-before-serializing-shared-state`
- `principle-sequence-verifiable-units`
- `principle-subtract-before-you-add`
- `principle-test-behavior-not-implementation`
- `principle-type-system-discipline`

## Platform verification surface

- `make check`: runs `node scripts/check-pstack.mjs`, `node --test scripts/*.node-tests.mjs`,
  `git diff --check`, and (when available on PATH) `actionlint -shellcheck=`,
  `shellcheck actions/*/*.sh`, and `terraform fmt -check -recursive modules/`.
- `make verify`: runs `make check` plus `(cd actions/report-findings && node --test)`.
- Subsystem checks from `.github/workflows/selftest.yml`:
  - `python3 scripts/check_internal_pins.py` when editing internal `uses:` pins,
  - `(cd tester-agent && npm ci && npm run typecheck && npm run test:ci && npm run build)` for
    `tester-agent/`,
  - `terraform init -backend=false -input=false && terraform validate` inside each touched
    `modules/<name>/` (local validation only; never cloud plan/apply),
  - manifest-parser cases (`actions/load-manifest/parse.sh` with mikefarah `yq` v4) when changing
    manifest parsing.

## Two-step SHA-pinning release discipline

Shared workflows in `platform` are production dependencies for every caller (`backend`, `web`,
`desktop`, `landing`, `product`):

1. **Every internal `uses:` must point at `arteamis-system/platform`**, never upstream
   `devsecops-playground-org/platform` (enforced by `scripts/check-pstack.mjs`).
2. **Step 1 — land the component change:** merge the workflow/action change to `main` and verify
   `selftest` passes.
3. **Step 2 — repoint internal SHA pins:** in a second PR/commit, update `_dispatch.yml`'s internal
   `uses:` (and nested action pins) to that full 40-character `main` commit SHA (verified by
   `python3 scripts/check_internal_pins.py`) and merge it. Never pin internal refs to movable tags
   like `v1`.
4. **Step 3 — caller opt-in:** downstream repositories bump `_dispatch.yml@<sha>` in their
   `.github/workflows/ci.yml` deliberately after reading the diff.

## Arteamis overrides

These win over the vendored text:

- **Verification surface.** "The control skill" and "the matching surface" mean `make verify` (plus
  the matching local `selftest` checks for touched subsystems).
- **Evidence (`opening-a-pr.md` override).** Where vendored `opening-a-pr.md` asks for
  `## Verification`, Arteamis requires `## Evidence` instead. Record exact commands, pass/fail
  counts, and any paired-PR / caller pin-bump order.
- **Who pushes.** Work on a topic branch from `main` (`docs/<topic>` for docs-only). Agents commit
  on local branches only. People push, open PRs, merge, and trigger releases. Where
  `opening-a-pr.md` says to open the PR, write the PR body into `.agent/pr-body.md` and stop.
- **Not vendored (X-20, X-21, X-22).** `architect`, `arena`, `swarm`, `interrogate`,
  `figure-it-out`, `unslop`, `technical-writing`, `tdd`, `/deslop`, `/loop`, plugin hooks, and
  model-slug defaults are not vendored. Skip any step that needs one and say so in one line; never
  install skills or plugins at runtime and never declare `"hooks"` in `.agents/` or `.claude/`.
- **Checks over instructions (P1-20..22).** A review comment made twice becomes a check in
  `scripts/check-pstack.mjs`, `scripts/check_internal_pins.py`, or `selftest.yml` whose failure
  message states the fix.
- **Repo rules.** Never commit secrets, `*.tfstate`, or generated artifacts; never run cloud
  deployments or `terraform apply` from an agent session; never edit vendored files under
  `<pstack>/`.
