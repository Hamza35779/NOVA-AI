import { useRef, useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { useAppStore } from '../../lib/store';
import { 
  Sparkles, PanelRightOpen, PanelRightClose, Database, MessageSquare, X,
  FileText, Mail, Calendar, GitCompare, Code2, Globe, UserCheck, ArrowRight
} from 'lucide-react';
import { listConnectors } from '../../lib/connectors-api';
import { listPersonas, setActivePersonaAPI } from '../../lib/api';
import { toast } from 'sonner';

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function ChatArea() {
  const messages = useAppStore((s) => s.messages);
  const streamState = useAppStore((s) => s.streamState);
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  // Check if any data sources are connected
  const [hasConnectedSources, setHasConnectedSources] = useState<boolean | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [personas, setPersonas] = useState<any[]>([]);
  const [activePersonaId, setActivePersonaId] = useState<string>('preset_default');

  useEffect(() => {
    listConnectors()
      .then((list) => setHasConnectedSources(list.some((c) => c.connected)))
      .catch(() => setHasConnectedSources(null));

    listPersonas()
      .then((res) => {
        setPersonas(res.personas || []);
        setActivePersonaId(res.active_id || 'preset_default');
      })
      .catch(() => {});
  }, []);

  const handleSelectPersona = async (id: string) => {
    setActivePersonaId(id);
    try {
      await setActivePersonaAPI(id);
      const chosen = personas.find(p => p.id === id);
      toast.success(`Active Persona: ${chosen?.name || id}`);
    } catch {}
  };

  useEffect(() => {
    if (shouldAutoScroll.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, streamState.content]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    shouldAutoScroll.current = scrollHeight - scrollTop - clientHeight < 100;
  };

  const isEmpty = messages.length === 0 && !streamState.isStreaming;
  const PanelIcon = systemPanelOpen ? PanelRightClose : PanelRightOpen;

  const quickTasks = [
    {
      title: 'Document Analysis',
      desc: 'Chat with PDFs, DOCX, and CSV spreadsheets',
      icon: FileText,
      color: '#06B6D4',
      bg: 'rgba(6, 182, 212, 0.1)',
      action: () => navigate('/docs'),
    },
    {
      title: 'Live Web Search',
      desc: 'Real-time grounded research with sources',
      icon: Globe,
      color: '#3B82F6',
      bg: 'rgba(59, 130, 246, 0.1)',
      action: () => {
        const el = document.querySelector('textarea');
        if (el) {
          el.focus();
          el.placeholder = 'Ask with live Web Search...';
        }
        toast.info('Web Search mode ready! Type your question below.');
      },
    },
    {
      title: 'Code Architect',
      desc: 'Scaffold Rust, Go, Python, and TypeScript apps',
      icon: Code2,
      color: '#10B981',
      bg: 'rgba(16, 185, 129, 0.1)',
      action: () => {
        const el = document.querySelector('textarea');
        if (el) {
          el.value = 'Create a new project scaffold for ';
          el.focus();
        }
      },
    },
    {
      title: 'Email Assistant',
      desc: 'Triage inbox, summarize threads & draft replies',
      icon: Mail,
      color: '#EC4899',
      bg: 'rgba(236, 72, 153, 0.1)',
      action: () => navigate('/email'),
    },
    {
      title: 'Daily Briefing & Prep',
      desc: 'Morning schedule briefing & meeting notes',
      icon: Calendar,
      color: '#F59E0B',
      bg: 'rgba(245, 158, 11, 0.1)',
      action: () => navigate('/calendar'),
    },
    {
      title: 'Compare Models',
      desc: 'A/B benchmark 2-4 models side-by-side',
      icon: GitCompare,
      color: '#8B5CF6',
      bg: 'rgba(139, 92, 246, 0.1)',
      action: () => navigate('/compare'),
    },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Top action bar: Persona Selector & System Panel Toggle */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 shrink-0">
        <div className="flex items-center gap-1.5 overflow-x-auto py-0.5 max-w-[80%]">
          <span className="text-xs text-gray-400 font-medium mr-1 flex items-center gap-1">
            <UserCheck size={13} /> Persona:
          </span>
          {personas.slice(0, 5).map((p) => {
            const isActive = p.id === activePersonaId;
            return (
              <button
                key={p.id}
                onClick={() => handleSelectPersona(p.id)}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition cursor-pointer flex items-center gap-1 shrink-0 ${
                  isActive
                    ? 'bg-[#7C3AED] text-white shadow-sm'
                    : 'bg-white/5 text-gray-400 hover:bg-white/10 hover:text-gray-200'
                }`}
                title={p.description}
              >
                <span>{p.avatar || '🤖'}</span>
                <span>{p.name.split(' ')[0]}</span>
              </button>
            );
          })}
        </div>
        <button
          onClick={toggleSystemPanel}
          className="p-1.5 rounded-md transition-colors cursor-pointer text-gray-400 hover:text-white"
          title={`${systemPanelOpen ? 'Hide' : 'Show'} system panel (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+I)`}
        >
          <PanelIcon size={16} />
        </button>
      </div>

      {/* Data sources banner */}
      {hasConnectedSources === false && !bannerDismissed && (
        <div
          className="mx-4 mt-2 flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm shrink-0"
          style={{
            background: 'var(--color-accent-subtle)',
            border: '1px solid var(--color-border)',
          }}
        >
          <Database size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <span style={{ color: 'var(--color-text-secondary)', flex: 1 }}>
            Connect your data sources (Gmail, iMessage, Slack, etc.) to get personalized answers.
          </span>
          <button
            onClick={() => navigate('/data-sources')}
            className="px-3 py-1 rounded text-xs font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', border: 'none' }}
          >
            Connect
          </button>
          <button
            onClick={() => setBannerDismissed(true)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)', background: 'transparent', border: 'none' }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center min-h-[80%] max-w-4xl mx-auto px-4 py-8">
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4 shadow-lg"
              style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.2), rgba(6,182,212,0.2))', border: '1px solid rgba(124,58,237,0.4)', color: 'var(--color-accent)' }}
            >
              <Sparkles size={28} className="text-[#06B6D4]" />
            </div>
            <h2 className="text-2xl font-bold mb-2 tracking-tight text-white">
              {getGreeting()}
            </h2>
            <p className="text-sm text-center max-w-md mb-8 text-gray-400">
              Private, local AI workstation. What would you like to accomplish?
            </p>

            {/* 6 Interactive Task Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 w-full">
              {quickTasks.map((t, idx) => {
                const Icon = t.icon;
                return (
                  <button
                    key={idx}
                    onClick={t.action}
                    className="flex flex-col items-start p-4 rounded-xl text-left transition-all duration-200 cursor-pointer group hover:-translate-y-0.5 border"
                    style={{
                      background: 'rgba(255, 255, 255, 0.02)',
                      borderColor: 'rgba(255, 255, 255, 0.08)',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = t.color;
                      e.currentTarget.style.background = t.bg;
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                      e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)';
                    }}
                  >
                    <div className="flex items-center justify-between w-full mb-2.5">
                      <div
                        className="p-2 rounded-lg"
                        style={{ background: t.bg, color: t.color }}
                      >
                        <Icon size={18} />
                      </div>
                      <ArrowRight size={14} className="text-gray-500 group-hover:translate-x-1 group-hover:text-white transition-all" />
                    </div>
                    <h3 className="text-sm font-semibold text-white mb-1">{t.title}</h3>
                    <p className="text-xs text-gray-400 leading-relaxed">{t.desc}</p>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="max-w-[var(--chat-max-width)] mx-auto px-4 py-6">
            {messages.map((msg, i) => {
              const isLastAssistant =
                i === messages.length - 1 && msg.role === 'assistant';
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isLive={isLastAssistant && streamState.isStreaming}
                />
              );
            })}
            {(() => {
              if (!streamState.isStreaming || streamState.content !== '') return null;
              // For research messages the ResearchTimeline handles its own
              // pre-content loading state — suppress the generic dots.
              const last = messages[messages.length - 1];
              if (last?.role === 'assistant' && last.isResearch) return null;
              return (
                <div className="flex justify-start mb-4">
                  <StreamingDots phase={streamState.phase} />
                </div>
              );
            })()}
          </div>
        )}
      </div>
      <InputArea />
    </div>
  );
}
