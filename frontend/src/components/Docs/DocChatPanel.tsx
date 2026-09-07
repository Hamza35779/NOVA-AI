import React, { useState } from 'react';
import { Send, Loader2, ChevronDown, ChevronRight, FileText } from 'lucide-react';
import { chatWithDocs } from '../../lib/api';

export function DocChatPanel({ selectedDocId }: { selectedDocId: string | null }) {
  const [messages, setMessages] = useState<{role: string, content: string, citations?: any[]}[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [expandedCitation, setExpandedCitation] = useState<string | null>(null);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    const userMsg = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const res = await chatWithDocs(userMsg.content, selectedDocId ? [selectedDocId] : []);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: res.answer || res.reply || res.content || 'No response',
        citations: res.citations || res.sources || []
      }]);
    } catch (e: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + e.message }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full" style={{ borderLeft: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
      <div className="p-4 flex items-center gap-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
        <h2 className="text-xl font-bold">Document Chat</h2>
        <div
          className="px-3 py-1 rounded-full text-xs flex items-center gap-1"
          style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-accent)' }}
        >
          <FileText size={14} />
          {selectedDocId ? '1 Document' : 'All Documents'}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
            <div
              className="max-w-[80%] rounded-xl p-4"
              style={
                msg.role === 'user'
                  ? { background: 'var(--color-user-bubble)', color: 'var(--color-user-bubble-text)' }
                  : { background: 'var(--color-bg-secondary)', color: 'var(--color-text)' }
              }
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>

              {msg.citations && msg.citations.length > 0 && (
                <div className="mt-4 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
                  <p className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>Sources:</p>
                  <div className="space-y-2">
                    {msg.citations.map((cit, cIdx) => (
                      <div key={cIdx} className="rounded-lg overflow-hidden" style={{ background: 'var(--color-bg)' }}>
                        <button
                          onClick={() => setExpandedCitation(expandedCitation === idx + '-' + cIdx ? null : idx + '-' + cIdx as any)}
                          className="w-full px-3 py-2 text-left text-xs flex items-center justify-between cursor-pointer"
                        >
                          <span className="truncate" style={{ color: 'var(--color-accent)' }}>{cit.title || cit.filename || 'Source'}</span>
                          {expandedCitation === idx + '-' + cIdx ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                        {expandedCitation === idx + '-' + cIdx && (
                          <div className="px-3 py-2 text-xs" style={{ color: 'var(--color-text-secondary)', borderTop: '1px solid var(--color-border-subtle)' }}>
                            {cit.text || cit.chunk || 'No preview available'}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2" style={{ color: 'var(--color-text-secondary)' }}>
            <Loader2 size={16} className="animate-spin" />
            <span className="text-sm">Searching documents...</span>
          </div>
        )}
      </div>

      <div className="p-4" style={{ borderTop: '1px solid var(--color-border)' }}>
        <div
          className="flex items-center gap-2 rounded-xl p-2 transition"
          style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }}
        >
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder="Ask a question about the documents..."
            className="flex-1 bg-transparent border-none outline-none px-2"
            style={{ color: 'var(--color-text)' }}
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="p-2 rounded-lg transition cursor-pointer disabled:opacity-50"
            style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)' }}
            onMouseEnter={(e) => {
              if (!loading && input.trim()) e.currentTarget.style.background = 'var(--color-accent-purple-hover)';
            }}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-accent-purple)')}
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
