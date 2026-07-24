import type { Finding } from './types.js';

/**
 * Collapse the raw findings from every iteration into one entry per fingerprint
 * (TRD §8.1). Repeats increment `verified` rather than multiplying findings, and
 * the highest severity seen for a fingerprint wins.
 */
const SEVERITY_RANK = { high: 3, med: 2, low: 1 } as const;

export function dedupeFindings(raw: Finding[]): Finding[] {
  const byId = new Map<string, Finding>();

  for (const finding of raw) {
    const existing = byId.get(finding.id);
    if (!existing) {
      byId.set(finding.id, { ...finding, verified: finding.verified || 1 });
      continue;
    }
    existing.verified += finding.verified || 1;
    if (SEVERITY_RANK[finding.severity] > SEVERITY_RANK[existing.severity]) {
      existing.severity = finding.severity;
      existing.summary = finding.summary;
      existing.metrics = finding.metrics;
    }
  }

  return [...byId.values()].sort(
    (a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.verified - a.verified,
  );
}

/**
 * The gate decision (TRD §7.3, FR-16). In soak mode a finding blocks promotion
 * only if its type is listed in `gateOn`, its severity is high, and it survived
 * the re-verification threshold. Monitor mode never gates.
 */
export function gateDecision(
  findings: Finding[],
  opts: { mode: 'soak' | 'monitor'; gateOn: string[]; minVerified: number },
): 'pass' | 'block' | 'n/a' {
  if (opts.mode === 'monitor') return 'n/a';

  const blocking = findings.some(
    (f) =>
      f.severity === 'high' &&
      f.verified >= opts.minVerified &&
      opts.gateOn.includes(gateKey(f.type)),
  );
  return blocking ? 'block' : 'pass';
}

// Map a finding type to the manifest's gate_on vocabulary.
function gateKey(type: Finding['type']): string {
  switch (type) {
    case 'functional_bug':
    case 'contract_violation':
      return 'functional_high';
    case 'latency_regression':
      return 'latency_p95_slo';
    case 'error_spike':
      return 'error_rate_slo';
    default:
      return type;
  }
}
