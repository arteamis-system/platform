# tester-agent

A TypeScript CLI (Node ≥ 22, zod) that probes a running deployment. It has two modes:

| Mode | When it runs | Can block promotion? |
|---|---|---|
| `soak` | After a staging deploy | Yes |
| `monitor` | On a cron | No, never |

`../.github/workflows/tester-agent.yml` calls it and sets its environment variables from the manifest. See `README.md` for the full list.

This agent is not enabled for any Arteamis repository (checked 2026-10-22): backend, web and landing manifests carry no `test.tester_agent` block, and no repository has a monitor workflow. Its build/unit tests do not establish that a deployed app has passed soak or monitoring; a real run needs an explicitly selected target and configured gateway access.

## Commands

```bash
npm ci
npm run typecheck
npm test                  # vitest in watch mode
npm run test:ci           # vitest run --coverage (what selftest runs)
npm run build             # tsc -p tsconfig.build.json
```

Run these commands from `tester-agent/`. `bin/tester-agent.js` loads `dist/cli.js`, so build before invoking the CLI. For report-contract changes also validate `../policy/schemas/validate.mjs` from the platform root (with Ajv 8 available); selftest checks valid and invalid report variants.

## Design rules

- **The loop** (`src/agent/loop.ts`): observe → plan → act → measure → judge → record → decide.
- **The model only plans probes and judges responses.**
- **Everything else is deterministic code in `src/core/`:**
  - budgets
  - latency percentiles and baselines
  - fingerprints and dedup
  - replay re-verification
  - the gate decision

  Keep it that way, so a finding reproduces without the model.
- **Safety rules:**
  - Read-only against staging by default.
  - Mutating verbs need `mutating: true`.
  - Paths that look destructive are always refused.
  - Every run is bounded by iterations, wall-clock time and USD, whichever runs out first.
  - Scrub secrets from every artefact.
  - `src/agent/prober.ts` implements request admission and destructive-path refusal; the model cannot override it. Enabling mutation in a manifest is a reviewed target-scope choice, not permission to probe unrelated services.
- **Reports are built in `src/agent/report.ts`** and must validate against `../policy/schemas/tester-report.schema.json`.
- **Model calls go through the Virtuals gateway client** in `src/vp/client.ts`, using one `VIRTUALS_API_KEY`.
- **Gate decisions stay deterministic.** `src/core/dedup.ts` returns `n/a` for monitor mode; a finding causes `src/cli.ts` to exit nonzero only for a blocking soak decision. Setup/runtime errors can still fail the command. Do not make a monitor finding block promotion or turn a model judgment alone into a verified failure.
- Unit tests inject fetch/time/provider doubles. Use them for budget, safety, replay and gate changes; keep credentials, live probes and provider spending out of ordinary tests. Report skipped or incomplete live checks separately from local unit results.
