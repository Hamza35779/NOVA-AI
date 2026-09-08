import { useState, useEffect, useCallback } from 'react';
import { Hammer, CheckCircle2, XCircle, ChevronDown, ChevronRight } from 'lucide-react';

interface DevWatchRun {
  command: string;
  status: 'pass' | 'fail';
  returncode?: number;
  failure_type?: string | null;
  output?: string;
  suggestion?: string;
  at?: string;
}

function timeAgo(iso?: string): string {
  if (!iso) return '';
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function RunRow({ run }: { run: DevWatchRun }) {
  const [expanded, setExpanded] = useState(false);
  const pass = run.status === 'pass';

  return (
    <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--color-border)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-3 py-2 text-sm transition-colors cursor-pointer"
        style={{ background: 'var(--color-bg-secondary)' }}
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {pass ? (
          <CheckCircle2 size={14} style={{ color: 'var(--color-success)' }} />
        ) : (
          <XCircle size={14} style={{ color: 'var(--color-danger, var(--color-error, #ef4444))' }} />
        )}
        <span className="font-mono text-xs truncate flex-1 text-left" style={{ color: 'var(--color-text)' }}>
          {run.command}
        </span>
        {run.failure_type && (
          <span
            className="px-1.5 py-0.5 rounded text-[10px] font-medium"
            style={{ background: 'color-mix(in srgb, var(--color-warning) 15%, transparent)', color: 'var(--color-warning)' }}
          >
            {run.failure_type}
          </span>
        )}
        {typeof run.returncode === 'number' && run.returncode !== 0 && (
          <span className="text-[10px] font-mono" style={{ color: 'var(--color-text-tertiary)' }}>
            exit {run.returncode}
          </span>
        )}
        <span className="text-[11px] shrink-0" style={{ color: 'var(--color-text-tertiary)' }}>
          {timeAgo(run.at)}
        </span>
      </button>
      {expanded && (
        <div className="px-3 py-2 text-xs space-y-2" style={{ borderTop: '1px solid var(--color-border)' }}>
          {run.suggestion && (
            <div>
              <div className="hud-label mb-1" style={{ fontSize: 10 }}>Self-healing suggestion</div>
              <pre className="whitespace-pre-wrap font-mono text-[11px] p-2 rounded" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>
                {run.suggestion}
              </pre>
            </div>
          )}
          {run.output && (
            <div>
              <div className="hud-label mb-1" style={{ fontSize: 10 }}>Output (tail)</div>
              <pre className="whitespace-pre-wrap font-mono text-[11px] p-2 rounded max-h-40 overflow-y-auto" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>
                {run.output.slice(-1500)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function DevWatchFeed() {
  const [runs, setRuns] = useState<DevWatchRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchRuns = useCallback(async () => {
    try {
      const base = import.meta.env.VITE_API_URL || '';
      const res = await fetch(`${base}/api/devwatch/runs?limit=20`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setRuns(data.runs || []);
      setError(null);
    } catch {
      setError('Cannot reach dev-watch API — is the server running?');
    }
  }, []);

  useEffect(() => {
    fetchRuns();
    const timer = setInterval(fetchRuns, 15000);
    return () => clearInterval(timer);
  }, [fetchRuns]);

  const failCount = runs.filter((r) => r.status === 'fail').length;

  return (
    <div className="hud-panel p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="hud-label flex items-center gap-2">
          <Hammer size={12} style={{ color: 'var(--color-accent)' }} />
          Build Diagnostics (dev-watch)
        </h3>
        {runs.length > 0 && (
          <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
            {runs.length} run{runs.length === 1 ? '' : 's'}
            {failCount > 0 && (
              <span style={{ color: 'var(--color-danger, var(--color-error, #ef4444))' }}>
                {' '}· {failCount} failed
              </span>
            )}
          </span>
        )}
      </div>

      {error ? (
        <div className="h-32 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span className="hud-mono">{error}</span>
        </div>
      ) : runs.length === 0 ? (
        <div className="h-32 flex flex-col items-center justify-center gap-1 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span>No dev-watch runs recorded yet.</span>
          <span className="text-xs hud-mono">nova dev-watch -c "pytest -q"</span>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5 max-h-80 overflow-y-auto">
          {runs.map((run, i) => (
            <RunRow key={`${run.at}-${i}`} run={run} />
          ))}
        </div>
      )}
    </div>
  );
}
