import { describe, expect, it, vi } from 'vitest';

import { VpClient, VpError, parseCompletion } from '../vp/client.js';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const OK_BODY = {
  choices: [{ finish_reason: 'stop', message: { content: 'hello' } }],
  usage: { prompt_tokens: 10, completion_tokens: 5, cost: 0.002 },
};

describe('VpClient', () => {
  it('requires an API key', () => {
    expect(() => new VpClient({ apiKey: '' })).toThrow(/VIRTUALS_API_KEY/);
  });

  it('treats 201 as success — the gateway does not return 200', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(201, OK_BODY));
    const client = new VpClient({ apiKey: 'acp-test', fetchImpl: fetchImpl as unknown as typeof fetch });

    const res = await client.complete([{ role: 'user', content: 'hi' }]);

    expect(res.content).toBe('hello');
    expect(client.totalCostUsd).toBeCloseTo(0.002, 6);
  });

  it('sends the bearer key and target model', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(201, OK_BODY));
    const client = new VpClient({
      apiKey: 'acp-secret',
      model: 'anthropic-claude-sonnet-5',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await client.complete([{ role: 'user', content: 'hi' }]);

    const call = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(call[0])).toContain('/chat/completions');
    const headers = call[1].headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer acp-secret');
    expect(JSON.parse(String(call[1].body)).model).toBe('anthropic-claude-sonnet-5');
  });

  it('never caps max_tokens below the reasoning-model floor', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(201, OK_BODY));
    const client = new VpClient({ apiKey: 'acp', fetchImpl: fetchImpl as unknown as typeof fetch });

    await client.complete([{ role: 'user', content: 'hi' }], { maxTokens: 16 });

    const call = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(call[1].body));
    expect(body.max_tokens).toBe(512);
  });

  it('retries 429 and 5xx, then succeeds', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(429, { error: { message: 'slow down' } }))
      .mockResolvedValueOnce(jsonResponse(500, { error: { message: 'boom' } }))
      .mockResolvedValueOnce(jsonResponse(201, OK_BODY));

    const client = new VpClient({
      apiKey: 'acp',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      maxRetries: 3,
    });

    const res = await client.complete([{ role: 'user', content: 'hi' }]);
    expect(res.content).toBe('hello');
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('does not retry a 4xx that is not 429', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(404, { error: { message: 'no such model' } }));
    const client = new VpClient({ apiKey: 'acp', fetchImpl: fetchImpl as unknown as typeof fetch });

    await expect(client.complete([{ role: 'user', content: 'hi' }])).rejects.toBeInstanceOf(VpError);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('gives up after exhausting retries', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(500, { error: { message: 'dead model' } }));
    const client = new VpClient({
      apiKey: 'acp',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      maxRetries: 1,
    });

    await expect(client.complete([{ role: 'user', content: 'hi' }])).rejects.toThrow(/gateway 500/);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});

describe('parseCompletion', () => {
  it('surfaces reasoning content and finish reason', () => {
    const out = parseCompletion(
      {
        choices: [
          {
            finish_reason: 'length',
            message: { content: '', reasoning_content: 'thinking...' },
          },
        ],
        usage: { prompt_tokens: 1, completion_tokens: 64, cost: 0.001 },
      },
      () => {},
    );

    expect(out.content).toBe('');
    expect(out.reasoning).toBe('thinking...');
    expect(out.finishReason).toBe('length');
  });

  it('tolerates a response with no choices or usage', () => {
    const out = parseCompletion({}, () => {});
    expect(out.content).toBe('');
    expect(out.usage.cost).toBe(0);
  });
});
