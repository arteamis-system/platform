import { describe, expect, it, vi } from 'vitest';

import { BlockedByGuardrail, Prober, assertAllowed } from '../agent/prober.js';
import { buildReport, renderSummary } from '../agent/report.js';
import { buildReplayBundle, renderHttpFile, scrubBody, scrubHeaders } from '../core/replay.js';
import type { Finding } from '../core/types.js';

describe('guardrails', () => {
  it('refuses mutating verbs in a read-only run', () => {
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      expect(() => assertAllowed({ method, url: '/orders' }, false)).toThrow(BlockedByGuardrail);
    }
  });

  it('allows mutating verbs once explicitly enabled', () => {
    expect(() => assertAllowed({ method: 'POST', url: '/orders' }, true)).not.toThrow();
  });

  it('always allows reads', () => {
    expect(() => assertAllowed({ method: 'GET', url: '/orders' }, false)).not.toThrow();
  });

  it('refuses destructive-looking paths even when mutating is enabled', () => {
    expect(() => assertAllowed({ method: 'POST', url: '/admin/reset-db' }, true)).toThrow(
      /destructive/,
    );
  });
});

describe('Prober', () => {
  it('measures latency and returns the status', async () => {
    let clock = 1000;
    const fetchImpl = vi.fn(async () => {
      clock += 120;
      return new Response('{"ok":true}', { status: 200 });
    });

    const prober = new Prober({
      baseUrl: 'https://api.example.dev',
      mutating: false,
      maxRps: 1000,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => clock,
    });

    const result = await prober.probe({ method: 'GET', url: '/health' });

    expect(result.status).toBe(200);
    expect(result.ok).toBe(true);
    expect(result.latencyMs).toBe(120);
    const call = fetchImpl.mock.calls[0] as unknown as [string];
    expect(String(call[0])).toBe('https://api.example.dev/health');
  });

  it('records a transport failure instead of throwing', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('ECONNREFUSED');
    });

    const prober = new Prober({
      baseUrl: 'https://api.example.dev',
      mutating: false,
      maxRps: 1000,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => 0,
    });

    const result = await prober.probe({ method: 'GET', url: '/health' });
    expect(result.ok).toBe(false);
    expect(result.error).toContain('ECONNREFUSED');
  });
});

describe('secret scrubbing', () => {
  it('redacts sensitive headers', () => {
    const out = scrubHeaders({ Authorization: 'Bearer abc', Accept: 'application/json' });
    expect(out.Authorization).toBe('<redacted>');
    expect(out.Accept).toBe('application/json');
  });

  it('redacts secret-looking body keys at any depth', () => {
    const out = scrubBody({
      user: 'nathan',
      apiKey: 'acp-live-key',
      nested: { password: 'hunter2', keep: 1 },
      list: [{ token: 't' }],
    }) as Record<string, unknown>;

    expect(out.user).toBe('nathan');
    expect(out.apiKey).toBe('<redacted>');
    expect((out.nested as Record<string, unknown>).password).toBe('<redacted>');
    expect((out.nested as Record<string, unknown>).keep).toBe(1);
    expect((out.list as Array<Record<string, unknown>>)[0]!.token).toBe('<redacted>');
  });

  it('builds a replay bundle with secrets already stripped', () => {
    const bundle = buildReplayBundle({
      fingerprint: 'fp123',
      seed: 42,
      nowIso: '2026-07-24T00:00:00Z',
      steps: [
        {
          method: 'get',
          url: '/orders',
          headers: { Authorization: 'Bearer live' },
          body: { secret: 's' },
        },
      ],
    });

    expect(bundle.steps[0]!.method).toBe('GET');
    expect(bundle.steps[0]!.headers!.Authorization).toBe('<redacted>');

    const http = renderHttpFile(bundle);
    expect(http).toContain('GET /orders');
    expect(http).not.toContain('Bearer live');
  });
});

describe('buildReport', () => {
  const finding = (over: Partial<Finding> = {}): Finding => ({
    id: 'fp1',
    type: 'functional_bug',
    severity: 'high',
    endpoint: 'GET /x',
    summary: 'returns 500',
    verified: 3,
    ...over,
  });

  it('produces the standardized contract shape', () => {
    const report = buildReport({
      mode: 'soak',
      environment: 'staging',
      iterationsRun: 12,
      rawFindings: [finding(), finding()],
      latency: { 'GET /x': { p50: 100, p95: 800, p99: 1200 } },
      costUsd: 0.123456789,
      gateOn: ['functional_high'],
      minVerified: 3,
    });

    expect(report.mode).toBe('soak');
    expect(report.iterations_run).toBe(12);
    expect(report.findings).toHaveLength(1);
    expect(report.gate_decision).toBe('block');
    expect(report.cost_usd).toBe(0.123457);
  });

  it('drops nominal findings from the report', () => {
    const report = buildReport({
      mode: 'monitor',
      environment: 'staging',
      iterationsRun: 1,
      rawFindings: [finding({ id: 'ok', type: 'nominal', severity: 'low' })],
      latency: {},
      costUsd: 0,
      gateOn: [],
      minVerified: 1,
    });

    expect(report.findings).toHaveLength(0);
    expect(report.gate_decision).toBe('n/a');
  });

  it('renders a summary table', () => {
    const report = buildReport({
      mode: 'soak',
      environment: 'staging',
      iterationsRun: 5,
      rawFindings: [finding()],
      latency: { 'GET /x': { p50: 10, p95: 20, p99: 30 } },
      costUsd: 0.5,
      gateOn: ['functional_high'],
      minVerified: 1,
    });

    const md = renderSummary(report);
    expect(md).toContain('Tester agent — soak on `staging`');
    expect(md).toContain('**block**');
    expect(md).toContain('GET /x');
  });
});
