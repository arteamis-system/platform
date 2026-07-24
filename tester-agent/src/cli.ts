import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';

import { runLoop } from './agent/loop.js';
import { buildReport, renderSummary } from './agent/report.js';
import { renderHttpFile } from './core/replay.js';
import type { BaselineStore } from './core/latency.js';
import type { Mode } from './core/types.js';
import { VpClient } from './vp/client.js';

// Entrypoint invoked by .github/workflows/tester-agent.yml. All configuration
// arrives as environment variables so the workflow stays the only place that
// knows how to read the manifest.

function env(name: string, fallback = ''): string {
  return process.env[name]?.trim() || fallback;
}

function num(name: string, fallback: number): number {
  const raw = Number(env(name));
  return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

function bool(name: string, fallback = false): boolean {
  const raw = env(name).toLowerCase();
  return raw ? raw === 'true' || raw === '1' : fallback;
}

async function readJson<T>(path: string, fallback: T): Promise<T> {
  try {
    return JSON.parse(await readFile(path, 'utf8')) as T;
  } catch {
    return fallback;
  }
}

export async function main(): Promise<number> {
  const mode = (env('TESTER_MODE', 'soak') as Mode) === 'monitor' ? 'monitor' : 'soak';
  const baseUrl = env('TESTER_BASE_URL');
  const environment = env('TESTER_ENVIRONMENT', 'staging');
  const outDir = env('TESTER_OUT_DIR', '.tester');

  if (!baseUrl) {
    console.error('TESTER_BASE_URL is not set — nothing to probe.');
    return 2;
  }

  const apiKey = env('VIRTUALS_API_KEY');
  if (!apiKey) {
    console.error(
      'VIRTUALS_API_KEY is not set. Add it as an org/repo secret to enable the tester agent.',
    );
    return 2;
  }

  const baselinePath = env('TESTER_BASELINE_FILE', join(outDir, 'baselines.json'));
  const baselines = await readJson<BaselineStore>(baselinePath, {});
  const spec = env('TESTER_OPENAPI') ? await readFile(env('TESTER_OPENAPI'), 'utf8') : undefined;

  const vp = new VpClient({
    apiKey,
    model: env('TESTER_MODEL', 'deepseek-deepseek-v4-flash'),
    baseUrl: env('VIRTUALS_BASE_URL', 'https://compute.virtuals.io/v1'),
  });

  const result = await runLoop(vp, {
    mode,
    environment,
    baseUrl,
    spec,
    slo: {
      latency_p95_ms: num('TESTER_SLO_P95_MS', 0) || undefined,
      latency_p99_ms: num('TESTER_SLO_P99_MS', 0) || undefined,
      error_rate_pct: num('TESTER_SLO_ERROR_PCT', 0) || undefined,
    },
    limits: {
      iterations: num('TESTER_ITERATIONS', 20),
      wallClockMs: num('TESTER_BUDGET_MINUTES', 10) * 60_000,
      tokenUsd: num('TESTER_BUDGET_USD', 3),
    },
    drift: {
      driftPct: num('TESTER_DRIFT_PCT', 30),
      sustainedRuns: num('TESTER_SUSTAINED_RUNS', 2),
    },
    baselines,
    mutating: bool('TESTER_MUTATING', false),
    maxRps: num('TESTER_MAX_RPS', 5),
    reverifyTimes: num('TESTER_REVERIFY', 3),
    seed: num('TESTER_SEED', 1),
  });

  const report = buildReport({
    mode,
    environment,
    iterationsRun: result.iterationsRun,
    rawFindings: result.findings,
    latency: result.latency,
    costUsd: result.costUsd,
    gateOn: env('TESTER_GATE_ON', 'functional_high,latency_p95_slo')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
    minVerified: num('TESTER_MIN_VERIFIED', 2),
  });

  // --- persist artefacts ---------------------------------------------------
  await mkdir(join(outDir, 'replays'), { recursive: true });
  await writeFile(join(outDir, 'report.json'), JSON.stringify(report, null, 2));
  for (const [id, bundle] of result.replays) {
    await writeFile(join(outDir, 'replays', `${id}.http`), renderHttpFile(bundle));
  }
  await mkdir(dirname(baselinePath), { recursive: true });
  await writeFile(baselinePath, JSON.stringify(baselines, null, 2));

  const summary = renderSummary(report);
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY) {
    await writeFile(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`, { flag: 'a' });
  }
  if (process.env.GITHUB_OUTPUT) {
    await writeFile(
      process.env.GITHUB_OUTPUT,
      [
        `gate_decision=${report.gate_decision}`,
        `findings=${report.findings.length}`,
        `report=${join(outDir, 'report.json')}`,
        `cost_usd=${report.cost_usd}`,
        '',
      ].join('\n'),
      { flag: 'a' },
    );
  }

  // Only soak gates. Monitor never fails the job (TRD §7.3).
  return report.gate_decision === 'block' ? 1 : 0;
}
