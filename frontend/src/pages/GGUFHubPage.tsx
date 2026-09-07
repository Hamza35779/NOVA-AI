import React, { useEffect, useState, useRef } from "react";
import {
  Download,
  CheckCircle2,
  Trash2,
  Cpu,
  HardDrive,
  Zap,
  Brain,
  Code2,
  Star,
  Search,
  RefreshCw,
  FolderOpen,
  AlertCircle,
  Loader2,
} from "lucide-react";

interface GGUFModel {
  id: string;
  name: string;
  category: string;
  params: string;
  size_gb: number;
  min_ram_gb: number;
  description: string;
  recommended: boolean;
  installed: boolean;
  local_path: string | null;
  size_bytes: number;
  requires_ollama: boolean;
}

interface DownloadProgress {
  model_id: string;
  status: string;
  percent: number;
  downloaded_bytes: number;
  total_bytes: number;
  done: boolean;
  error: string | null;
  local_path: string | null;
}

const CATEGORY_ICONS: Record<string, React.ReactElement> = {
  fast: <Zap className="w-4 h-4" />,
  general: <Star className="w-4 h-4" />,
  coding: <Code2 className="w-4 h-4" />,
  reasoning: <Brain className="w-4 h-4" />,
};

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const gb = bytes / 1_073_741_824;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  const mb = bytes / 1_048_576;
  return `${mb.toFixed(0)} MB`;
}

