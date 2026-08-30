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
    <div className="flex flex-col h-full bg-[#0F0B1E] text-white border-l border-white/10">
      <div className="p-4 border-b border-white/10 flex items-center gap-2">
        <h2 className="text-xl font-bold">Document Chat</h2>
        <div className="bg-[#1E1533] px-3 py-1 rounded-full text-xs text-[#06B6D4] flex items-center gap-1">
          <FileText size={14} />
          {selectedDocId ? '1 Document' : 'All Documents'}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
            <div className={`max-w-[80%] rounded-xl p-4 ${msg.role === 'user' ? 'bg-[#7C3AED] text-white' : 'bg-[#1E1533] text-gray-200'}`}>
              <p className="whitespace-pre-wrap">{msg.content}</p>
              
              {msg.citations && msg.citations.length > 0 && (
                <div className="mt-4 border-t border-white/10 pt-3">
                  <p className="text-xs text-gray-400 mb-2">Sources:</p>
                  <div className="space-y-2">
                    {msg.citations.map((cit, cIdx) => (
                      <div key={cIdx} className="bg-black/20 rounded-lg overflow-hidden">
                        <button 
                          onClick={() => setExpandedCitation(expandedCitation === idx + '-' + cIdx ? null : idx + '-' + cIdx as any)}
                          className="w-full px-3 py-2 text-left text-xs flex items-center justify-between hover:bg-black/30"
                        >
                          <span className="truncate text-[#06B6D4]">{cit.title || cit.filename || 'Source'}</span>
                          {expandedCitation === idx + '-' + cIdx ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                        {expandedCitation === idx + '-' + cIdx && (
                          <div className="px-3 py-2 text-xs text-gray-400 bg-black/40 border-t border-white/5">
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
          <div className="flex items-center gap-2 text-gray-400">
            <Loader2 size={16} className="animate-spin" />
            <span className="text-sm">Searching documents...</span>
          </div>
        )}
      </div>

      <div className="p-4 border-t border-white/10">
        <div className="flex items-center gap-2 bg-[#1E1533] rounded-xl p-2 border border-white/5 focus-within:border-[#7C3AED] transition">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder="Ask a question about the documents..."
            className="flex-1 bg-transparent border-none outline-none text-white px-2 placeholder-gray-500"
          />
          <button 
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="p-2 bg-[#7C3AED] hover:bg-purple-600 disabled:opacity-50 disabled:hover:bg-[#7C3AED] rounded-lg transition text-white"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
