import { Budget, type BudgetLimits } from '../core/budget.js';
import { fingerprint } from '../core/fingerprint.js';
import { evaluateDrift, summarize, type BaselineStore, type DriftConfig } from '../core/latency.js';
import { buildReplayBundle, type ReplayStep } from '../core/replay.js';
import type { Finding, LatencySample, Mode, SLO } from '../core/types.js';
import { Prober, BlockedByGuardrail } from './prober.js';
import type { VpClient } from '../vp/client.js';

// The loop from TRD §7.2:
//   observe → plan → act → measure → judge → record → decide
// The LLM proposes what to probe next (plan) and classifies the result (judge);
// everything else is deterministic so findings stay reproducible.

const PLANNER_SYSTEM = `You are a QA agent probing an HTTP API to find real defects.
Reply with ONLY a JSON array of up to 4 requests to try next, no prose:
[{"method":"GET","url":"/path","headers":{},"body":null,"why":"short reason"}]
Prefer endpoints from the spec you have not yet covered, boundary values, and
error paths. Never propose destructive operations.`;

const JUDGE_SYSTEM = `You classify one HTTP probe result against the API spec.
Reply with ONLY JSON:
{"type":"functional_bug|latency_regression|error_spike|contract_violation|flaky|nominal",
 "severity":"high|med|low","summary":"one sentence"}
Use "nominal" when the response is correct. A 5xx, a schema violation, or a
response contradicting the spec is a functional_bug or contract_violation.`;

export interface LoopOptions {
  mode: Mode;
  environment: string;
  baseUrl: string;
  spec?: string;
  slo: SLO;
  limits: BudgetLimits;
  drift: DriftConfig;
  baselines: BaselineStore;
  mutating: boolean;
  maxRps: number;
  reverifyTimes: number;
  seed: number;
  model?: string;
  now?: () => number;
  fetchImpl?: typeof fetch;
}

export interface LoopResult {
  findings: Finding[];
  latency: Record<string, LatencySample>;
  iterationsRun: number;
  costUsd: number;
  replays: Map<string, ReturnType<typeof buildReplayBundle>>;
}

export async function runLoop(vp: VpClient, opts: LoopOptions): Promise<LoopResult> {
  const now = opts.now ?? (() => Date.now());
  const budget = new Budget(opts.limits, now());
  const prober = new Prober({
    baseUrl: opts.baseUrl,
    mutating: opts.mutating,
    maxRps: opts.maxRps,
    fetchImpl: opts.fetchImpl,
    now,
  });

  const findings: Finding[] = [];
  const replays = new Map<string, ReturnType<typeof buildReplayBundle>>();
  const samples = new Map<string, number[]>();
  const covered: string[] = [];

  while (budget.stopReason(now()) === null) {
    budget.startIteration();

    // --- plan -------------------------------------------------------------
    const steps = await planSteps(vp, opts, covered);
    if (steps.length === 0) {
      budget.record(0, false);
      continue;
    }

    let foundSomething = false;

    for (const step of steps) {
      // --- act + measure --------------------------------------------------
      let result;
      try {
        result = await prober.probe(step);
      } catch (err) {
        // A guardrail refusal is expected behaviour, not a finding.
        if (err instanceof BlockedByGuardrail) continue;
        throw err;
      }

      const endpoint = `${step.method.toUpperCase()} ${step.url}`;
      covered.push(endpoint);
      pushSample(samples, endpoint, result.latencyMs);

      // --- judge ----------------------------------------------------------
      const verdict = await judge(vp, opts, endpoint, result);

      if (verdict.type !== 'nominal') {
        const id = fingerprint({
          type: verdict.type,
          endpoint,
          signature: verdict.summary,
          environment: opts.environment,
        });
        findings.push({
          id,
          type: verdict.type,
          severity: verdict.severity,
          endpoint,
          summary: verdict.summary,
          metrics: { latency_ms: result.latencyMs, status: result.status },
          repro: `.tester/replays/${id}.http`,
          verified: 1,
        });
        replays.set(
          id,
          buildReplayBundle({
            fingerprint: id,
            seed: opts.seed,
            nowIso: new Date(now()).toISOString(),
            steps: [step],
          }),
        );
        foundSomething = true;
      }
    }

    budget.record(vp.totalCostUsd - budget.totalUsd, foundSomething);
  }

  // --- latency: SLO breaches and sustained drift ---------------------------
  const latency: Record<string, LatencySample> = {};
  for (const [endpoint, values] of samples) {
    const s = summarize(values);
    latency[endpoint] = s;

    if (opts.slo.latency_p95_ms && s.p95 > opts.slo.latency_p95_ms) {
      findings.push(
        latencyFinding(opts, endpoint, 'p95 above the declared SLO', {
          p95_ms: s.p95,
          slo_p95_ms: opts.slo.latency_p95_ms,
        }),
      );
    }

    const drift = evaluateDrift(
      opts.baselines,
      `${opts.environment}|${endpoint}|p95`,
      s.p95,
      opts.drift,
    );
    if (drift.drifted) {
      findings.push(
        latencyFinding(opts, endpoint, 'p95 drifted above the rolling baseline', {
          p95_ms: drift.current,
          baseline_p95_ms: Math.round(drift.baseline),
        }),
      );
    }
  }

  // --- re-verify: a finding must survive repeats before it can gate (FR-19) --
  for (const finding of findings) {
    if (finding.type === 'latency_regression') {
      // Latency findings are already evidence over many samples/runs.
      finding.verified = Math.max(finding.verified, opts.reverifyTimes);
      continue;
    }
    finding.verified = await reverify(prober, finding, replays, opts.reverifyTimes);
  }

  return {
    findings,
    latency,
    iterationsRun: budget.iterationsRun,
    costUsd: vp.totalCostUsd,
    replays,
  };
}

