import type { LatencySample } from './types.js';

/** Exact percentile via nearest-rank over a copy of the samples. */
export function percentile(samplesMs: number[], p: number): number {
  if (samplesMs.length === 0) return 0;
  const sorted = [...samplesMs].sort((a, b) => a - b);
  const rank = Math.ceil((p / 100) * sorted.length);
  const index = Math.min(sorted.length - 1, Math.max(0, rank - 1));
  return sorted[index]!;
}

export function summarize(samplesMs: number[]): LatencySample {
  return {
    p50: percentile(samplesMs, 50),
    p95: percentile(samplesMs, 95),
    p99: percentile(samplesMs, 99),
  };
}

export interface BaselineRecord {
  value: number; // rolling EWMA of the chosen metric
  runs: number; // how many runs have contributed
  driftStreak: number; // consecutive runs currently over threshold
}

export type BaselineStore = Record<string, BaselineRecord>;

export interface DriftConfig {
  driftPct: number; // e.g. 30 → flag when current > baseline * 1.3
  sustainedRuns: number; // consecutive over-threshold runs before flagging
  alpha?: number; // EWMA weight for the newest sample (default 0.3)
}

export interface DriftResult {
  drifted: boolean;
  baseline: number;
  current: number;
  streak: number;
}

/**
 * Compare a metric against its rolling baseline, then fold the observation into
 * the baseline (TRD §7.4). Drift is only reported once it has been sustained for
 * `sustainedRuns` consecutive runs, so a single spike does not gate or file.
 *
 * The baseline updates *after* comparison, so slow creep is always measured
 * against history rather than against itself.
 */
export function evaluateDrift(
  store: BaselineStore,
  key: string,
  current: number,
  cfg: DriftConfig,
): DriftResult {
  const alpha = cfg.alpha ?? 0.3;
  const prior = store[key];

  // First observation establishes the baseline; nothing to drift against yet.
  if (!prior) {
    store[key] = { value: current, runs: 1, driftStreak: 0 };
    return { drifted: false, baseline: current, current, streak: 0 };
  }

  const threshold = prior.value * (1 + cfg.driftPct / 100);
  const over = current > threshold;
  const streak = over ? prior.driftStreak + 1 : 0;
  const drifted = streak >= cfg.sustainedRuns;

  store[key] = {
    value: alpha * current + (1 - alpha) * prior.value,
    runs: prior.runs + 1,
    driftStreak: drifted ? 0 : streak, // reset the streak once we've flagged
  };

  return { drifted, baseline: prior.value, current, streak };
}
