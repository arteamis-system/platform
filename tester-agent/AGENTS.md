# tester-agent

A TypeScript CLI (Node ≥ 22, zod) that probes a running deployment. It has two modes:

| Mode | When it runs | Can block promotion? |
|---|---|---|
| `soak` | After a staging deploy | Yes |
| `monitor` | On a cron | No, never |

`../.github/workflows/tester-agent.yml` calls it and sets its environment variables from the manifest. See `README.md` for the full list.

## Commands

```bash
npm ci
npm run typecheck
npm test                  # vitest in watch mode
npm run test:ci           # vitest run --coverage (what selftest runs)
npm run build             # tsc -p tsconfig.build.json
```

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
- **Reports are built in `src/agent/report.ts`** and must validate against `../policy/schemas/tester-report.schema.json`.
- **Model calls go through the Virtuals gateway client** in `src/vp/client.ts`, using one `VIRTUALS_API_KEY`.
