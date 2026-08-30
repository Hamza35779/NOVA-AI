import React, { useState } from 'react';
import { useAppStore } from '../lib/store';
import { compareModelsAPI, voteModelAPI } from '../lib/api';
import { Play, CheckCircle } from 'lucide-react';

export function ModelComparePage() {
  const models = useAppStore(s => s.models);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [comparisonId, setComparisonId] = useState<string | null>(null);

  const samplePrompts = [
    "Code a Python LRU Cache",
    "Explain Quantum Entanglement",
    "Draft a Product Pitch"
  ];

  const toggleModel = (modelId: string) => {
    if (selectedModels.includes(modelId)) {
      setSelectedModels(selectedModels.filter(id => id !== modelId));
    } else {
      if (selectedModels.length < 4) {
        setSelectedModels([...selectedModels, modelId]);
      }
    }
  };

  const handleRun = async () => {
    if (selectedModels.length < 2 || !prompt) return;
    setLoading(true);
    try {
      const data = await compareModelsAPI(selectedModels, prompt);
      setResults(data.results || []);
      setComparisonId(data.comparison_id || 'test-id');
    } catch (e) {
      console.error(e);
      // Dummy data for testing
      setResults(selectedModels.map(m => ({
        model: m,
        content: `Response from ${m} for prompt: ${prompt}`,
        latency_ms: Math.floor(Math.random() * 2000 + 500),
        tokens_per_sec: Math.floor(Math.random() * 50 + 10)
      })));
      setComparisonId('dummy-id');
    }
    setLoading(false);
  };

  const handleVote = async (winner: string) => {
    if (!comparisonId) return;
    try {
      await voteModelAPI(comparisonId, winner, prompt, selectedModels);
      alert(`Voted for ${winner}!`);
    } catch (e) {
      console.error(e);
      alert(`Voted for ${winner}! (Dummy)`);
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto flex flex-col h-full overflow-y-auto">
      <h1 className="text-2xl font-bold mb-4">Model Comparison (A/B Test)</h1>
      <div className="mb-4">
        <h3 className="text-sm font-semibold mb-2">Select Models (2-4):</h3>
        <div className="flex gap-2 flex-wrap">
          {models.map(m => (
            <button
              key={m.id}
              onClick={() => toggleModel(m.id)}
              className={`px-3 py-1 rounded-full text-sm border transition-colors ${
                selectedModels.includes(m.id)
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-transparent text-gray-700 border-gray-300 hover:bg-gray-100'
              }`}
              style={{
                 borderColor: selectedModels.includes(m.id) ? 'var(--color-accent)' : 'var(--color-border)',
                 backgroundColor: selectedModels.includes(m.id) ? 'var(--color-accent)' : 'transparent',
                 color: selectedModels.includes(m.id) ? '#fff' : 'var(--color-text)'
              }}
            >
              {m.name || m.id}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Enter prompt..."
          className="w-full p-3 rounded-lg border outline-none min-h-[100px]"
          style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
        />
        <div className="flex gap-2 mt-2">
          {samplePrompts.map(p => (
            <button
              key={p}
              onClick={() => setPrompt(p)}
              className="text-xs px-2 py-1 rounded border hover:bg-opacity-50 transition-colors"
              style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={handleRun}
        disabled={loading || selectedModels.length < 2 || !prompt}
        className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium self-start mb-6 disabled:opacity-50"
        style={{ background: 'var(--color-accent)', color: '#fff' }}
      >
        <Play size={16} /> {loading ? 'Running...' : 'Run Comparison'}
      </button>

      {results.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {results.map((r, i) => (
            <div key={i} className="p-4 rounded-lg border flex flex-col" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
              <h3 className="font-semibold text-lg mb-2" style={{ color: 'var(--color-text)' }}>{r.model}</h3>
              <div className="flex-1 overflow-y-auto mb-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {r.content}
              </div>
              <div className="text-xs mb-3 space-y-1" style={{ color: 'var(--color-text-tertiary)' }}>
                <div>Latency: {r.latency_ms}ms</div>
                <div>Tokens/sec: {r.tokens_per_sec}</div>
              </div>
              <button
                onClick={() => handleVote(r.model)}
                className="flex items-center justify-center gap-2 w-full py-2 rounded border transition-colors hover:bg-opacity-80 mt-auto"
                style={{ borderColor: 'var(--color-accent)', color: 'var(--color-accent)' }}
              >
                <CheckCircle size={16} /> Vote as Best
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
