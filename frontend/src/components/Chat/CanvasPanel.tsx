import { useState } from 'react';
import { X, ExternalLink, Maximize2, Minimize2 } from 'lucide-react';

interface CanvasPanelProps {
  title: string;
  html: string;
  artifactId: string;
  fileUri?: string;
  onClose?: () => void;
}

export function CanvasPanel({ title, html, artifactId, fileUri, onClose }: CanvasPanelProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`canvas-panel rounded-xl overflow-hidden border transition-all ${
        expanded ? 'fixed inset-4 z-50 shadow-2xl' : 'relative mt-3'
      }`}
      style={{
        background: 'var(--color-surface, var(--color-bg-secondary))',
        borderColor: 'var(--color-border)',
      }}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-4 py-2"
        style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {/* Canvas icon */}
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <rect x="1" y="1" width="14" height="14" rx="3" stroke="var(--color-accent-purple)" strokeWidth="1.5" />
            <path d="M4 8h8M8 4v8" stroke="var(--color-accent)" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span
            className="text-sm font-semibold truncate"
            style={{ color: 'var(--color-text)' }}
          >
            {title}
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {/* Open in browser */}
          {fileUri && (
            <button
              onClick={() => window.open(fileUri, '_blank')}
              title="Open in browser"
              className="p-1.5 rounded-lg transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <ExternalLink size={13} />
            </button>
          )}
          {/* Expand / collapse */}
          <button
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? 'Collapse' : 'Expand'}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: 'var(--color-text-secondary)' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            {expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          </button>
          {/* Close */}
          {onClose && (
            <button
              onClick={onClose}
              title="Close"
              className="p-1.5 rounded-lg transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Sandboxed iframe rendering the canvas HTML */}
      <iframe
        key={artifactId}
        srcDoc={html}
        sandbox="allow-scripts allow-same-origin"
        title={title}
        className="w-full block"
        style={{
          height: expanded ? 'calc(100% - 40px)' : '420px',
          border: 'none',
          background: 'var(--color-code-bg)',
        }}
      />
    </div>
  );
}
