# tester-agent

The autonomous tester from the PRD (FR-14–19). It probes a running deployment,
classifies what it sees, tracks latency against a rolling baseline, and produces
the standardized report that findings-routing consumes.

It runs on the **Virtuals Protocol gateway** (`compute.virtuals.io`), an
OpenAI-compatible endpoint fronting many providers, so one `VIRTUALS_API_KEY`
covers every model.

## The loop

```
observe → plan → act → measure → judge → record → decide
```

The model only *plans* what to probe and *judges* the response. Everything that
determines an outcome — budgets, percentiles, baselines, fingerprints,
re-verification, the gate decision — is deterministic code, so a finding is
reproducible without the model and a chatty or malformed reply can never turn a
500 into a pass.

## Run models

| mode | when | gates? |
|---|---|---|
| `soak` | after a staging deploy | yes — a verified high finding blocks promotion |
| `monitor` | on a cron | never; files/updates issues and updates baselines |

## Safety (NFR-8)

Read-only against staging by default. Mutating verbs are refused unless
`mutating: true`, destructive-looking paths are always refused, requests are rate
limited, and every run is bounded by iteration, wall-clock **and** USD ceilings —
whichever is hit first ends it. Secrets are scrubbed from every artefact.

## Configuration

Driven entirely by environment variables set from the manifest by
`tester-agent.yml`:

| variable | meaning |
|---|---|
| `TESTER_MODE` | `soak` or `monitor` |
| `TESTER_BASE_URL` | target (resolved from `base_url_secret`) |
| `TESTER_ITERATIONS` / `TESTER_BUDGET_MINUTES` / `TESTER_BUDGET_USD` | hard budgets |
| `TESTER_SLO_P95_MS` / `TESTER_SLO_P99_MS` | SLO thresholds |
| `TESTER_DRIFT_PCT` / `TESTER_SUSTAINED_RUNS` | baseline drift rule |
| `TESTER_MUTATING` / `TESTER_MAX_RPS` | guardrails |
| `TESTER_REVERIFY` / `TESTER_MIN_VERIFIED` | false-positive control |
| `TESTER_GATE_ON` | which finding classes may block |
| `TESTER_MODEL` | VP model id (default `deepseek-deepseek-v4-flash`) |
| `VIRTUALS_API_KEY` | gateway key — required |

## Output

`.tester/report.json` conforms to `policy/schemas/tester-report.schema.json`, plus
one replay bundle per finding under `.tester/replays/<fingerprint>.http` and an
updated `.tester/baselines.json`.
