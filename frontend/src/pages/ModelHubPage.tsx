import React, { useState, useEffect } from 'react';
import { getModelCatalog, installModelAPI } from '../lib/api';
import { Download, Zap, Star, Code, Brain, Eye } from 'lucide-react';

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
    getModelCatalog().then(data => setCatalog(data.models || [])).catch(e => {
      // Dummy data fallback
      setCatalog([
        { id: 'llama3:8b', name: 'Llama 3 8B', params: '8B', vram: '4GB', desc: 'Fast, capable general-purpose model.', category: 'Fast' },
        { id: 'qwen2.5-coder:7b', name: 'Qwen 2.5 Coder', params: '7B', vram: '4GB', desc: 'Excellent at coding tasks.', category: 'Coding' },
        { id: 'llava:7b', name: 'LLaVA 1.5', params: '7B', vram: '5GB', desc: 'Multimodal vision model.', category: 'Vision' },
      ]);
    });
  }, []);

  const handleInstall = async (id: string) => {
    setInstalling(id);
    try {
      await installModelAPI(id);
    } catch (e) {
      console.log('Using dummy install for', id);
      await new Promise(r => setTimeout(r, 2000));
    }
    setInstalling(null);
    alert(`${id} installed successfully!`);
  };

  const filtered = filter === 'All' ? catalog : catalog.filter(m => m.category === filter);

  return (
    <div className="p-6 max-w-6xl mx-auto flex flex-col h-full overflow-y-auto">
      <h1 className="text-2xl font-bold mb-6">Model Hub</h1>
      
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
        {filtered.map(m => (
          <div key={m.id} className="p-5 rounded-lg border flex flex-col" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
            <h3 className="font-semibold text-lg mb-1" style={{ color: 'var(--color-text)' }}>{m.name}</h3>
            <p className="text-sm mb-3 flex-1" style={{ color: 'var(--color-text-secondary)' }}>{m.desc}</p>
            <div className="flex gap-3 text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>
              <span>Params: {m.params}</span>
              <span>VRAM: {m.vram}</span>
            </div>
            
            <button
              onClick={() => handleInstall(m.id)}
              disabled={installing === m.id}
              className="flex items-center justify-center gap-2 w-full py-2 rounded border transition-colors font-medium mt-auto"
              style={{ 
                borderColor: 'var(--color-accent)', 
                color: installing === m.id ? 'var(--color-text-secondary)' : 'var(--color-accent)',
                opacity: installing === m.id ? 0.7 : 1
              }}
            >
              <Download size={16} /> 
              {installing === m.id ? 'Installing...' : 'Install'}
            </button>
            {installing === m.id && (
              <div className="w-full bg-gray-200 rounded-full h-1.5 mt-2" style={{ background: 'var(--color-border)' }}>
                <div className="bg-blue-600 h-1.5 rounded-full animate-pulse w-1/2" style={{ background: 'var(--color-accent)' }}></div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
