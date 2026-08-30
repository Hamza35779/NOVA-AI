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

const CATEGORY_COLORS: Record<string, string> = {
  fast: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  general: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  coding: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  reasoning: "bg-green-500/10 text-green-400 border-green-500/20",
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
    <div className="flex flex-col h-full bg-[#0a0a0f] text-white overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-[#0a0a0f]/95 backdrop-blur border-b border-white/5 px-6 py-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-xl font-semibold flex items-center gap-2">
              <HardDrive className="w-5 h-5 text-indigo-400" />
              GGUF Model Hub
            </h1>
            <p className="text-sm text-white/40 mt-0.5">
              Download and run models locally — no Ollama or external server required
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm text-white/40">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4 text-green-400" />
              {totalInstalled} installed
            </span>
            <button
              onClick={fetchCatalog}
              className="p-1.5 rounded hover:bg-white/5 transition-colors"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Storage path */}
        {modelsDir && (
          <div className="flex items-center gap-2 text-xs text-white/30 mb-3 bg-white/3 rounded px-3 py-1.5">
            <FolderOpen className="w-3.5 h-3.5 shrink-0" />
            <span className="font-mono truncate">{modelsDir}</span>
          </div>
        )}

        {/* Search + Filter bar */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
            <input
              type="text"
              placeholder="Search models..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg pl-9 pr-4 py-2 text-sm focus:outline-none focus:border-indigo-500/50 placeholder:text-white/30"
            />
          </div>
          <div className="flex gap-1.5">
            {categories.map((cat) => (
              <button
                key={cat.key}
                onClick={() => setActiveCategory(cat.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  activeCategory === cat.key
                    ? "bg-indigo-600 text-white"
                    : "bg-white/5 text-white/50 hover:bg-white/8 hover:text-white/80"
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* How it works banner */}
      <div className="mx-6 mt-4 rounded-xl bg-indigo-600/10 border border-indigo-500/20 px-4 py-3 flex items-start gap-3">
        <Cpu className="w-5 h-5 text-indigo-400 mt-0.5 shrink-0" />
        <div className="text-sm">
          <span className="text-indigo-300 font-medium">100% Local & Offline.</span>
          <span className="text-white/50 ml-1.5">
            Models download directly from Hugging Face and run entirely in-process on your CPU or GPU.
            No Ollama, no Docker, no external service needed.
          </span>
        </div>
      </div>

      {/* Model grid */}
      <div className="p-6">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="w-6 h-6 text-white/30 animate-spin" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-24 text-white/30">
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
                  className={`relative rounded-xl border p-4 flex flex-col gap-3 transition-all ${
                    model.installed
                      ? "bg-green-500/5 border-green-500/20"
                      : "bg-white/2 border-white/8 hover:border-white/15"
                  }`}
                >
                  {/* Recommended badge */}
                  {model.recommended && (
                    <span className="absolute top-3 right-3 text-[10px] font-semibold bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 rounded-full px-2 py-0.5">
                      RECOMMENDED
                    </span>
                  )}

                  {/* Name & category */}
                  <div className="pr-20">
                    <div className="font-medium text-sm leading-snug">{model.name}</div>
                    <div className="mt-1">
                      <span
                        className={`inline-flex items-center gap-1 text-[10px] font-medium border rounded-full px-2 py-0.5 ${
                          CATEGORY_COLORS[model.category] ?? "bg-white/5 text-white/50 border-white/10"
                        }`}
                      >
                        {CATEGORY_ICONS[model.category]}
                        {model.category}
                      </span>
                    </div>
                  </div>

                  {/* Description */}
                  <p className="text-xs text-white/40 leading-relaxed">{model.description}</p>

                  {/* Stats */}
                  <div className="flex items-center gap-3 text-[11px] text-white/35">
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
                        <span className="text-white/50 capitalize">{dl.status}</span>
                        <span className="text-white/60 font-mono">
                          {dl.total_bytes > 0
                            ? `${formatBytes(dl.downloaded_bytes)} / ${formatBytes(dl.total_bytes)}`
                            : `${dl.percent}%`}
                        </span>
                      </div>
                      <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-indigo-500 rounded-full transition-all duration-300"
                          style={{ width: `${dl.percent}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Error state */}
                  {hasFailed && (
                    <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 rounded-lg px-3 py-2">
                      <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      <span>{dl.error}</span>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex gap-2 mt-auto">
                    {model.installed ? (
                      <>
                        <div className="flex-1 flex items-center gap-1.5 text-xs text-green-400 font-medium bg-green-500/10 rounded-lg px-3 py-2">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Installed
                        </div>
                        <button
                          onClick={() => deleteModel(model)}
                          className="p-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                          title="Delete model"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </>
                    ) : isDownloading ? (
                      <div className="flex-1 flex items-center justify-center gap-1.5 text-xs text-white/50 bg-white/5 rounded-lg px-3 py-2">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Downloading...
                      </div>
                    ) : (
                      <button
                        onClick={() => startDownload(model)}
                        className="flex-1 flex items-center justify-center gap-1.5 text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg px-3 py-2 transition-colors"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Download & Install
                      </button>
                    )}
                  </div>

                  {/* Installed size */}
                  {model.installed && model.size_bytes > 0 && (
                    <p className="text-[10px] text-white/25 -mt-1">
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
