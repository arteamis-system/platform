// Verifies that the tester-report schema actually guards the contract: a valid
// report must pass, and each deliberately-broken variant must be rejected.
// Run with `node policy/schemas/validate.mjs` (needs ajv on the path).

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// The schema declares draft 2020-12, so it needs ajv's 2020 entrypoint — the
// default export only understands draft-07.
import Ajv from 'ajv/dist/2020.js';

const here = dirname(fileURLToPath(import.meta.url));
const schema = JSON.parse(readFileSync(join(here, 'tester-report.schema.json'), 'utf8'));

const valid = {
  mode: 'soak',
  environment: 'staging',
  iterations_run: 12,
  gate_decision: 'block',
  cost_usd: 0.12,
  findings: [
    {
      id: 'a1b2c3d4',
      type: 'latency_regression',
      severity: 'high',
      endpoint: 'GET /search',
      summary: 'p95 above SLO',
      metrics: { p95_ms: 812, baseline_p95_ms: 350 },
      repro: '.tester/replays/a1b2c3d4.http',
      verified: 3,
    },
  ],
  latency: { 'GET /search': { p50: 120, p95: 812, p99: 1400 } },
};

// Each entry must be REJECTED, or the schema is not really enforcing anything.
const mustReject = {
  'invalid severity': { ...valid, findings: [{ ...valid.findings[0], severity: 'critical' }] },
  'invalid finding type': { ...valid, findings: [{ ...valid.findings[0], type: 'vibes' }] },
  'invalid gate decision': { ...valid, gate_decision: 'maybe' },
  'invalid mode': { ...valid, mode: 'chaos' },
  'missing required field': { ...valid, environment: undefined },
  'non-hex fingerprint': { ...valid, findings: [{ ...valid.findings[0], id: 'not-a-hash!' }] },
  'negative iterations': { ...valid, iterations_run: -1 },
  'unknown top-level key': { ...valid, surprise: true },
  'incomplete latency sample': { ...valid, latency: { 'GET /x': { p50: 1 } } },
};

const ajv = new Ajv({ strict: false });
const validate = ajv.compile(schema);

let failures = 0;

if (!validate(valid)) {
  console.error('FAIL: a valid report was rejected:', validate.errors);
  failures += 1;
} else {
  console.log('ok: valid report accepted');
}

for (const [name, sample] of Object.entries(mustReject)) {
  if (validate(sample)) {
    console.error(`FAIL: schema accepted ${name}`);
    failures += 1;
  } else {
    console.log(`ok: rejected ${name}`);
  }
}

if (failures > 0) {
  console.error(`${failures} schema check(s) failed`);
  process.exit(1);
}
console.log('report schema guards the contract');
