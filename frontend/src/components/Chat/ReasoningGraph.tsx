import { useEffect, useRef, useState } from 'react';
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDashed,
  Hammer,
  RefreshCcw,
  ShieldAlert,
  Wrench,
  XCircle,
} from 'lucide-react';

export type ReasoningStepKind =
  | 'plan'
  | 'thought'
  | 'tool_call'
  | 'observation'
  | 'repair_attempt'
  | 'repair_success'
  | 'repair_exhausted';

export interface ReasoningStep {
  id: string;
  kind: ReasoningStepKind;
  label: string;
  detail?: string;
  status: 'pending' | 'running' | 'done' | 'error';
  timestamp: number;
  /** Repair iteration this step belongs to (0 = main loop) */
  repairIndex?: number;
}

interface ReasoningGraphProps {
  steps: ReasoningStep[];
  /** Live = the agent is still running; shows pulse on last step */
  isLive?: boolean;
  /** Collapse by default once the run completes */
  defaultOpen?: boolean;
  maxHeight?: number;
}

const KIND_META: Record<
  ReasoningStepKind,
  { icon: React.ReactNode; text: string; ring: string }
> = {
  plan: {
    icon: <Brain className="h-3.5 w-3.5" />,
    text: 'var(--color-accent-purple)',
    ring: 'var(--color-accent-purple-subtle)',
  },
  thought: {
    icon: <CircleDashed className="h-3.5 w-3.5" />,
    text: 'var(--color-text-secondary)',
    ring: 'var(--color-border)',
  },
  tool_call: {
    icon: <Wrench className="h-3.5 w-3.5" />,
    text: 'var(--color-accent)',
    ring: 'var(--color-accent-subtle)',
  },
  observation: {
    icon: <Hammer className="h-3.5 w-3.5" />,
    text: 'var(--color-text-secondary)',
    ring: 'var(--color-border)',
  },
  repair_attempt: {
    icon: <RefreshCcw className="h-3.5 w-3.5" />,
    text: 'var(--color-accent-amber)',
    ring: 'var(--color-accent-amber-subtle)',
  },
  repair_success: {
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    text: 'var(--color-success)',
    ring: 'var(--color-accent-subtle)',
  },
  repair_exhausted: {
    icon: <ShieldAlert className="h-3.5 w-3.5" />,
    text: 'var(--color-error)',
    ring: 'var(--color-accent-subtle)',
  },
};

function StepRow({
  step,
  isLast,
  isLive,
}: {
  step: ReasoningStep;
  isLast: boolean;
  isLive: boolean;
}) {
  const [open, setOpen] = useState(false);
  const meta = KIND_META[step.kind];
  const active = isLast && isLive && step.status === 'running';
  const expandable = Boolean(step.detail) && step.detail!.length > 0;
  const repairTag =
    step.repairIndex && step.repairIndex > 0
      ? ` · repair ${step.repairIndex}`
      : '';

  return (
    <div className="relative pl-7" data-step-kind={step.kind}>
      {/* Vertical rail */}
      {!isLast && (
        <span
          aria-hidden
          className="absolute left-[11px] top-6 h-[calc(100%-14px)] w-px bg-[var(--color-border)]"
        />
      )}
      {/* Node dot */}
      <span
        aria-hidden
        className={`absolute left-0 top-1 flex h-6 w-6 items-center justify-center rounded-full border ${
          active ? 'animate-pulse' : ''
        }`}
        style={{
          borderColor: meta.ring,
          backgroundColor: meta.ring,
          color: meta.text,
        }}
      >
        {step.status === 'error' ? (
          <XCircle className="h-3.5 w-3.5" />
        ) : (
          meta.icon
        )}
      </span>

      <button
        type="button"
        onClick={() => expandable && setOpen((o) => !o)}
        className={`w-full rounded-md px-1 py-0.5 text-left transition-colors ${
          expandable ? 'cursor-pointer hover:bg-[var(--color-bg-tertiary)]' : 'cursor-default'
        }`}
        aria-expanded={open}
      >
        <span className="flex items-center gap-1.5">
          <span
            className="text-xs font-medium"
            style={{ color: meta.text }}
          >
            {step.label}
            <span className="font-normal text-[var(--color-text-tertiary)]">
              {repairTag}
            </span>
          </span>
          {expandable && (
            <span className="ml-auto text-[var(--color-text-tertiary)]">
              {open ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </span>
          )}
        </span>
        {open && step.detail && (
          <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg)] p-2 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
            {step.detail}
          </pre>
        )}
      </button>
    </div>
  );
}

/**
 * Interactive reasoning graph — a vertical flow of the agent's plan,
 * thoughts, tool calls, observations, and self-repair iterations.
 * Each node expands to show its full detail (stderr, tool output, …).
 */
export function ReasoningGraph({
  steps,
  isLive = false,
  defaultOpen = true,
  maxHeight = 420,
}: ReasoningGraphProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Autoscroll to newest step while live
  useEffect(() => {
    if (isLive && open) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [steps.length, isLive, open]);

  if (steps.length === 0) return null;

  return (
    <div
      className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)]"
      data-testid="reasoning-graph"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2"
        aria-expanded={open}
      >
        <Brain className="h-4 w-4 text-[var(--color-accent)]" />
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
          Reasoning
        </span>
        <span className="rounded-full bg-[var(--color-bg-tertiary)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text-tertiary)]">
          {steps.length}
        </span>
        <span className="ml-auto text-[var(--color-text-tertiary)]">
          {open ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </span>
      </button>

      {open && (
        <div
          className="overflow-y-auto px-3 pb-3 pt-1"
          style={{ maxHeight }}
        >
          <div className="flex flex-col gap-2">
            {steps.map((s, i) => (
              <StepRow
                key={s.id}
                step={s}
                isLast={i === steps.length - 1}
                isLive={isLive}
              />
            ))}
          </div>
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}

/** Store helpers: build steps from live agent events */

let stepCounter = 0;
export function makeStep(
  kind: ReasoningStepKind,
  label: string,
  detail?: string,
  status: ReasoningStep['status'] = 'done',
  repairIndex?: number,
): ReasoningStep {
  stepCounter += 1;
  return {
    id: `rs_${stepCounter}_${Date.now()}`,
    kind,
    label,
    detail,
    status,
    timestamp: Date.now(),
    repairIndex,
  };
}

/** Derive a step from a ReAct-parsed assistant message (thought/action) */
export function stepsFromThoughtAction(
  thought: string,
  action: string | null,
  actionInput: string | null,
): ReasoningStep[] {
  const out: ReasoningStep[] = [];
  if (thought.trim()) {
    out.push(makeStep('thought', 'Thought', thought.trim()));
  }
  if (action) {
    out.push(
      makeStep('tool_call', `Call ${action}`, actionInput ?? undefined, 'running'),
    );
  }
  return out;
}