function latencyFinding(
  opts: LoopOptions,
  endpoint: string,
  summary: string,
  metrics: Record<string, number>,
): Finding {
  const id = fingerprint({
    type: 'latency_regression',
    endpoint,
    signature: summary,
    environment: opts.environment,
  });
  return {
    id,
    type: 'latency_regression',
    severity: 'high',
    endpoint,
    summary,
    metrics,
    verified: 1,
  };
}

/** Replay a finding's request N times; count how many repeats reproduce it. */
async function reverify(
  prober: Prober,
  finding: Finding,
  replays: Map<string, ReturnType<typeof buildReplayBundle>>,
  times: number,
): Promise<number> {
  const bundle = replays.get(finding.id);
  const step = bundle?.steps[0];
  if (!step) return finding.verified;

  let confirmed = 0;
  for (let i = 0; i < times; i++) {
    try {
      const result = await prober.probe(step);
      // The defect reproduces if the response is still not successful.
      if (!result.ok) confirmed += 1;
    } catch {
      // A guardrail or transport error is not a confirmation.
    }
  }
  return confirmed;
}

async function planSteps(
  vp: VpClient,
  opts: LoopOptions,
  covered: string[],
): Promise<ReplayStep[]> {
  const context = [
    `Base URL: ${opts.baseUrl}`,
    opts.spec ? `OpenAPI spec:\n${opts.spec.slice(0, 12_000)}` : 'No spec provided.',
    covered.length ? `Already probed:\n${[...new Set(covered)].slice(-40).join('\n')}` : '',
    opts.mutating ? 'Mutating requests are ALLOWED.' : 'Read-only run: GET/HEAD only.',
  ]
    .filter(Boolean)
    .join('\n\n');

  const res = await vp.complete(
    [
      { role: 'system', content: PLANNER_SYSTEM },
      { role: 'user', content: context },
    ],
    { maxTokens: 1024, model: opts.model },
  );

  return parseSteps(res.content);
}

async function judge(
  vp: VpClient,
  opts: LoopOptions,
  endpoint: string,
  result: { status: number; latencyMs: number; bodySnippet: string; error?: string },
): Promise<{ type: Finding['type']; severity: Finding['severity']; summary: string }> {
  const res = await vp.complete(
    [
      { role: 'system', content: JUDGE_SYSTEM },
      {
        role: 'user',
        content: [
          `Endpoint: ${endpoint}`,
          `Status: ${result.status}${result.error ? ` (transport error: ${result.error})` : ''}`,
          `Latency: ${result.latencyMs}ms`,
          opts.spec ? `Spec excerpt:\n${opts.spec.slice(0, 4000)}` : '',
          `Body:\n${result.bodySnippet.slice(0, 1500)}`,
        ]
          .filter(Boolean)
          .join('\n'),
      },
    ],
    { maxTokens: 512, model: opts.model },
  );

  return parseVerdict(res.content, result.status);
}

/** Models wrap JSON in prose or fences; extract the payload defensively. */
export function extractJson(text: string): unknown {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const candidate = (fenced?.[1] ?? text).trim();
  const start = candidate.search(/[[{]/);
  if (start === -1) return null;
  const end = Math.max(candidate.lastIndexOf(']'), candidate.lastIndexOf('}'));
  try {
    return JSON.parse(candidate.slice(start, end + 1));
  } catch {
    return null;
  }
}

export function parseSteps(text: string): ReplayStep[] {
  const parsed = extractJson(text);
  if (!Array.isArray(parsed)) return [];

  return parsed
    .filter((s): s is Record<string, unknown> => !!s && typeof s === 'object')
    .map((s) => ({
      method: String(s.method ?? 'GET'),
      url: String(s.url ?? '/'),
      headers: (s.headers as Record<string, string>) ?? undefined,
      body: s.body ?? undefined,
    }))
    .filter((s) => s.url.length > 0)
    .slice(0, 4);
}

export function parseVerdict(
  text: string,
  status: number,
): { type: Finding['type']; severity: Finding['severity']; summary: string } {
  const parsed = extractJson(text) as Record<string, unknown> | null;

  const validTypes: Finding['type'][] = [
    'functional_bug',
    'latency_regression',
    'error_spike',
    'contract_violation',
    'flaky',
    'nominal',
  ];
  const type = validTypes.includes(parsed?.type as Finding['type'])
    ? (parsed!.type as Finding['type'])
    : // If the judge is unparseable, fall back to the status code: a 5xx is a
      // defect regardless of what the model said.
      status >= 500
      ? 'functional_bug'
      : 'nominal';

  const severity = (['high', 'med', 'low'] as const).includes(
    parsed?.severity as Finding['severity'],
  )
    ? (parsed!.severity as Finding['severity'])
    : status >= 500
      ? 'high'
      : 'low';

  return {
    type,
    severity,
    summary: String(parsed?.summary ?? `status ${status}`).slice(0, 300),
  };
}

function pushSample(map: Map<string, number[]>, key: string, value: number): void {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}
