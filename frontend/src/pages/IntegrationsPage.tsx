import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Layers,
  MessageSquare,
  FileText,
  Terminal,
  Share2,
  CheckCircle2,
  AlertCircle,
  Play,
  Search,
  Sparkles,
  Network,
  Presentation,
  Globe,
} from 'lucide-react';
import { toast } from 'sonner';

interface AppItem {
  id: string;
  name: string;
  description: string;
  status: string;
  enabled: boolean;
}

interface CategoryGroup {
  category: string;
  apps: AppItem[];
}

const FALLBACK_CATEGORIES: CategoryGroup[] = [
  {
    category: 'Communication & Messaging',
    apps: [
      { id: 'whatsapp', name: 'WhatsApp', description: 'Send & receive messages via WhatsApp Web QR bridge', status: 'Built-in', enabled: true },
      { id: 'telegram', name: 'Telegram', description: 'Telegram Bot API for groups and private channels', status: 'Built-in', enabled: false },
      { id: 'slack', name: 'Slack', description: 'Slack workspace messaging & automated webhook alerts', status: 'Built-in', enabled: false },
      { id: 'gmail', name: 'Gmail & Email (SMTP)', description: 'Email dispatch for leave requests & team notifications', status: 'Built-in', enabled: true },
    ],
  },
  {
    category: 'Developer & Agent CLIs',
    apps: [
      { id: 'claude', name: 'Claude Code CLI', description: 'Anthropic Claude terminal pair-programmer for code synthesis', status: 'CLI Ready', enabled: true },
      { id: 'gemini', name: 'Gemini CLI', description: 'Google Gemini terminal agent for multi-file repo edits', status: 'CLI Ready', enabled: true },
      { id: 'opencode', name: 'OpenCode CLI', description: 'Autonomous repository builder, refactorer, and test generator', status: 'CLI Ready', enabled: true },
      { id: 'aider', name: 'Aider AI Pair', description: 'Git-integrated terminal pair-programming assistant', status: 'CLI Ready', enabled: false },
      { id: 'github', name: 'GitHub Integration', description: 'Manage issues, PR reviews, branches, and repo actions', status: 'Skill Ready', enabled: true },
    ],
  },
  {
    category: 'Documents, Simulations & Formats',
    apps: [
      { id: 'cisco_packet_tracer', name: 'Cisco Packet Tracer', description: 'Generate router/switch configs (.cfg), VLANs, OSPF, and network topologies', status: 'Active', enabled: true },
      { id: 'docx_generator', name: 'Microsoft Word (.docx)', description: 'Create structured Word documents with formatted tables & headings', status: 'Active', enabled: true },
      { id: 'pptx_generator', name: 'PowerPoint (.pptx)', description: 'Generate executive slide decks with themes & bullet points', status: 'Active', enabled: true },
      { id: 'pdf_generator', name: 'PDF Report Suite (.pdf)', description: 'Export publication-grade PDF documents & technical whitepapers', status: 'Active', enabled: true },
    ],
  },
  {
    category: 'Notes & Knowledge',
    apps: [
      { id: 'notion', name: 'Notion', description: 'Sync database records, pages, and structured knowledge wikis', status: 'Skill Ready', enabled: true },
      { id: 'obsidian', name: 'Obsidian', description: 'Read and write local markdown knowledge vaults', status: 'Skill Ready', enabled: true },
      { id: 'memory_wiki', name: 'Active Memory Wiki', description: 'Local persistent long-term AI memory store', status: 'Active', enabled: true },
    ],
  },
];

