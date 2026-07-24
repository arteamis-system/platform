import { describe, expect, it } from 'vitest';

import { Budget } from '../core/budget.js';
import { dedupeFindings, gateDecision } from '../core/dedup.js';
import { fingerprint, normalizeSignature } from '../core/fingerprint.js';
import { evaluateDrift, percentile, summarize, type BaselineStore } from '../core/latency.js';
import type { Finding } from '../core/types.js';

describe('Budget', () => {
  const limits = { iterations: 3, wallClockMs: 10_000, tokenUsd: 1 };

  it('allows iterations until the count is exhausted', () => {
    const b = new Budget(limits, 0);
    for (let i = 0; i < 3; i++) {
      expect(b.stopReason(0)).toBeNull();
      b.startIteration();
      b.record(0.01, true);
    }
    expect(b.stopReason(0)).toBe('iterations');
    expect(b.iterationsRun).toBe(3);
  });

  it('stops on wall-clock even with iterations left', () => {
    const b = new Budget(limits, 0);
    expect(b.stopReason(10_000)).toBe('wallclock');
  });

  it('stops when the USD budget is spent', () => {
    const b = new Budget(limits, 0);
    b.startIteration();
    b.record(1.5, true);
    expect(b.stopReason(0)).toBe('budget');
    expect(b.totalUsd).toBe(1.5);
  });

  it('stops after consecutive dry iterations', () => {
    const b = new Budget({ ...limits, iterations: 100 }, 0, 2);
    b.startIteration();
    b.record(0, false);
    expect(b.stopReason(0)).toBeNull();
    b.startIteration();
    b.record(0, false);
    expect(b.stopReason(0)).toBe('dry');
  });

  it('resets the dry streak when something new is found', () => {
    const b = new Budget({ ...limits, iterations: 100 }, 0, 2);
    b.startIteration();
    b.record(0, false);
    b.startIteration();
    b.record(0, true);
    expect(b.stopReason(0)).toBeNull();
  });

  it('never counts negative spend', () => {
    const b = new Budget(limits, 0);
    b.record(-5, true);
    expect(b.totalUsd).toBe(0);
  });
});

describe('fingerprint', () => {
  it('normalizes volatile detail out of a signature', () => {
    expect(normalizeSignature('User 123e4567-e89b-12d3-a456-426614174000 failed')).toBe(
      'user <uuid> failed',
    );
    expect(normalizeSignature('/orders/9981/items')).toBe('/orders/<id>/items');
    expect(normalizeSignature('balance 0xDEADBEEF low')).toBe('balance <hex> low');
  });

  it('is stable across cosmetically different repeats', () => {
    const a = fingerprint({
      type: 'functional_bug',
      endpoint: 'GET /orders/1',
      signature: 'order 4412 returned 500 at 2026-07-24T10:00:00Z',
      environment: 'staging',
    });
    const b = fingerprint({
      type: 'functional_bug',
      endpoint: 'GET /orders/1',
      signature: 'order 9987 returned 500 at 2026-07-24T18:31:02Z',
      environment: 'staging',
    });
    expect(a).toBe(b);
  });

  it('separates different environments and types', () => {
    const base = { endpoint: 'GET /x', signature: 'boom', environment: 'staging' } as const;
    const staging = fingerprint({ ...base, type: 'functional_bug' });
    const prod = fingerprint({ ...base, type: 'functional_bug', environment: 'production' });
    const other = fingerprint({ ...base, type: 'latency_regression' });

    expect(staging).not.toBe(prod);
    expect(staging).not.toBe(other);
  });
});

describe('latency', () => {
  it('computes percentiles by nearest rank', () => {
    const samples = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
    expect(percentile(samples, 50)).toBe(50);
    expect(percentile(samples, 95)).toBe(100);
    expect(percentile([], 95)).toBe(0);
  });

  it('summarizes a sample set', () => {
    expect(summarize([100, 100, 100])).toEqual({ p50: 100, p95: 100, p99: 100 });
  });
});

