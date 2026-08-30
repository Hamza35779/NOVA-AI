import { useEffect, useRef, useState } from 'react';
import { Play, X, RefreshCw, CheckCircle2, AlertCircle, Clock, Loader2 } from 'lucide-react';

interface SubTask {
  id: string;
  title: string;
  description?: string;
  tool_name?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'blocked' | 'skipped';
  depends_on: string[];
  duration_ms: number;
  retries: number;
  error?: string;
}

interface TaskPlan {
  plan_id: string;
  goal: string;
  status: string;
  progress: number;
  tasks: SubTask[];
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#475569',
  running: '#7C3AED',
  completed: '#10B981',
  failed: '#EF4444',
  blocked: '#F59E0B',
  skipped: '#6B7280',
};

const STATUS_ICONS: Record<string, JSX.Element> = {
  pending: <Clock size={12} />,
  running: <Loader2 size={12} className="animate-spin" />,
  completed: <CheckCircle2 size={12} />,
  failed: <AlertCircle size={12} />,
  blocked: <AlertCircle size={12} />,
  skipped: <X size={12} />,
};

function TaskNode({ task }: { task: SubTask }) {
  const color = STATUS_COLORS[task.status] ?? '#475569';
  const isRunning = task.status === 'running';

  return (
    <div
      className="flex flex-col gap-1 px-3 py-2 rounded-xl border text-xs min-w-[160px] max-w-[220px] transition-all"
      style={{
        background: `${color}18`,
        borderColor: color,
        boxShadow: isRunning ? `0 0 10px ${color}55` : 'none',
        animation: isRunning ? 'pulse 1.8s ease-in-out infinite' : 'none',
      }}
    >
      <div className="flex items-center gap-1.5" style={{ color }}>
        {STATUS_ICONS[task.status]}
        <span className="font-semibold truncate">{task.title}</span>
      </div>
      {task.tool_name && (
        <span className="text-xs" style={{ color: '#94A3B8' }}>
          Tool: {task.tool_name}
        </span>
      )}
      {task.duration_ms > 0 && (
        <span style={{ color: '#64748B' }}>{task.duration_ms.toFixed(0)}ms</span>
      )}
      {task.retries > 0 && (
        <span style={{ color: '#F59E0B' }}>↺ {task.retries} retr{task.retries === 1 ? 'y' : 'ies'}</span>
      )}
      {task.error && (
        <span className="truncate" style={{ color: '#EF4444' }} title={task.error}>
          {task.error.slice(0, 40)}
        </span>
      )}
    </div>
  );
}

function Arrow() {
  return (
    <svg width="28" height="16" viewBox="0 0 28 16" className="shrink-0 self-center">
      <line x1="0" y1="8" x2="22" y2="8" stroke="#475569" strokeWidth="1.5" />
      <polygon points="22,4 28,8 22,12" fill="#475569" />
    </svg>
  );
}

