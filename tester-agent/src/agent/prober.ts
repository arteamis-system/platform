import type { ReplayStep } from '../core/replay.js';

// Safety guardrails (NFR-8, TRD §7.6). The agent is read-only against staging by
// default; anything that could mutate state is refused unless explicitly enabled.

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const DESTRUCTIVE_PATH = /(delete|drop|truncate|purge|wipe|reset|destroy)/i;

export class BlockedByGuardrail extends Error {
  constructor(reason: string) {
    super(reason);
    this.name = 'BlockedByGuardrail';
  }
}

export interface ProbeResult {
  step: ReplayStep;
  status: number;
  ok: boolean;
  latencyMs: number;
  bodySnippet: string;
  error?: string;
}

export interface ProberOptions {
  baseUrl: string;
  mutating: boolean;
  maxRps: number;
  fetchImpl?: typeof fetch;
  now?: () => number;
  timeoutMs?: number;
}

export function assertAllowed(step: ReplayStep, mutating: boolean): void {
  const method = step.method.toUpperCase();
  if (!mutating && MUTATING_METHODS.has(method)) {
    throw new BlockedByGuardrail(
      `${method} is refused: the run is read-only (set tester_agent.scope.mutating to allow)`,
    );
  }
  if (DESTRUCTIVE_PATH.test(step.url)) {
    throw new BlockedByGuardrail(`refusing a destructive-looking path: ${step.url}`);
  }
}

/**
 * Issues probes against the target, measuring latency and enforcing a max request
 * rate so the agent can never DoS the thing it is testing.
 */
export class Prober {
  private readonly fetchImpl: typeof fetch;
  private readonly now: () => number;
  private lastRequestAt = 0;

  constructor(private readonly opts: ProberOptions) {
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.now = opts.now ?? (() => Date.now());
  }

  private get minIntervalMs(): number {
    return this.opts.maxRps > 0 ? 1000 / this.opts.maxRps : 0;
  }

  async probe(step: ReplayStep): Promise<ProbeResult> {
    assertAllowed(step, this.opts.mutating);

    await this.throttle();

    const url = step.url.startsWith('http')
      ? step.url
      : `${this.opts.baseUrl.replace(/\/+$/, '')}/${step.url.replace(/^\/+/, '')}`;

    const startedAt = this.now();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.opts.timeoutMs ?? 20_000);

    try {
      const res = await this.fetchImpl(url, {
        method: step.method.toUpperCase(),
        headers: step.headers,
        body: step.body === undefined ? undefined : JSON.stringify(step.body),
        signal: controller.signal,
      });
      const text = await res.text().catch(() => '');
      return {
        step,
        status: res.status,
        ok: res.ok,
        latencyMs: this.now() - startedAt,
        bodySnippet: text.slice(0, 2000),
      };
    } catch (err) {
      return {
        step,
        status: 0,
        ok: false,
        latencyMs: this.now() - startedAt,
        bodySnippet: '',
        error: err instanceof Error ? err.message : String(err),
      };
    } finally {
      clearTimeout(timer);
    }
  }

  private async throttle(): Promise<void> {
    const wait = this.minIntervalMs - (this.now() - this.lastRequestAt);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    this.lastRequestAt = this.now();
  }
}
