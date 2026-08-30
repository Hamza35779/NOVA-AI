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
        background: 'var(--color-surface-raised, #1E1533)',
        borderColor: 'rgba(124, 58, 237, 0.35)',
      }}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-4 py-2"
        style={{ borderBottom: '1px solid rgba(124, 58, 237, 0.2)' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {/* Canvas icon */}
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <rect x="1" y="1" width="14" height="14" rx="3" stroke="#7C3AED" strokeWidth="1.5" />
            <path d="M4 8h8M8 4v8" stroke="#06B6D4" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span
            className="text-sm font-semibold truncate"
            style={{ color: 'var(--color-text-primary, #F1F5F9)' }}
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
              className="p-1.5 rounded-lg transition-colors hover:bg-white/10"
              style={{ color: 'var(--color-text-secondary, #94A3B8)' }}
            >
              <ExternalLink size={13} />
            </button>
          )}
          {/* Expand / collapse */}
          <button
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? 'Collapse' : 'Expand'}
            className="p-1.5 rounded-lg transition-colors hover:bg-white/10"
            style={{ color: 'var(--color-text-secondary, #94A3B8)' }}
          >
            {expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          </button>
          {/* Close */}
          {onClose && (
            <button
              onClick={onClose}
              title="Close"
              className="p-1.5 rounded-lg transition-colors hover:bg-white/10"
              style={{ color: 'var(--color-text-secondary, #94A3B8)' }}
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
          background: '#0F0B1E',
        }}
      />
    </div>
  );
}
