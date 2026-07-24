// Client for the Virtuals Protocol LLM gateway — an OpenAI-compatible endpoint
// that fans one key out to many providers. See docs/virtuals-protocol-models.md.
//
// Two gateway quirks are handled here so the rest of the agent never has to care:
//   1. a successful completion returns HTTP 201, not 200 (treat any 2xx as OK)
//   2. reasoning models return empty content if max_tokens is too small, so the
//      floor is clamped up.

export interface VpMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface VpUsage {
  prompt_tokens: number;
  completion_tokens: number;
  cost: number;
}

export interface VpCompletion {
  content: string;
  reasoning: string;
  finishReason: string;
  usage: VpUsage;
}

export interface VpClientOptions {
  apiKey: string;
  baseUrl?: string;
  model?: string;
  fetchImpl?: typeof fetch;
  maxRetries?: number;
  timeoutMs?: number;
}

const DEFAULT_BASE = 'https://compute.virtuals.io/v1';
// Cheap, non-reasoning default so a misconfigured run can't burn budget.
const DEFAULT_MODEL = 'deepseek-deepseek-v4-flash';
// Reasoning models spend tokens before emitting content; never cap below this.
const MIN_MAX_TOKENS = 512;

export class VpError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryable: boolean,
  ) {
    super(message);
    this.name = 'VpError';
  }
}

export class VpClient {
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly fetchImpl: typeof fetch;
  private readonly maxRetries: number;
  private readonly timeoutMs: number;
  private spentUsd = 0;

  constructor(private readonly opts: VpClientOptions) {
    if (!opts.apiKey) {
      throw new Error('VIRTUALS_API_KEY is required');
    }
    this.baseUrl = (opts.baseUrl ?? DEFAULT_BASE).replace(/\/+$/, '');
    this.model = opts.model ?? DEFAULT_MODEL;
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.maxRetries = opts.maxRetries ?? 4;
    this.timeoutMs = opts.timeoutMs ?? 60_000;
  }

  get totalCostUsd(): number {
    return Number(this.spentUsd.toFixed(6));
  }

  async complete(
    messages: VpMessage[],
    opts: { maxTokens?: number; temperature?: number; model?: string } = {},
  ): Promise<VpCompletion> {
    const body = {
      model: opts.model ?? this.model,
      messages,
      max_tokens: Math.max(MIN_MAX_TOKENS, opts.maxTokens ?? MIN_MAX_TOKENS),
      temperature: opts.temperature ?? 0.2,
    };

    let attempt = 0;
    // eslint-disable-next-line no-constant-condition
    while (true) {
      attempt += 1;
      try {
        return await this.once(body);
      } catch (err) {
        const retryable = err instanceof VpError ? err.retryable : true;
        if (!retryable || attempt > this.maxRetries) throw err;
        // Exponential backoff with a deterministic base (no jitter → testable).
        await sleep(Math.min(8000, 250 * 2 ** (attempt - 1)));
      }
    }
  }

  private async once(body: unknown): Promise<VpCompletion> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${this.opts.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    // 201 is success on this gateway; treat any 2xx as OK.
    if (res.status < 200 || res.status >= 300) {
      const retryable = res.status === 429 || res.status >= 500;
      const text = await safeText(res);
      throw new VpError(`gateway ${res.status}: ${text.slice(0, 200)}`, res.status, retryable);
    }

    const json = (await res.json()) as GatewayResponse;
    return parseCompletion(json, (usd) => {
      this.spentUsd += usd;
    });
  }
}

interface GatewayResponse {
  choices?: Array<{
    finish_reason?: string;
    message?: { content?: string; reasoning_content?: string };
  }>;
  usage?: { prompt_tokens?: number; completion_tokens?: number; cost?: number };
}

export function parseCompletion(
  json: GatewayResponse,
  onCost: (usd: number) => void,
): VpCompletion {
  const choice = json.choices?.[0];
  const usage: VpUsage = {
    prompt_tokens: json.usage?.prompt_tokens ?? 0,
    completion_tokens: json.usage?.completion_tokens ?? 0,
    cost: json.usage?.cost ?? 0,
  };
  onCost(usage.cost);
  return {
    content: choice?.message?.content ?? '',
    reasoning: choice?.message?.reasoning_content ?? '',
    finishReason: choice?.finish_reason ?? 'unknown',
    usage,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function safeText(res: Response): Promise<string> {
  try {
    return await res.text();
  } catch {
    return '<no body>';
  }
}
