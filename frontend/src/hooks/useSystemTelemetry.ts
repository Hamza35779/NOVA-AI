import { useEffect, useState } from 'react';
import { apiFetch, getBase } from '../lib/api';

export interface GpuTelemetry {
  index: number;
  util_percent: number;
  mem_used_gb: number;
  mem_total_gb: number;
  temperature_c: number;
}

export interface SystemTelemetry {
  cpu: { percent: number; cores: number };
  ram: {
    percent: number;
    used_gb: number;
    total_gb: number;
    free_gb: number;
  };
  gpu: {
    vendor: string;
    name: string;
    available: boolean;
    gpus: GpuTelemetry[];
    vram_free_gb: number;
    vram_total_gb: number;
  };
  timestamp: number;
}

/**
 * Poll the local server's live hardware telemetry (`/api/system/telemetry`).
 * Falls back gracefully when the backend or sensors are unavailable.
 */
export function useSystemTelemetry(intervalMs = 2000): {
  telemetry: SystemTelemetry | null;
  error: string | null;
} {
  const [telemetry, setTelemetry] = useState<SystemTelemetry | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getBase()) {
      setError('backend-unavailable');
      return;
    }
    let cancelled = false;

    const poll = async () => {
      try {
        const res = await apiFetch('/api/system/telemetry');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as SystemTelemetry;
        if (!cancelled) {
          setTelemetry(data);
          setError(null);
        }
      } catch {
        if (!cancelled) setError('backend-unavailable');
      }
    };

    poll();
    const timer = setInterval(poll, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [intervalMs]);

  return { telemetry, error };
}
