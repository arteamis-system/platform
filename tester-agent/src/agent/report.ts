import { dedupeFindings, gateDecision } from '../core/dedup.js';
import type { Finding, LatencySample, Mode, TesterReport } from '../core/types.js';

/**
 * Assembles the standardized report (TRD §7.7). This object is the contract with
 * findings-routing and any dashboard, so it is built in one place and validated
 * against the schema in policy/schemas/tester-report.schema.json.
 */
export function buildReport(input: {
  mode: Mode;
  environment: string;
  iterationsRun: number;
  rawFindings: Finding[];
  latency: Record<string, LatencySample>;
  costUsd: number;
  gateOn: string[];
  minVerified: number;
}): TesterReport {
  const findings = dedupeFindings(input.rawFindings).filter((f) => f.type !== 'nominal');

  return {
    mode: input.mode,
    environment: input.environment,
    iterations_run: input.iterationsRun,
    gate_decision: gateDecision(findings, {
      mode: input.mode,
      gateOn: input.gateOn,
      minVerified: input.minVerified,
    }),
    findings,
    latency: input.latency,
    cost_usd: Number(input.costUsd.toFixed(6)),
  };
}

/** A compact human summary for the GitHub step summary. */
export function renderSummary(report: TesterReport): string {
  const lines = [
    `### Tester agent — ${report.mode} on \`${report.environment}\``,
    '',
    `| | |`,
    `|---|---|`,
    `| iterations | ${report.iterations_run} |`,
    `| gate | **${report.gate_decision}** |`,
    `| findings | ${report.findings.length} |`,
    `| cost | $${report.cost_usd.toFixed(4)} |`,
    '',
  ];

  if (report.findings.length > 0) {
    lines.push('| severity | type | endpoint | summary | seen |', '|---|---|---|---|---|');
    for (const f of report.findings) {
      lines.push(
        `| ${f.severity} | ${f.type} | \`${f.endpoint}\` | ${f.summary} | ${f.verified} |`,
      );
    }
    lines.push('');
  }

  const endpoints = Object.entries(report.latency);
  if (endpoints.length > 0) {
    lines.push('| endpoint | p50 | p95 | p99 |', '|---|---|---|---|');
    for (const [endpoint, l] of endpoints) {
      lines.push(`| \`${endpoint}\` | ${l.p50}ms | ${l.p95}ms | ${l.p99}ms |`);
    }
  }

  return lines.join('\n');
}
