// Findings routing (TRD §8). GitHub Issues are the system of record; Lark is a
// notification channel for the few events a human must see immediately.
//
// Dependency-free on purpose: it runs on the runner's Node with fetch, so there
// is no bundle to build or vendored tree to keep current.

import { readFile, appendFile } from 'node:fs/promises';

const GITHUB_API = process.env.GITHUB_API_URL ?? 'https://api.github.com';
const FP_LABEL_PREFIX = 'agent-fp:';

const token = process.env.GITHUB_TOKEN ?? '';
const larkWebhook = process.env.LARK_WEBHOOK ?? '';

const cfg = {
  reportPath: process.env.REPORT_PATH,
  component: process.env.COMPONENT ?? 'unknown',
  sourceRepo: process.env.SOURCE_REPO ?? '',
  issuesRepo:
    !process.env.ISSUES_REPO || process.env.ISSUES_REPO === 'self'
      ? process.env.SOURCE_REPO
      : process.env.ISSUES_REPO,
  notifyOn: new Set(
    (process.env.NOTIFY_ON ?? '').split(',').map((s) => s.trim()).filter(Boolean),
  ),
  autoCloseAfter: Number(process.env.AUTO_CLOSE_AFTER ?? 3),
  runUrl: process.env.RUN_URL ?? '',
};

// ---------------------------------------------------------------- helpers ---

/** Issue title for a finding — stable, so humans recognise repeats. */
export function issueTitle(finding, component) {
  return `[${finding.severity}] ${finding.type} in ${component}: ${finding.endpoint}`;
}

export function issueBody(finding, meta) {
  const metrics = Object.entries(finding.metrics ?? {})
    .map(([k, v]) => `| ${k} | ${v} |`)
    .join('\n');

  return [
    finding.summary,
    '',
    '| metric | value |',
    '|---|---|',
    metrics || '| — | — |',
    '',
    `- **environment:** \`${meta.environment}\``,
    `- **endpoint:** \`${finding.endpoint}\``,
    `- **verified:** ${finding.verified} independent reproduction(s)`,
    finding.repro ? `- **replay bundle:** \`${finding.repro}\` (in the run artefact)` : '',
    `- **first seen:** ${meta.nowIso}`,
    meta.runUrl ? `- **run:** ${meta.runUrl}` : '',
    '',
    '<sub>Filed by the tester agent. It updates this issue on change and closes it',
    'automatically once the finding stops reproducing.</sub>',
  ]
    .filter(Boolean)
    .join('\n');
}

/** Whether a metric change is material enough to warrant a new comment. */
export function hasMateriallyChanged(previous, current) {
  if (!previous) return true;
  if (previous.severity !== current.severity) return true;

  const prevMetrics = previous.metrics ?? {};
  for (const [key, value] of Object.entries(current.metrics ?? {})) {
    const before = Number(prevMetrics[key]);
    if (!Number.isFinite(before)) return true;
    if (before === 0) {
      if (value !== 0) return true;
      continue;
    }
    if (Math.abs(value - before) / Math.abs(before) > 0.2) return true; // >20% move
  }
  return false;
}

async function gh(path, init = {}) {
  const res = await fetch(`${GITHUB_API}${path}`, {
    ...init,
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`GitHub ${init.method ?? 'GET'} ${path} -> ${res.status} ${await res.text()}`);
  }
  return res.status === 204 ? null : res.json();
}

async function postLark(card) {
  if (!larkWebhook) return;
  try {
    await fetch(larkWebhook, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(card),
    });
  } catch (err) {
    // A chat outage must never fail a pipeline.
    console.log(`::warning::Lark notification failed: ${err.message}`);
  }
}

/** Lark interactive card: severity colour, the metrics, and a link to the issue. */
export function larkCard({ title, severity, lines, url }) {
  const template = severity === 'high' ? 'red' : severity === 'med' ? 'orange' : 'grey';
  return {
    msg_type: 'interactive',
    card: {
      config: { wide_screen_mode: true },
      header: { template, title: { tag: 'plain_text', content: title } },
      elements: [
        { tag: 'div', text: { tag: 'lark_md', content: lines.join('\n') } },
        ...(url
          ? [
              {
                tag: 'action',
                actions: [
                  {
                    tag: 'button',
                    text: { tag: 'plain_text', content: 'Open issue' },
                    url,
                    type: 'primary',
                  },
                ],
              },
            ]
          : []),
      ],
    },
  };
}

// ------------------------------------------------------------------- main ---