export default function GGUFHubPage() {
  const [catalog, setCatalog] = useState<GGUFModel[]>([]);
  const [activeCategory, setActiveCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [modelsDir, setModelsDir] = useState("");
  const [totalInstalled, setTotalInstalled] = useState(0);
  const [downloads, setDownloads] = useState<Record<string, DownloadProgress>>({});
  const sseRefs = useRef<Record<string, EventSource>>({});

  const fetchCatalog = async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/models/gguf/catalog");
      const data = await res.json();
      setCatalog(data.catalog ?? []);
      setModelsDir(data.models_dir ?? "");
      setTotalInstalled(data.total_installed ?? 0);
    } catch (err) {
      console.error("Failed to load GGUF catalog:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCatalog();
    return () => {
      // Clean up SSE connections on unmount
      Object.values(sseRefs.current).forEach((es) => es.close());
    };
  }, []);

  const startDownload = async (model: GGUFModel) => {
    const res = await fetch("/api/models/gguf/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: model.id }),
    });
    const data = await res.json();

    if (data.status === "already_installed") {
      fetchCatalog();
      return;
    }

    const taskId: string = data.task_id;
    setDownloads((prev) => ({
      ...prev,
      [model.id]: {
        model_id: model.id,
        status: "starting",
        percent: 0,
        downloaded_bytes: 0,
        total_bytes: 0,
        done: false,
        error: null,
        local_path: null,
      },
    }));

    // Open SSE stream for progress
    const es = new EventSource(`/api/models/gguf/download/${taskId}/progress`);
    sseRefs.current[model.id] = es;

    es.onmessage = (event) => {
      try {
        const info: DownloadProgress = JSON.parse(event.data);
        setDownloads((prev) => ({ ...prev, [model.id]: info }));
        if (info.done || info.error) {
          es.close();
          delete sseRefs.current[model.id];
          if (info.done && !info.error) {
            fetchCatalog();
          }
        }
      } catch {
        /* ignore parse errors */
      }
    };

    es.onerror = () => {
      es.close();
      delete sseRefs.current[model.id];
    };
  };

  const deleteModel = async (model: GGUFModel) => {
    if (!confirm(`Delete ${model.name}? This will free up disk space.`)) return;
    await fetch(`/api/models/gguf/model/${model.id}`, { method: "DELETE" });
    fetchCatalog();
  };

  const filtered = catalog.filter((m) => {
    const matchCat = activeCategory === "all" || m.category === activeCategory;
    const matchSearch =
      !search ||
      m.name.toLowerCase().includes(search.toLowerCase()) ||
      m.description.toLowerCase().includes(search.toLowerCase());
    return matchCat && matchSearch;
  });

  const categories = [
    { key: "all", label: "All Models" },
    { key: "fast", label: "Fast & Light" },
    { key: "general", label: "General" },
    { key: "coding", label: "Coding" },
    { key: "reasoning", label: "Reasoning" },
  ];

  return (
    <div className="flex flex-col h-full overflow-y-auto" style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}>
      {/* Header */}
      <div
        className="sticky top-0 z-10 backdrop-blur px-6 py-4"
        style={{ background: 'color-mix(in srgb, var(--color-bg) 92%, transparent)', borderBottom: '1px solid var(--color-border-subtle)' }}
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-xl font-semibold flex items-center gap-2">
              <HardDrive className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />
              GGUF Model Hub
            </h1>
            <p className="text-sm mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
              Download and run models locally — no Ollama or external server required
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4" style={{ color: 'var(--color-success)' }} />
              {totalInstalled} installed
            </span>
            <button
              onClick={fetchCatalog}
              className="p-1.5 rounded transition-colors cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Storage path */}
        {modelsDir && (
          <div className="flex items-center gap-2 text-xs mb-3 rounded px-3 py-1.5" style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-secondary)' }}>
            <FolderOpen className="w-3.5 h-3.5 shrink-0" />
            <span className="font-mono truncate">{modelsDir}</span>
          </div>
        )}

        {/* Search + Filter bar */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
            <input
              type="text"
              placeholder="Search models..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg pl-9 pr-4 py-2 text-sm focus:outline-none"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>
          <div className="flex gap-1.5">
            {categories.map((cat) => (
              <button
                key={cat.key}
                onClick={() => setActiveCategory(cat.key)}
                className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer"
                style={
                  activeCategory === cat.key
                    ? { background: 'var(--color-accent)', color: 'var(--color-on-accent)' }
                    : { background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border-subtle)' }
                }
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* How it works banner */}
      <div className="mx-6 mt-4 rounded-xl px-4 py-3 flex items-start gap-3" style={{ background: 'var(--color-accent-subtle)', border: '1px solid var(--color-accent)' }}>
        <Cpu className="w-5 h-5 mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
        <div className="text-sm">
          <span className="font-medium" style={{ color: 'var(--color-accent)' }}>100% Local & Offline.</span>
          <span className="ml-1.5" style={{ color: 'var(--color-text-secondary)' }}>
            Models download directly from Hugging Face and run entirely in-process on your CPU or GPU.
            No Ollama, no Docker, no external service needed.
          </span>
        </div>
      </div>

      {/* Model grid */}
      <div className="p-6">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="w-6 h-6 animate-spin" style={{ color: 'var(--color-text-tertiary)' }} />
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-24" style={{ color: 'var(--color-text-tertiary)' }}>
            <Search className="w-8 h-8 mx-auto mb-3 opacity-40" />
            <p>No models match your search.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map((model) => {
              const dl = downloads[model.id];
              const isDownloading = dl && !dl.done;
              const hasFailed = dl?.error;

              return (
                <div
                  key={model.id}
                  className="relative rounded-xl p-4 flex flex-col gap-3 transition-all hover:-translate-y-0.5"
                  style={{
                    ...(model.installed
                      ? { background: 'color-mix(in srgb, var(--color-success) 5%, transparent)', border: '1px solid color-mix(in srgb, var(--color-success) 25%, transparent)' }
                      : { background: 'var(--color-surface)', border: '1px solid var(--color-border)' }),
                    boxShadow: 'var(--shadow-sm)',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.boxShadow = 'var(--shadow-md)')}
                  onMouseLeave={(e) => (e.currentTarget.style.boxShadow = 'var(--shadow-sm)')}
                >
                  {/* Recommended badge */}
                  {model.recommended && (
                    <span
                      className="absolute top-3 right-3 text-[10px] font-semibold rounded-full px-2 py-0.5"
                      style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)', border: '1px solid var(--color-accent)' }}
                    >
                      RECOMMENDED
                    </span>
                  )}

                  {/* Name & category */}
                  <div className="pr-20">
                    <div className="font-medium text-sm leading-snug">{model.name}</div>
                    <div className="mt-1">
                      <span
                        className="inline-flex items-center gap-1 text-[10px] font-medium rounded-full px-2 py-0.5"
                        style={{
                          background: 'var(--color-bg-secondary)',
                          color: 'var(--color-text-secondary)',
                          border: '1px solid var(--color-border)',
                        }}
                      >
                        {CATEGORY_ICONS[model.category]}
                        {model.category}
                      </span>
                    </div>
                  </div>

                  {/* Description */}
                  <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{model.description}</p>

                  {/* Stats */}
                  <div className="flex items-center gap-3 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                    <span className="flex items-center gap-1">
                      <Cpu className="w-3 h-3" />
                      {model.params}
                    </span>
                    <span className="flex items-center gap-1">
                      <HardDrive className="w-3 h-3" />
                      {model.size_gb} GB
                    </span>
                    <span className="flex items-center gap-1">
                      <Zap className="w-3 h-3" />
                      {model.min_ram_gb} GB RAM
                    </span>
                  </div>

                  {/* Download progress */}
                  {isDownloading && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="capitalize" style={{ color: 'var(--color-text-secondary)' }}>{dl.status}</span>
                        <span className="font-mono" style={{ color: 'var(--color-text)' }}>
                          {dl.total_bytes > 0
                            ? `${formatBytes(dl.downloaded_bytes)} / ${formatBytes(dl.total_bytes)}`
                            : `${dl.percent}%`}
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-tertiary)' }}>
                        <div
                          className="h-full rounded-full transition-all duration-300"
                          style={{ width: `${dl.percent}%`, background: 'var(--color-accent)' }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Error state */}
                  {hasFailed && (
                    <div className="flex items-start gap-2 text-xs rounded-lg px-3 py-2" style={{ color: 'var(--color-error)', background: 'color-mix(in srgb, var(--color-error) 10%, transparent)' }}>
                      <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      <span>{dl.error}</span>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex gap-2 mt-auto">
                    {model.installed ? (
                      <>
                        <div className="flex-1 flex items-center gap-1.5 text-xs font-medium rounded-lg px-3 py-2" style={{ color: 'var(--color-success)', background: 'color-mix(in srgb, var(--color-success) 10%, transparent)' }}>
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Installed
                        </div>
                        <button
                          onClick={() => deleteModel(model)}
                          className="p-2 rounded-lg transition-colors cursor-pointer"
                          style={{ color: 'var(--color-error)', background: 'color-mix(in srgb, var(--color-error) 10%, transparent)' }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = 'color-mix(in srgb, var(--color-error) 20%, transparent)')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = 'color-mix(in srgb, var(--color-error) 10%, transparent)')}
                          title="Delete model"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </>
                    ) : isDownloading ? (
                      <div className="flex-1 flex items-center justify-center gap-1.5 text-xs rounded-lg px-3 py-2" style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-secondary)' }}>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Downloading...
                      </div>
                    ) : (
                      <button
                        onClick={() => startDownload(model)}
                        className="flex-1 flex items-center justify-center gap-1.5 text-xs font-medium rounded-lg px-3 py-2 transition-colors cursor-pointer"
                        style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-hover)')}
                        onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-accent)')}
                      >
                        <Download className="w-3.5 h-3.5" />
                        Download & Install
                      </button>
                    )}
                  </div>

                  {/* Installed size */}
                  {model.installed && model.size_bytes > 0 && (
                    <p className="text-[10px] -mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                      {formatBytes(model.size_bytes)} on disk
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
