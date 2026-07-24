// The data contracts from TRD §7.7 and §8. Every downstream consumer depends on
// these shapes, not on repo specifics.

export type Mode = 'soak' | 'monitor';

export type FindingType =
  | 'functional_bug'
  | 'latency_regression'
  | 'error_spike'
  | 'contract_violation'
  | 'flaky'
  | 'nominal';

export type Severity = 'high' | 'med' | 'low';

export interface Finding {
  id: string; // fingerprint
  type: FindingType;
  severity: Severity;
  endpoint: string;
  summary: string;
  metrics?: Record<string, number>;
  repro?: string;
  verified: number;
}

export interface LatencySample {
  p50: number;
  p95: number;
  p99: number;
}

export interface TesterReport {
  mode: Mode;
  environment: string;
  iterations_run: number;
  gate_decision: 'pass' | 'block' | 'n/a';
  findings: Finding[];
  latency: Record<string, LatencySample>;
  cost_usd: number;
}

export interface SLO {
  latency_p95_ms?: number;
  latency_p99_ms?: number;
  error_rate_pct?: number;
}