async function main() {
  const report = JSON.parse(await readFile(cfg.reportPath, 'utf8'));
  const nowIso = new Date().toISOString();
  const [owner, repo] = cfg.issuesRepo.split('/');

  if (!token) {
    console.log('::warning::No GITHUB_TOKEN available; skipping findings routing.');
    return;
  }

  // Every issue this agent has open for this component.
  const existing = await gh(
    `/repos/${owner}/${repo}/issues?state=open&labels=tester-agent&per_page=100`,
  );
  const byFingerprint = new Map();
  for (const issue of existing) {
    const label = issue.labels
      .map((l) => (typeof l === 'string' ? l : l.name))
      .find((n) => n?.startsWith(FP_LABEL_PREFIX));
    if (label) byFingerprint.set(label.slice(FP_LABEL_PREFIX.length), issue);
  }

  const seen = new Set();
  let opened = 0;
  let updated = 0;
  let closed = 0;

  for (const finding of report.findings ?? []) {
    seen.add(finding.id);
    const existingIssue = byFingerprint.get(finding.id);
    const labels = [
      'tester-agent',
      `severity:${finding.severity}`,
      `type:${finding.type}`,
      `env:${report.environment}`,
      `${FP_LABEL_PREFIX}${finding.id}`,
    ];

    if (!existingIssue) {
      const created = await gh(`/repos/${owner}/${repo}/issues`, {
        method: 'POST',
        body: JSON.stringify({
          title: issueTitle(finding, cfg.component),
          body: issueBody(finding, { environment: report.environment, nowIso, runUrl: cfg.runUrl }),
          labels,
        }),
      });
      opened += 1;
      console.log(`opened #${created.number} for ${finding.id}`);

      if (finding.severity === 'high' && cfg.notifyOn.has('new_high')) {
        await postLark(
          larkCard({
            title: `New high-severity finding — ${cfg.component}`,
            severity: finding.severity,
            lines: [
              `**${finding.type}** on \`${finding.endpoint}\``,
              finding.summary,
              `Environment: \`${report.environment}\``,
            ],
            url: created.html_url,
          }),
        );
      }
      continue;
    }

    // Already open and reproducing again: clear any absence countdown, or an
    // intermittent finding would drift toward auto-close and never converge.
    if (countAbsences(existingIssue.body) > 0) {
      await gh(`/repos/${owner}/${repo}/issues/${existingIssue.number}`, {
        method: 'PATCH',
        body: JSON.stringify({ body: clearAbsences(existingIssue.body) }),
      });
    }

    // Comment only when something material moved, so a flapping endpoint
    // produces one issue rather than a stream of noise.
    const prior = parseState(existingIssue.body);
    if (hasMateriallyChanged(prior, finding)) {
      await gh(`/repos/${owner}/${repo}/issues/${existingIssue.number}/comments`, {
        method: 'POST',
        body: JSON.stringify({
          body: [
            `Still reproducing (${finding.verified}×) with changed metrics:`,
            '',
            '```json',
            JSON.stringify(finding.metrics ?? {}, null, 2),
            '```',
            cfg.runUrl ? `[run](${cfg.runUrl})` : '',
          ]
            .filter(Boolean)
            .join('\n'),
        }),
      });
      updated += 1;
    }
  }

  // Anything previously open that this run did not reproduce moves toward
  // auto-close; a finding must be absent for several consecutive runs first.
  for (const [fp, issue] of byFingerprint) {
    if (seen.has(fp)) continue;

    const absences = countAbsences(issue.body) + 1;
    if (absences < cfg.autoCloseAfter) {
      // The counter lives in the issue body, not a comment, so the next run can
      // actually read it back — comments are not fetched here.
      await gh(`/repos/${owner}/${repo}/issues/${issue.number}`, {
        method: 'PATCH',
        body: JSON.stringify({ body: withAbsences(issue.body, absences) }),
      });
      await gh(`/repos/${owner}/${repo}/issues/${issue.number}/comments`, {
        method: 'POST',
        body: JSON.stringify({
          body: `Not reproduced in this run (${absences}/${cfg.autoCloseAfter} before auto-close).`,
        }),
      });
      continue;
    }

    await gh(`/repos/${owner}/${repo}/issues/${issue.number}`, {
      method: 'PATCH',
      body: JSON.stringify({ state: 'closed', state_reason: 'completed' }),
    });
    await gh(`/repos/${owner}/${repo}/issues/${issue.number}/labels`, {
      method: 'POST',
      body: JSON.stringify({ labels: ['auto-resolved'] }),
    });
    closed += 1;

    if (cfg.notifyOn.has('auto_resolved')) {
      await postLark(
        larkCard({
          title: `Auto-resolved — ${cfg.component}`,
          severity: 'low',
          lines: [`\`${issue.title}\` stopped reproducing and was closed.`],
          url: issue.html_url,
        }),
      );
    }
  }

  if (report.gate_decision === 'block' && cfg.notifyOn.has('gate_block')) {
    await postLark(
      larkCard({
        title: `Promotion blocked — ${cfg.component}`,
        severity: 'high',
        lines: [
          `The tester agent blocked promotion to production.`,
          `${report.findings.length} confirmed finding(s) on \`${report.environment}\`.`,
        ],
        url: cfg.runUrl,
      }),
    );
  }

  console.log(`opened=${opened} updated=${updated} closed=${closed}`);
  if (process.env.GITHUB_OUTPUT) {
    await appendFile(
      process.env.GITHUB_OUTPUT,
      `opened=${opened}\nupdated=${updated}\nclosed=${closed}\n`,
    );
  }
}

/** Recover the last recorded metrics from an issue body (best effort). */
function parseState(body = '') {
  const match = body.match(/```json\s*([\s\S]*?)```/);
  if (!match) return null;
  try {
    return { metrics: JSON.parse(match[1]), severity: null };
  } catch {
    return null;
  }
}

export function countAbsences(body = '') {
  const matches = [...body.matchAll(/<!--absences:(\d+)-->/g)];
  const last = matches.at(-1);
  return last ? Number(last[1]) : 0;
}

/** Replace (or append) the absence marker carried in the issue body. */
export function withAbsences(body = '', count) {
  const marker = `<!--absences:${count}-->`;
  return /<!--absences:\d+-->/.test(body)
    ? body.replace(/<!--absences:\d+-->/g, marker)
    : `${body}\n\n${marker}`;
}

/** A finding that reappears must reset the counter, or it never converges. */
export function clearAbsences(body = '') {
  return body.replace(/\n*<!--absences:\d+-->/g, '');
}

main().catch((err) => {
  // Routing must never be the reason a pipeline fails.
  console.log(`::warning::findings routing failed: ${err.message}`);
});
