import { Cpu, Gauge, MemoryStick, MonitorSmartphone } from 'lucide-react';
import { useSystemTelemetry } from '../../hooks/useSystemTelemetry';

function fmtGb(v: number): string {
  if (v <= 0) return '—';
  return v >= 10 ? `${Math.round(v)} GB` : `${v.toFixed(1)} GB`;
}

function Meter({
  label,
  icon,
  percent,
  detail,
  available = true,
}: {
  label: string;
  icon: React.ReactNode;
  percent: number;
  detail: string;
  available?: boolean;
}) {
  // Deterministic hue: 0% → accent, >85% → warning red
  const pct = Math.max(0, Math.min(100, percent));
  const barColor =
    pct > 85
      ? 'bg-red-500/80'
      : pct > 65
        ? 'bg-amber-500/80'
        : 'bg-[var(--color-accent)]';

  return (
    <div
      className="flex flex-col gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2.5"
      data-available={available}
      aria-label={`${label} ${available ? `${pct}%` : 'unavailable'}`}
    >
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-secondary)]">
          {icon}
          {label}
        </span>
        <span className="font-mono text-[11px] tabular-nums text-[var(--color-text)]">
          {available ? `${Math.round(pct)}%` : '—'}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ease-out ${barColor}`}
          style={{ width: `${available ? pct : 0}%` }}
        />
      </div>
      <span className="truncate text-[10px] text-[var(--color-text-tertiary)]">
        {detail}
      </span>
    </div>
  );
}

/**
 * Live CPU / RAM / VRAM gauges for the dashboard workspace.
 * Polls `/api/system/telemetry`; renders nothing while unreachable.
 */
export function HardwareGauges({ className = '' }: { className?: string }) {
  const { telemetry, error } = useSystemTelemetry(2000);

  if (error || !telemetry) {
    return (
      <div
        className={`flex items-center gap-2 rounded-lg border border-dashed border-[var(--color-border)] px-3 py-2 text-[11px] text-[var(--color-text-tertiary)] ${className}`}
      >
        <Gauge className="h-3.5 w-3.5" />
        Hardware telemetry unavailable
      </div>
    );
  }

  const { cpu, ram, gpu } = telemetry;
  const primaryGpu = gpu.gpus[0];
  const vramPercent = primaryGpu
    ? (primaryGpu.mem_used_gb / Math.max(primaryGpu.mem_total_gb, 0.01)) * 100
    : gpu.vram_total_gb > 0
      ? ((gpu.vram_total_gb - gpu.vram_free_gb) / gpu.vram_total_gb) * 100
      : -1;

  return (
    <div className={`grid grid-cols-2 gap-2 lg:grid-cols-4 ${className}`}>
      <Meter
        label="CPU"
        icon={<Cpu className="h-3.5 w-3.5" />}
        percent={cpu.percent >= 0 ? cpu.percent : 0}
        detail={`${cpu.cores} cores${cpu.percent < 0 ? ' · sensor n/a' : ''}`}
        available={cpu.percent >= 0}
      />
      <Meter
        label="RAM"
        icon={<MemoryStick className="h-3.5 w-3.5" />}
        percent={ram.percent >= 0 ? ram.percent : 0}
        detail={`${fmtGb(ram.used_gb)} / ${fmtGb(ram.total_gb)}`}
        available={ram.percent >= 0}
      />
      <Meter
        label="VRAM"
        icon={<MonitorSmartphone className="h-3.5 w-3.5" />}
        percent={vramPercent >= 0 ? vramPercent : 0}
        detail={
          gpu.available
            ? primaryGpu
              ? `${fmtGb(primaryGpu.mem_used_gb)} / ${fmtGb(primaryGpu.mem_total_gb)}`
              : `${fmtGb(gpu.vram_total_gb - gpu.vram_free_gb)} / ${fmtGb(gpu.vram_total_gb)}`
            : 'No discrete GPU'
        }
        available={vramPercent >= 0}
      />
      <div
        className="flex flex-col justify-center gap-0.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2.5"
        aria-label="GPU device"
      >
        <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-secondary)]">
          <Gauge className="h-3.5 w-3.5" />
          GPU
        </span>
        <span
          className="truncate text-xs font-medium text-[var(--color-text)]"
          title={gpu.name || 'CPU only'}
        >
          {gpu.available ? gpu.name : 'CPU inference'}
        </span>
        {primaryGpu && (
          <span className="font-mono text-[10px] tabular-nums text-[var(--color-text-tertiary)]">
            {primaryGpu.util_percent}% util · {primaryGpu.temperature_c}°C
          </span>
        )}
      </div>
    </div>
  );
}