export function IntegrationsPage() {
  const [categories, setCategories] = useState<CategoryGroup[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [debouncedQuery, setDebouncedQuery] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce search input (150ms)
  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => setDebouncedQuery(value.trim().toLowerCase()), 150);
  };

  useEffect(() => () => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
  }, []);

  const fetchIntegrations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/v1/integrations');
      if (res.ok) {
        const data = await res.json();
        setCategories(data.categories || []);
      } else {
        setError(`Failed to load integrations (HTTP ${res.status}). Showing offline catalog.`);
        setCategories(FALLBACK_CATEGORIES);
      }
    } catch (err) {
      console.error(err);
      setError('Could not reach the integrations API. Showing offline catalog.');
      setCategories(FALLBACK_CATEGORIES);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIntegrations();
  }, [fetchIntegrations]);

  const handleToggle = async (appId: string, currentStatus: boolean) => {
    const nextStatus = !currentStatus;
    // Optimistic update
    setCategories((prev) =>
      prev.map((cat) => ({
        ...cat,
        apps: cat.apps.map((a) => (a.id === appId ? { ...a, enabled: nextStatus } : a)),
      }))
    );
    try {
      const res = await fetch(`/v1/integrations/${appId}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: nextStatus }),
      });
      if (res.ok) {
        toast.success(`${nextStatus ? 'Enabled' : 'Disabled'} integration.`);
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (err) {
      // Roll back the optimistic update on failure
      setCategories((prev) =>
        prev.map((cat) => ({
          ...cat,
          apps: cat.apps.map((a) => (a.id === appId ? { ...a, enabled: currentStatus } : a)),
        }))
      );
      toast.error('Failed to update integration state.');
    }
  };

  const handleQuickAction = async (appId: string) => {
    setActionLoading(appId);
    try {
      let params: Record<string, unknown> = {};
      if (appId === 'cisco_packet_tracer') {
        params = { project_name: 'Enterprise_Network_Demo' };
      } else if (appId === 'docx_generator' || appId === 'document_generator') {
        params = {
          doc_type: 'docx',
          title: 'Project Proposal',
          filename: 'Project_Proposal.docx',
          sections_or_slides: [{ heading: 'Overview', body: 'Generated via NOVA AI Integrations Hub.' }],
        };
      }

      const res = await fetch('/v1/integrations/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: appId, action: 'execute', params }),
      });
      if (res.ok) {
        const data = await res.json();
        toast.success(`Action completed: ${data.content || data.message || 'Success!'}`);
      } else {
        toast.info(`Task dispatched for ${appId}. Check console or agent session.`);
      }
    } catch (e) {
      toast.info(`Dispatched task for ${appId}.`);
    } finally {
      setActionLoading(null);
    }
  };

  const filteredBySearch = useMemo(() => {
    if (!debouncedQuery) return categories;
    return categories
      .map((cat) => ({
        ...cat,
        apps: cat.apps.filter(
          (app) =>
            app.name.toLowerCase().includes(debouncedQuery) ||
            app.description.toLowerCase().includes(debouncedQuery) ||
            app.id.toLowerCase().includes(debouncedQuery)
        ),
      }))
      .filter((cat) => cat.apps.length > 0);
  }, [categories, debouncedQuery]);

  const categoryList = useMemo(
    () => ['All', ...filteredBySearch.map((c) => c.category)],
    [filteredBySearch]
  );

  const displayedCategories =
    selectedCategory === 'All'
      ? filteredBySearch
      : filteredBySearch.filter((c) => c.category.toLowerCase().includes(selectedCategory.toLowerCase()));

  return (
    <div className="flex-1 h-full overflow-y-auto p-6 md:p-10" style={{ background: 'var(--color-bg-primary)' }}>
      {/* Header */}
      <div className="max-w-6xl mx-auto mb-8">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-[var(--color-border)]">
          <div>
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-600 to-cyan-500 flex items-center justify-center text-white shadow-lg">
                <Layers size={22} />
              </div>
              <div>
                <h1 className="text-2xl md:text-3xl font-extrabold text-[var(--color-text-primary)]">
                  App & Software Integrations
                </h1>
                <p className="text-sm text-[var(--color-text-secondary)] mt-0.5">
                  Connect external applications, coding CLIs (Claude Code, Gemini CLI, OpenCode), and document tools.
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20">
              <Sparkles size={14} /> Agentic Multi-App Hub
            </span>
          </div>
        </div>

        {/* Search */}
        <div className="relative mt-4 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-secondary)]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search integrations..."
            aria-label="Search integrations"
            className="w-full pl-9 pr-4 py-2.5 rounded-xl text-sm bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-secondary)] focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30"
          />
        </div>

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            className="mt-4 flex items-center gap-3 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-sm text-red-400"
          >
            <AlertCircle size={18} className="shrink-0" />
            <span className="flex-1">{error}</span>
            <button
              onClick={fetchIntegrations}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 transition-all cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {/* Category Filter Pills */}
        {!loading && (
          <div className="flex items-center gap-2 overflow-x-auto py-4 scrollbar-none">
            {categoryList.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                aria-pressed={selectedCategory === cat}
                className={`px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
                  selectedCategory === cat
                    ? 'bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow-md shadow-purple-500/20'
                    : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-tertiary)] border border-[var(--color-border)]'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Loading skeleton */}
      {loading ? (
        <div className="max-w-6xl mx-auto space-y-8" data-testid="integrations-skeleton">
          {[0, 1].map((section) => (
            <div key={section} className="space-y-4">
              <div className="h-5 w-48 rounded-lg animate-pulse bg-[var(--color-bg-tertiary)]" />
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {[0, 1, 2].map((card) => (
                  <div
                    key={card}
                    className="rounded-2xl p-5 border border-[var(--color-border)] bg-[var(--color-bg-secondary)] animate-pulse"
                  >
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-10 h-10 rounded-xl bg-[var(--color-bg-tertiary)]" />
                      <div className="space-y-2 flex-1">
                        <div className="h-3.5 w-32 rounded bg-[var(--color-bg-tertiary)]" />
                        <div className="h-2.5 w-20 rounded bg-[var(--color-bg-tertiary)]" />
                      </div>
                    </div>
                    <div className="space-y-2 mb-4">
                      <div className="h-2.5 w-full rounded bg-[var(--color-bg-tertiary)]" />
                      <div className="h-2.5 w-4/5 rounded bg-[var(--color-bg-tertiary)]" />
                    </div>
                    <div className="h-8 w-full rounded-lg bg-[var(--color-bg-tertiary)]" />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : displayedCategories.length === 0 ? (
        <div className="max-w-6xl mx-auto text-center py-16">
          <Search size={40} className="mx-auto text-[var(--color-text-secondary)] mb-4 opacity-50" />
          <h3 className="text-lg font-semibold text-[var(--color-text-primary)] mb-1">No integrations found</h3>
          <p className="text-sm text-[var(--color-text-secondary)]">
            Try a different search term or clear the filter.
          </p>
        </div>
      ) : (
        /* Grid of Apps by Category */
        <div className="max-w-6xl mx-auto space-y-10">
          {displayedCategories.map((group) => (
            <div key={group.category} className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-[var(--color-text-primary)] flex items-center gap-2">
                  {group.category.includes('Messaging') && <MessageSquare size={18} className="text-cyan-400" />}
                  {group.category.includes('Developer') && <Terminal size={18} className="text-purple-400" />}
                  {group.category.includes('Document') && <FileText size={18} className="text-emerald-400" />}
                  {group.category.includes('Notes') && <Share2 size={18} className="text-amber-400" />}
                  {group.category}
                </h2>
                <span className="text-xs text-[var(--color-text-secondary)]">{group.apps.length} integrations</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {group.apps.map((app) => (
                  <div
                    key={app.id}
                    className="rounded-2xl p-5 border border-[var(--color-border)] bg-[var(--color-bg-secondary)] hover:border-purple-500/40 transition-all flex flex-col justify-between shadow-sm"
                  >
                    <div>
                      <div className="flex items-start justify-between gap-3 mb-3">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-xl bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] flex items-center justify-center text-[var(--color-text-primary)] font-bold text-sm">
                            {app.id.includes('cisco') ? (
                              <Network size={20} className="text-cyan-400" />
                            ) : app.id.includes('docx') || app.id.includes('pdf') ? (
                              <FileText size={20} className="text-emerald-400" />
                            ) : app.id.includes('pptx') ? (
                              <Presentation size={20} className="text-orange-400" />
                            ) : app.id.includes('claude') || app.id.includes('gemini') || app.id.includes('opencode') ? (
                              <Terminal size={20} className="text-purple-400" />
                            ) : (
                              <Globe size={20} className="text-indigo-400" />
                            )}
                          </div>
                          <div>
                            <h3 className="font-bold text-sm text-[var(--color-text-primary)]">{app.name}</h3>
                            <span className="text-[11px] font-mono text-purple-400">{app.id}</span>
                          </div>
                        </div>

                        {/* Toggle Switch */}
                        <button
                          onClick={() => handleToggle(app.id, app.enabled)}
                          role="switch"
                          aria-checked={app.enabled}
                          aria-label={`${app.enabled ? 'Disable' : 'Enable'} ${app.name} integration`}
                          disabled={actionLoading === app.id}
                          className={`w-11 h-6 rounded-full transition-colors relative p-0.5 cursor-pointer ${
                            app.enabled ? 'bg-purple-600' : 'bg-gray-700'
                          }`}
                          title={app.enabled ? 'Click to Disable' : 'Click to Enable'}
                        >
                          <div
                            className={`w-5 h-5 rounded-full bg-white transition-transform ${
                              app.enabled ? 'translate-x-5' : 'translate-x-0'
                            }`}
                          />
                        </button>
                      </div>

                      <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed mb-4">
                        {app.description}
                      </p>
                    </div>

                    <div className="flex items-center justify-between pt-3 border-t border-[var(--color-border)] mt-2">
                      <span
                        className={`text-[11px] font-semibold flex items-center gap-1 ${
                          app.enabled ? 'text-green-400' : 'text-gray-400'
                        }`}
                      >
                        {app.enabled ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}
                        {app.enabled ? 'Connected' : app.status}
                      </span>

                      <button
                        onClick={() => handleQuickAction(app.id)}
                        disabled={actionLoading === app.id}
                        aria-label={`Run task for ${app.name}`}
                        className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/20 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                      >
                        <Play size={12} />
                        {actionLoading === app.id ? 'Running...' : 'Run Task'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default IntegrationsPage;
