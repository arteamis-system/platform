// Pure-function tests for findings routing. Run with `node --test` — no
// dependencies, so the platform selftest can execute them directly.

import assert from 'node:assert/strict';
import { test, describe } from 'node:test';

import {
  clearAbsences,
  countAbsences,
  hasMateriallyChanged,
  issueBody,
  issueTitle,
  larkCard,
  withAbsences,
} from './route.mjs';

const finding = (over = {}) => ({
  id: 'fp1',
  type: 'latency_regression',
  severity: 'high',
  endpoint: 'GET /search',
  summary: 'p95 above SLO',
  metrics: { p95_ms: 800, baseline_p95_ms: 350 },
  verified: 3,
  ...over,
});

describe('issue rendering', () => {
  test('title carries severity, type and endpoint', () => {
    assert.equal(
      issueTitle(finding(), 'tasmil-ai'),
      '[high] latency_regression in tasmil-ai: GET /search',
    );
  });

  test('body includes metrics, environment and the replay pointer', () => {
    const body = issueBody(finding({ repro: '.tester/replays/fp1.http' }), {
      environment: 'staging',
      nowIso: '2026-07-24T00:00:00Z',
      runUrl: 'https://example/run/1',
    });

    assert.match(body, /p95_ms \| 800/);
    assert.match(body, /`staging`/);
    assert.match(body, /replays\/fp1\.http/);
    assert.match(body, /3 independent reproduction/);
  });

  test('body tolerates a finding with no metrics', () => {
    const body = issueBody(finding({ metrics: undefined }), {
      environment: 'staging',
      nowIso: 'now',
      runUrl: '',
    });
    assert.match(body, /\| — \| — \|/);
  });
});

describe('comment throttling', () => {
  test('a first sighting always reports', () => {
    assert.equal(hasMateriallyChanged(null, finding()), true);
  });

  test('a severity change always reports', () => {
    const prior = { metrics: { p95_ms: 800 }, severity: 'low' };
    assert.equal(hasMateriallyChanged(prior, finding({ severity: 'high' })), true);
  });

  test('a small metric wobble stays silent', () => {
    const prior = { metrics: { p95_ms: 800, baseline_p95_ms: 350 }, severity: 'high' };
    const next = finding({ severity: 'high', metrics: { p95_ms: 830, baseline_p95_ms: 350 } });
    assert.equal(hasMateriallyChanged(prior, next), false);
  });

  test('a large metric move reports', () => {
    const prior = { metrics: { p95_ms: 800, baseline_p95_ms: 350 }, severity: 'high' };
    const next = finding({ severity: 'high', metrics: { p95_ms: 2000, baseline_p95_ms: 350 } });
    assert.equal(hasMateriallyChanged(prior, next), true);
  });

  test('a brand new metric key reports', () => {
    const prior = { metrics: { p95_ms: 800 }, severity: 'high' };
    const next = finding({ severity: 'high', metrics: { p95_ms: 800, error_rate: 5 } });
    assert.equal(hasMateriallyChanged(prior, next), true);
  });
});

describe('absence counter', () => {
  test('reads zero from a body with no marker', () => {
    assert.equal(countAbsences('nothing here'), 0);
  });

  test('round-trips through the body', () => {
    const body = withAbsences('some body', 2);
    assert.equal(countAbsences(body), 2);
  });

  test('replaces rather than appends on repeat', () => {
    const once = withAbsences('body', 1);
    const twice = withAbsences(once, 2);
    assert.equal(countAbsences(twice), 2);
    assert.equal(twice.match(/absences/g).length, 1);
  });

  test('clears when the finding reappears', () => {
    const body = withAbsences('body', 2);
    assert.equal(countAbsences(clearAbsences(body)), 0);
  });
});

describe('lark card', () => {
  test('colours by severity and links the issue', () => {
    const card = larkCard({
      title: 'Promotion blocked',
      severity: 'high',
      lines: ['something broke'],
      url: 'https://example/issue/1',
    });

    assert.equal(card.msg_type, 'interactive');
    assert.equal(card.card.header.template, 'red');
    assert.equal(card.card.elements.at(-1).actions[0].url, 'https://example/issue/1');
  });

  test('omits the button when there is no url', () => {
    const card = larkCard({ title: 't', severity: 'low', lines: ['x'], url: '' });
    assert.equal(card.card.header.template, 'grey');
    assert.equal(card.card.elements.length, 1);
  });
});
