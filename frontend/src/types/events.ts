// Standardized SSE agent-event contract.
// Fixture from PROJECT_IMPROVEMENTS_EXTENDED.md §10.
// Backend should emit: token | tool_start | tool_end | done | error with request_id + seq.

export type AgentEvent =
  | { kind: "token"; request_id: string; seq: number; delta: string }
  | { kind: "tool_start"; request_id: string; seq: number; tool: string }
  | { kind: "tool_end"; request_id: string; seq: number; tool: string; ok: boolean }
  | { kind: "done"; request_id: string; seq: number; cost_usd: number }
  | { kind: "error"; request_id: string; seq: number; message: string };
