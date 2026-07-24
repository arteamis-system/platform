// Reproducibility (FR-18). Every finding ships a deterministic replay bundle so a
// human — or the regression suite — can reproduce it without the LLM in the loop.

export interface ReplayStep {
  method: string;
  url: string;
  headers?: Record<string, string>;
  body?: unknown;
}

export interface ReplayBundle {
  fingerprint: string;
  createdAtIso: string;
  seed: number;
  steps: ReplayStep[];
}

const REDACTED = '<redacted>';
const SENSITIVE_HEADERS = new Set([
  'authorization',
  'cookie',
  'set-cookie',
  'x-api-key',
  'proxy-authorization',
]);

/**
 * Secrets must never reach a finding, an artifact, or a notification (TR-7).
 * Headers are redacted by name; body values are redacted by key name.
 */
export function scrubHeaders(headers: Record<string, string> = {}): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    out[key] = SENSITIVE_HEADERS.has(key.toLowerCase()) ? REDACTED : value;
  }
  return out;
}

const SENSITIVE_KEY = /(token|secret|password|passwd|api[-_]?key|authorization|credential)/i;

export function scrubBody(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(scrubBody);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, inner] of Object.entries(value as Record<string, unknown>)) {
      out[key] = SENSITIVE_KEY.test(key) ? REDACTED : scrubBody(inner);
    }
    return out;
  }
  return value;
}

export function buildReplayBundle(input: {
  fingerprint: string;
  steps: ReplayStep[];
  seed: number;
  nowIso: string;
}): ReplayBundle {
  return {
    fingerprint: input.fingerprint,
    createdAtIso: input.nowIso,
    seed: input.seed,
    steps: input.steps.map((step) => ({
      method: step.method.toUpperCase(),
      url: step.url,
      headers: scrubHeaders(step.headers),
      body: step.body === undefined ? undefined : scrubBody(step.body),
    })),
  };
}

/** Render a bundle as a .http file — runnable in curl/VS Code REST client. */
export function renderHttpFile(bundle: ReplayBundle): string {
  const lines: string[] = [
    `# replay bundle ${bundle.fingerprint}`,
    `# captured ${bundle.createdAtIso} (seed ${bundle.seed})`,
    '',
  ];
  for (const step of bundle.steps) {
    lines.push(`${step.method} ${step.url}`);
    for (const [key, value] of Object.entries(step.headers ?? {})) {
      lines.push(`${key}: ${value}`);
    }
    if (step.body !== undefined) {
      lines.push('', JSON.stringify(step.body, null, 2));
    }
    lines.push('', '###', '');
  }
  return lines.join('\n');
}
