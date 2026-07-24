import { describe, expect, it } from 'vitest';

import { extractJson, parseSteps, parseVerdict } from '../agent/loop.js';

// The model's output is the one untrusted input in the loop. These tests pin the
// parsing down so a chatty or malformed model can never crash a run or silently
// turn a 500 into a pass.

describe('extractJson', () => {
  it('reads a bare JSON array', () => {
    expect(extractJson('[{"a":1}]')).toEqual([{ a: 1 }]);
  });

  it('reads JSON out of a fenced block', () => {
    expect(extractJson('```json\n{"a":1}\n```')).toEqual({ a: 1 });
  });

  it('reads JSON surrounded by prose', () => {
    expect(extractJson('Sure! Here you go:\n[{"a":1}]\nHope that helps.')).toEqual([{ a: 1 }]);
  });

  it('returns null for unparseable output', () => {
    expect(extractJson('I cannot help with that.')).toBeNull();
    expect(extractJson('[{broken')).toBeNull();
  });
});

describe('parseSteps', () => {
  it('parses a plan into probe steps', () => {
    const steps = parseSteps('[{"method":"get","url":"/health","why":"smoke"}]');
    expect(steps).toEqual([{ method: 'get', url: '/health', headers: undefined, body: undefined }]);
  });

  it('caps the plan at four steps so one iteration cannot run away', () => {
    const many = JSON.stringify(
      Array.from({ length: 10 }, (_, i) => ({ method: 'GET', url: `/p${i}` })),
    );
    expect(parseSteps(many)).toHaveLength(4);
  });

  it('returns an empty plan rather than throwing on junk', () => {
    expect(parseSteps('no json here')).toEqual([]);
    expect(parseSteps('{"not":"an array"}')).toEqual([]);
  });

  it('defaults a missing method to GET', () => {
    expect(parseSteps('[{"url":"/x"}]')[0]!.method).toBe('GET');
  });
});

describe('parseVerdict', () => {
  it('accepts a well-formed verdict', () => {
    const v = parseVerdict('{"type":"functional_bug","severity":"high","summary":"500 on /x"}', 500);
    expect(v).toEqual({ type: 'functional_bug', severity: 'high', summary: '500 on /x' });
  });

  it('falls back to the status code when the judge is unparseable', () => {
    // A 5xx must never be silently classified as fine just because the model
    // returned prose.
    const v = parseVerdict('the server seems unhappy', 503);
    expect(v.type).toBe('functional_bug');
    expect(v.severity).toBe('high');
  });

  it('treats an unparseable judgement on a 200 as nominal', () => {
    const v = parseVerdict('looks good to me', 200);
    expect(v.type).toBe('nominal');
  });

  it('rejects an invented finding type', () => {
    const v = parseVerdict('{"type":"catastrophe","severity":"high","summary":"x"}', 200);
    expect(v.type).toBe('nominal');
  });

  it('truncates an overlong summary', () => {
    const v = parseVerdict(
      JSON.stringify({ type: 'nominal', severity: 'low', summary: 'x'.repeat(1000) }),
      200,
    );
    expect(v.summary.length).toBe(300);
  });
});
