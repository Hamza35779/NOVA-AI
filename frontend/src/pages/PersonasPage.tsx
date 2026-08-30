import React, { useState, useEffect } from 'react';
import { listPersonas, createPersona, deletePersonaAPI, setActivePersonaAPI } from '../lib/api';
import { Plus, User, Check, Trash } from 'lucide-react';

export function PersonasPage() {
  const [personas, setPersonas] = useState<any[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    name: '',
    avatar: '🤖',
    description: '',
    system_prompt: '',
    temperature: 0.7
  });

  const loadPersonas = async () => {
    try {
      const data = await listPersonas();
      setPersonas(data.personas || []);
      const active = (data.personas || []).find((p: any) => p.is_active);
      if (active) setActiveId(active.id);
    } catch (e) {
      setPersonas([
        { id: '1', name: 'Senior Architect', avatar: '🏛️', description: 'Expert in system design and scalable software.', is_active: true },
        { id: '2', name: 'Socratic Tutor', avatar: '🦉', description: 'Guides you to the answer with questions.', is_active: false }
      ]);
      setActiveId('1');
    }
  };

  useEffect(() => {
    loadPersonas();
  }, []);

  const handleCreate = async () => {
    try {
      await createPersona(formData);
    } catch (e) {
      setPersonas([...personas, { id: Date.now().toString(), ...formData }]);
    }
    setShowModal(false);
    loadPersonas();
  };

  const handleSetActive = async (id: string) => {
    try {
      await setActivePersonaAPI(id);
    } catch (e) {
      // ignore
    }
    setActiveId(id);
  };

  return (
    <div className="p-6 max-w-6xl mx-auto flex flex-col h-full overflow-y-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Personas Manager</h1>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors"
          style={{ background: 'var(--color-accent)', color: '#fff' }}
        >
          <Plus size={16} /> Create Persona
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {personas.map(p => (
          <div key={p.id} className="p-5 rounded-lg border flex flex-col relative" style={{ background: 'var(--color-bg-secondary)', borderColor: activeId === p.id ? 'var(--color-accent)' : 'var(--color-border)' }}>
            <div className="text-4xl mb-2">{p.avatar}</div>
            <h3 className="font-semibold text-lg mb-1" style={{ color: 'var(--color-text)' }}>{p.name}</h3>
            <p className="text-sm mb-4 flex-1" style={{ color: 'var(--color-text-secondary)' }}>{p.description}</p>
            
            <div className="flex gap-2 mt-auto">
              <button
                onClick={() => handleSetActive(p.id)}
                className={`flex-1 flex items-center justify-center gap-2 py-2 rounded border text-sm transition-colors ${activeId === p.id ? 'bg-opacity-10' : ''}`}
                style={{ 
                  borderColor: activeId === p.id ? 'var(--color-accent)' : 'var(--color-border)', 
                  color: activeId === p.id ? 'var(--color-accent)' : 'var(--color-text)',
                  backgroundColor: activeId === p.id ? 'var(--color-accent-subtle)' : 'transparent'
                }}
              >
                <Check size={16} /> {activeId === p.id ? 'Active' : 'Set Active'}
              </button>
              <button className="p-2 border rounded hover:bg-red-50 hover:text-red-600 hover:border-red-600 transition-colors" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}>
                <Trash size={16} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="w-full max-w-md rounded-lg shadow-xl p-6 flex flex-col gap-4" style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}>
            <h2 className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>Create New Persona</h2>
            
            <input placeholder="Name (e.g. Code Reviewer)" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} className="p-2 rounded border bg-transparent w-full" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }} />
            <input placeholder="Avatar Emoji (e.g. 👾)" value={formData.avatar} onChange={e => setFormData({...formData, avatar: e.target.value})} className="p-2 rounded border bg-transparent w-full" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }} />
            <input placeholder="Description" value={formData.description} onChange={e => setFormData({...formData, description: e.target.value})} className="p-2 rounded border bg-transparent w-full" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }} />
            <textarea placeholder="System Prompt (You are a helpful assistant...)" value={formData.system_prompt} onChange={e => setFormData({...formData, system_prompt: e.target.value})} className="p-2 rounded border bg-transparent w-full min-h-[100px]" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }} />
            
            <div>
              <label className="text-sm block mb-1" style={{ color: 'var(--color-text-secondary)' }}>Temperature: {formData.temperature}</label>
              <input type="range" min="0" max="2" step="0.1" value={formData.temperature} onChange={e => setFormData({...formData, temperature: parseFloat(e.target.value)})} className="w-full" />
            </div>

            <div className="flex gap-2 mt-2 justify-end">
              <button onClick={() => setShowModal(false)} className="px-4 py-2 rounded text-sm hover:opacity-80" style={{ color: 'var(--color-text-secondary)' }}>Cancel</button>
              <button onClick={handleCreate} className="px-4 py-2 rounded text-sm text-white" style={{ background: 'var(--color-accent)' }}>Create</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