describe('evaluateDrift', () => {
  const cfg = { driftPct: 30, sustainedRuns: 2 };

  it('establishes a baseline on first sight without flagging', () => {
    const store: BaselineStore = {};
    const r = evaluateDrift(store, 'staging|GET /x|p95', 400, cfg);

    expect(r.drifted).toBe(false);
    expect(store['staging|GET /x|p95']?.value).toBe(400);
  });

  it('requires drift to be sustained before flagging', () => {
    const store: BaselineStore = { k: { value: 100, runs: 5, driftStreak: 0 } };

    const first = evaluateDrift(store, 'k', 200, cfg);
    expect(first.drifted).toBe(false);
    expect(first.streak).toBe(1);

    const second = evaluateDrift(store, 'k', 200, cfg);
    expect(second.drifted).toBe(true);
  });

  it('resets the streak when latency returns to normal', () => {
    const store: BaselineStore = { k: { value: 100, runs: 5, driftStreak: 1 } };
    const r = evaluateDrift(store, 'k', 105, cfg);

    expect(r.drifted).toBe(false);
    expect(store.k?.driftStreak).toBe(0);
  });

  it('folds the observation into the baseline after comparing', () => {
    const store: BaselineStore = { k: { value: 100, runs: 1, driftStreak: 0 } };
    evaluateDrift(store, 'k', 200, { ...cfg, alpha: 0.5 });

    // Compared against 100, then EWMA'd to 150 — so creep is measured against history.
    expect(store.k?.value).toBe(150);
    expect(store.k?.runs).toBe(2);
  });
});

describe('dedupeFindings', () => {
  const make = (over: Partial<Finding>): Finding => ({
    id: 'fp1',
    type: 'functional_bug',
    severity: 'low',
    endpoint: 'GET /x',
    summary: 'boom',
    verified: 1,
    ...over,
  });

  it('collapses repeats and counts verifications', () => {
    const out = dedupeFindings([make({}), make({}), make({ id: 'fp2' })]);

    expect(out).toHaveLength(2);
    expect(out.find((f) => f.id === 'fp1')?.verified).toBe(2);
  });

  it('keeps the highest severity seen for a fingerprint', () => {
    const out = dedupeFindings([make({ severity: 'low' }), make({ severity: 'high' })]);
    expect(out[0]?.severity).toBe('high');
  });

  it('orders by severity then frequency', () => {
    const out = dedupeFindings([
      make({ id: 'low', severity: 'low' }),
      make({ id: 'high', severity: 'high' }),
    ]);
    expect(out[0]?.id).toBe('high');
  });
});

describe('gateDecision', () => {
  const high: Finding = {
    id: 'a',
    type: 'functional_bug',
    severity: 'high',
    endpoint: 'GET /x',
    summary: 'boom',
    verified: 3,
  };

  it('never gates in monitor mode', () => {
    expect(gateDecision([high], { mode: 'monitor', gateOn: ['functional_high'], minVerified: 1 }))
      .toBe('n/a');
  });

  it('blocks a verified high finding listed in gate_on', () => {
    expect(gateDecision([high], { mode: 'soak', gateOn: ['functional_high'], minVerified: 3 }))
      .toBe('block');
  });

  it('does not block when the type is not gated on', () => {
    expect(gateDecision([high], { mode: 'soak', gateOn: ['latency_p95_slo'], minVerified: 1 }))
      .toBe('pass');
  });

  it('does not block a finding that failed re-verification', () => {
    expect(
      gateDecision([{ ...high, verified: 1 }], {
        mode: 'soak',
        gateOn: ['functional_high'],
        minVerified: 3,
      }),
    ).toBe('pass');
  });

  it('does not block on medium severity', () => {
    expect(
      gateDecision([{ ...high, severity: 'med' }], {
        mode: 'soak',
        gateOn: ['functional_high'],
        minVerified: 1,
      }),
    ).toBe('pass');
  });

  it('maps latency regressions to the latency gate key', () => {
    const latency: Finding = { ...high, type: 'latency_regression' };
    expect(gateDecision([latency], { mode: 'soak', gateOn: ['latency_p95_slo'], minVerified: 1 }))
      .toBe('block');
  });
});
