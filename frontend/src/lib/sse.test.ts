import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { streamChat, streamResearch } from './sse';

// streamChat/streamResearch parse the server's SSE wire format. Bugs here
// surface as "chat hangs mid-answer" or "lost tool events", so the parser
// behavior is pinned: framing, [DONE] handling, partial-chunk buffering,
// and error propagation.

function sseResponse(chunks: string[], ok = true): Response {
  const encoder = new TextEncoder();
  let sent = 0;
  return {
    ok,
    status: ok ? 200 : 500,
    body: {
      getReader: () => ({
        read: async () => {
          if (sent < chunks.length) {
            const value = encoder.encode(chunks[sent++]);
            return { done: false, value } as ReadableStreamReadResult<Uint8Array>;
          }
          return { done: true, value: undefined } as ReadableStreamReadResult<Uint8Array>;
        },
        releaseLock: () => undefined,
        cancel: () => undefined,
      }),
    },
  } as unknown as Response;
}

// Functional in-memory localStorage so settings (API key / URL) written by a
// test are actually readable back — the api helpers parse the settings blob
// on every call.
class MemoryStorage {
  private store = new Map<string, string>();
  getItem(k: string): string | null {
    return this.store.has(k) ? (this.store.get(k) as string) : null;
  }
  setItem(k: string, v: string): void {
    this.store.set(k, String(v));
  }
  removeItem(k: string): void {
    this.store.delete(k);
  }
  clear(): void {
    this.store.clear();
  }
}

beforeEach(() => {
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const CHAT_REQ = {
  model: 'qwen3:8b',
  messages: [{ role: 'user', content: 'hi' }],
  stream: true as const,
};

describe('streamChat', () => {
  it('yields token events and stops after [DONE]', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      sseResponse([
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        'data: [DONE]\n\n',
      ]),
    );

    const events = [];
    for await (const ev of streamChat(CHAT_REQ)) {
      events.push(ev);
    }

    expect(events).toHaveLength(2);
    expect(events[0].data).toContain('Hel');
    expect(events[1].data).toContain('lo');
  });

  it('carries the event: name alongside data', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      sseResponse(['event: tool_start\ndata: {"name":"calculator"}\n\n']),
    );

    const events = [];
    for await (const ev of streamChat(CHAT_REQ)) {
      events.push(ev);
    }

    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('tool_start');
    expect(events[0].data).toBe('{"name":"calculator"}');
  });

  it('buffers a JSON object split across network chunks', async () => {
    // One SSE frame delivered in two TCP-sized pieces.
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      sseResponse([
        'data: {"choices":[{"del',
        'ta":{"content":"hi"}}]}\n\n',
      ]),
    );

    const events = [];
    for await (const ev of streamChat(CHAT_REQ)) {
      events.push(ev);
    }

    expect(events).toHaveLength(1);
    expect(events[0].data).toBe('{"choices":[{"delta":{"content":"hi"}}]}');
  });

  it('throws on non-2xx responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(sseResponse([], false));

    await expect(async () => {
      for await (const _ of streamChat(CHAT_REQ)) {
        // consume
      }
    }).rejects.toThrow(/500/);
  });

  it('sends auth + content-type headers and the JSON body', async () => {
    localStorage.setItem(
      'nova_ai-settings',
      JSON.stringify({ apiKey: 'test-key-123' }),
    );
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(sseResponse(['data: [DONE]\n\n']));

    for await (const _ of streamChat(CHAT_REQ)) {
      // consume
    }

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    const headers = init.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers.Authorization).toBe('Bearer test-key-123');
    expect(JSON.parse(init.body as string)).toMatchObject(CHAT_REQ);
  });
});

describe('streamResearch', () => {
  it('parses JSON payloads, skips malformed ones, stops on done', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      sseResponse([
        'data: {"type":"search_call","arguments":{"query":"q"}}\n\n',
        'data: not-json-at-all\n\n',
        'data: {"type":"done"}\n\n',
        'data: {"type":"after_done_should_not_appear"}\n\n',
      ]),
    );

    const events = [];
    for await (const ev of streamResearch('q')) {
      events.push(ev);
    }

    expect(events).toHaveLength(2);
    expect(events[0].type).toBe('search_call');
    expect(events[1].type).toBe('done');
  });

  it('strips a trailing /v1 from the base URL', async () => {
    localStorage.setItem(
      'nova_ai-settings',
      JSON.stringify({ apiUrl: 'http://127.0.0.1:8000/v1' }),
    );
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(sseResponse(['data: {"type":"done"}\n\n']));

    for await (const _ of streamResearch('q')) {
      // consume
    }

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe('http://127.0.0.1:8000/api/research');
  });
});