export function TaskPlannerPanel() {
  const [plans, setPlans] = useState<TaskPlan[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const fetchPlans = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/tasks');
      if (res.ok) {
        const data = await res.json();
        setPlans(data.plans ?? []);
      }
    } catch {
      // Server not running — show empty state
    } finally {
      setLoading(false);
    }
  };

  const fetchPlanDetail = async (planId: string) => {
    try {
      const res = await fetch(`/api/tasks/${planId}`);
      if (res.ok) {
        const data = await res.json();
        setPlans((prev) =>
          prev.map((p) => (p.plan_id === planId ? { ...p, ...data } : p))
        );
      }
    } catch {}
  };

  const subscribeToSSE = (planId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    const es = new EventSource(`/api/tasks/${planId}/stream`);
    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        if (event.type === 'snapshot') {
          setPlans((prev) =>
            prev.map((p) => (p.plan_id === planId ? { ...p, ...event } : p))
          );
        } else if (event.type === 'task_update') {
          setPlans((prev) =>
            prev.map((p) =>
              p.plan_id === planId
                ? {
                    ...p,
                    tasks: p.tasks?.map((t) =>
                      t.id === event.task_id ? { ...t, ...event } : t
                    ) ?? [],
                  }
                : p
            )
          );
        } else if (event.type === 'plan_complete') {
          fetchPlanDetail(planId);
          es.close();
        }
      } catch {}
    };
    es.onerror = () => es.close();
    eventSourceRef.current = es;
  };

  useEffect(() => {
    fetchPlans();
    return () => eventSourceRef.current?.close();
  }, []);

  const handleSelectPlan = (planId: string) => {
    setSelectedPlanId(planId);
    subscribeToSSE(planId);
    fetchPlanDetail(planId);
  };

  const handleCancel = async (planId: string) => {
    try {
      await fetch(`/api/tasks/${planId}/cancel`, { method: 'POST' });
      fetchPlanDetail(planId);
    } catch {}
  };

  const selectedPlan = plans.find((p) => p.plan_id === selectedPlanId);

  // Build execution layers for left-to-right DAG rendering
  const buildLayers = (tasks: SubTask[]): SubTask[][] => {
    const layers: SubTask[][] = [];
    const placed = new Set<string>();
    let remaining = [...tasks];
    while (remaining.length > 0) {
      const layer = remaining.filter((t) =>
        t.depends_on.every((dep) => placed.has(dep))
      );
      if (layer.length === 0) break;
      layers.push(layer);
      layer.forEach((t) => placed.add(t.id));
      remaining = remaining.filter((t) => !placed.has(t.id));
    }
    return layers;
  };

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold" style={{ color: '#F1F5F9' }}>
          Task Planner
        </h2>
        <button
          onClick={fetchPlans}
          className="p-1.5 rounded-lg hover:bg-white/10 transition-colors"
          style={{ color: '#94A3B8' }}
          title="Refresh"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Plan list */}
      <div className="flex flex-col gap-2 overflow-y-auto max-h-48">
        {plans.length === 0 && (
          <p className="text-sm" style={{ color: '#475569' }}>
            No active plans. Plans are created automatically when Nova runs multi-step tasks.
          </p>
        )}
        {plans.map((plan) => (
          <button
            key={plan.plan_id}
            onClick={() => handleSelectPlan(plan.plan_id)}
            className={`text-left p-3 rounded-xl border transition-all ${
              selectedPlanId === plan.plan_id ? 'border-purple-500' : 'border-white/10'
            }`}
            style={{ background: '#1E1533' }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium truncate" style={{ color: '#F1F5F9' }}>
                {plan.goal}
              </span>
              <span
                className="text-xs px-2 py-0.5 rounded-full shrink-0"
                style={{
                  background: `${STATUS_COLORS[plan.status] ?? '#475569'}22`,
                  color: STATUS_COLORS[plan.status] ?? '#94A3B8',
                }}
              >
                {plan.status}
              </span>
            </div>
            {/* Progress bar */}
            <div className="mt-2 h-1 rounded-full bg-white/10">
              <div
                className="h-1 rounded-full transition-all"
                style={{
                  width: `${(plan.progress ?? 0) * 100}%`,
                  background: 'linear-gradient(90deg, #7C3AED, #06B6D4)',
                }}
              />
            </div>
          </button>
        ))}
      </div>

      {/* DAG Visualization */}
      {selectedPlan && (
        <div className="flex flex-col gap-3 flex-1 overflow-auto">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold" style={{ color: '#CBD5E1' }}>
              {selectedPlan.goal}
            </h3>
            {selectedPlan.status === 'running' && (
              <button
                onClick={() => handleCancel(selectedPlan.plan_id)}
                className="flex items-center gap-1 text-xs px-3 py-1 rounded-lg transition-colors"
                style={{ background: '#EF444422', color: '#EF4444' }}
              >
                <X size={11} /> Cancel
              </button>
            )}
          </div>

          {/* DAG: render layers left to right */}
          <div
            className="flex items-start gap-2 overflow-x-auto pb-3"
            style={{ minHeight: 120 }}
          >
            {buildLayers(selectedPlan.tasks ?? []).map((layer, layerIdx) => (
              <div key={layerIdx} className="flex flex-col gap-2">
                {layer.map((task, taskIdx) => (
                  <div key={task.id} className="flex items-center gap-2">
                    <TaskNode task={task} />
                    {layerIdx < buildLayers(selectedPlan.tasks ?? []).length - 1 && (
                      <Arrow />
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
