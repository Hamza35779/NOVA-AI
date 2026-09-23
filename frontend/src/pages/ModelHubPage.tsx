import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getModelCatalog, installModelAPI, watchInstallProgress, type InstallProgress } from '../lib/api';
import { Download, Zap, Star, Code, Brain, Eye, CheckCircle2, XCircle } from 'lucide-react';

// Backend returns { catalog: [...], categories: [...], total_installed } with
// `description` (not `desc`) and lowercase categories. Normalize once so both
// the initial load and the post-install refresh see the same shape.
function normalizeCatalog(data: any): any[] {
  const items = data.catalog || data.models || [];
  return items.map((m: any) => ({
    id: m.id,
    name: m.name,
    params: m.params,
    vram: m.vram,
    size: m.size,
    desc: m.description || m.desc || '',
    category: (m.category || 'General').charAt(0).toUpperCase() + (m.category || 'General').slice(1),
    installed: !!m.installed,
  }));
}

export function ModelHubPage() {
  const [catalog, setCatalog] = useState<any[]>([]);
  const [filter, setFilter] = useState('All');
  const [installing, setInstalling] = useState<string | null>(null);

  const filters = [
    { label: 'All', icon: Star },
    { label: 'Fast', icon: Zap },
    { label: 'General', icon: Star },
    { label: 'Coding', icon: Code },
    { label: 'Reasoning', icon: Brain },
    { label: 'Vision', icon: Eye }
  ];

  useEffect(() => {
    // Backend returns { catalog: [...], categories: [...], total_installed }.
    // The old code read data.models, which doesn't exist — the grid silently
    // rendered empty while the request succeeded.
    getModelCatalog().then(data => {
      setCatalog(normalizeCatalog(data));
    }).catch(e => {
      // Dummy data fallback
      setCatalog([
        { id: 'llama3:8b', name: 'Llama 3 8B', params: '8B', vram: '4GB', desc: 'Fast, capable general-purpose model.', category: 'Fast' },
        { id: 'qwen2.5-coder:7b', name: 'Qwen 2.5 Coder', params: '7B', vram: '4GB', desc: 'Excellent at coding tasks.', category: 'Coding' },
        { id: 'llava:7b', name: 'LLaVA 1.5', params: '7B', vram: '5GB', desc: 'Multimodal vision model.', category: 'Vision' },
      ]);
    });
  }, []);

  const [progress, setProgress] = useState<Record<string, number>>({});
  const [status, setStatus] = useState<Record<string, 'done' | 'error'>>({});
  const cancelWatch = useRef<Record<string, (() => void) | undefined>>({});

  useEffect(() => () => { Object.values(cancelWatch.current).forEach(fn => fn?.()); }, []);

  const handleInstall = useCallback(async (id: string) => {
    setInstalling(id);
    setStatus(s => ({ ...s, [id]: undefined as unknown as 'done' | 'error' }));
    setProgress(p => ({ ...p, [id]: 0 }));
    let taskId = `dl_${id.replace(':', '_')}`;
    let started = false;
    try {
      const resp = await installModelAPI(id);
      if (resp?.task_id) taskId = resp.task_id;
      started = true;
    } catch {
      // Server unreachable — no install possible; show error instead of a
      // fake success.
      setInstalling(null);
      setStatus(s => ({ ...s, [id]: 'error' }));
      return;
    }
    if (!started) { setInstalling(null); return; }
    // Real completion: stream the backend's SSE progress until done/error,
    // then refresh installed state. No more premature success alert.
    cancelWatch.current[id] = watchInstallProgress(
      taskId,
      (p: InstallProgress) => setProgress(pr => ({ ...pr, [id]: p.percent })),
      (final) => {
        cancelWatch.current[id]?.();
        delete cancelWatch.current[id];
        setInstalling(null);
        setProgress(pr => ({ ...pr, [id]: final?.percent ?? 100 }));
        setStatus(s => ({ ...s, [id]: final?.error ? 'error' : 'done' }));
        // Refresh via the shared normalizer — reading data.models here (a field
        // the backend never sends) silently wiped the grid on completion.
        getModelCatalog().then(data => setCatalog(normalizeCatalog(data))).catch(() => {});
      },
    );
  }, []);

  const filtered = filter === 'All' ? catalog : catalog.filter(m => m.category === filter);

  return (
    <div className="p-6 max-w-6xl mx-auto flex flex-col h-full overflow-y-auto">
      <h1 className="text-2xl font-bold mb-6">Model Hub</h1>
      {catalog.length === 0 && (
        <div className="text-sm py-8 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
          Loading catalog…
        </div>
      )}
      
      <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
        {filters.map(f => {
          const Icon = f.icon;
          return (
            <button
              key={f.label}
              onClick={() => setFilter(f.label)}
              className="flex items-center gap-2 px-4 py-2 rounded-full border text-sm transition-colors shrink-0"
              style={{
                borderColor: filter === f.label ? 'var(--color-accent)' : 'var(--color-border)',
                background: filter === f.label ? 'var(--color-accent)' : 'transparent',
                color: filter === f.label ? '#fff' : 'var(--color-text)'
              }}
            >
              <Icon size={16} /> {f.label}
            </button>
          )
        })}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map(m => {
          const isInstalled = !!(m.installed || status[m.id] === 'done');
          return (
          <div key={m.id} className="p-5 rounded-lg border flex flex-col" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
            <h3 className="font-semibold text-lg mb-1" style={{ color: 'var(--color-text)' }}>{m.name}</h3>
            <p className="text-sm mb-3 flex-1" style={{ color: 'var(--color-text-secondary)' }}>{m.desc}</p>
            <div className="flex gap-3 text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>
              <span>Params: {m.params}</span>
              <span>VRAM: {m.vram}</span>
              {m.size && <span>Size: {m.size}</span>}
              {isInstalled && (
                <span className="px-1.5 rounded" style={{ background: 'var(--color-success)', color: '#fff' }}>installed</span>
              )}
            </div>
            
            <button
              onClick={() => handleInstall(m.id)}
              disabled={installing === m.id || isInstalled}
              className="flex items-center justify-center gap-2 w-full py-2 rounded border transition-colors font-medium mt-auto"
              style={{ 
                borderColor: 'var(--color-accent)', 
                color: installing === m.id ? 'var(--color-text-secondary)' : 'var(--color-accent)',
                opacity: installing === m.id ? 0.7 : 1
              }}
            >
              {isInstalled ? <CheckCircle2 size={16} /> : status[m.id] === 'error' ? <XCircle size={16} /> : <Download size={16} />}
              {installing === m.id
                ? `Installing... ${progress[m.id] ?? 0}%`
                : isInstalled
                  ? 'Installed'
                  : status[m.id] === 'error'
                    ? 'Failed — retry'
                    : 'Install'}
            </button>
            {installing === m.id && (
              <div className="w-full rounded-full h-1.5 mt-2" style={{ background: 'var(--color-border)' }}>
                <div className="h-1.5 rounded-full transition-all" style={{ background: 'var(--color-accent)', width: `${progress[m.id] ?? 0}%` }}></div>
              </div>
            )}
          </div>
          );
        })}
      </div>
    </div>
  );
}
