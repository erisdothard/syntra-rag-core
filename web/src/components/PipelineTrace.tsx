"use client";

import type { PipelineStage } from "@/lib/api";

interface PipelineTraceProps {
  stages: PipelineStage[];
}

function stageColor(ms: number): string {
  if (ms < 500) return "bg-emerald-400";
  if (ms < 2000) return "bg-amber-400";
  return "bg-red-400";
}

function dotColor(ms: number): string {
  if (ms < 500) return "bg-emerald-400 shadow-emerald-400/50";
  if (ms < 2000) return "bg-amber-400 shadow-amber-400/50";
  return "bg-red-400 shadow-red-400/50";
}

export default function PipelineTrace({ stages }: PipelineTraceProps) {
  if (stages.length === 0) return null;

  const totalMs = stages.reduce((sum, s) => sum + s.duration_ms, 0);

  return (
    <div className="mt-4 rounded-lg bg-white/[0.03] p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-white/40">
          Pipeline
        </span>
        <span className="font-mono text-[11px] text-white/30">
          {totalMs.toLocaleString()}ms total
        </span>
      </div>

      {/* The track */}
      <div className="relative flex h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
        {stages.map((stage, i) => {
          const widthPct = totalMs > 0 ? (stage.duration_ms / totalMs) * 100 : 0;
          return (
            <div
              key={`${stage.name}-${i}`}
              className={`h-full transition-all duration-500 ${stageColor(stage.duration_ms)} ${i === 0 ? "rounded-l-full" : ""} ${i === stages.length - 1 ? "rounded-r-full" : ""}`}
              style={{ width: `${widthPct}%` }}
            />
          );
        })}
      </div>

      {/* Stage labels */}
      <div className="mt-3 flex items-start justify-between gap-1">
        {stages.map((stage, i) => (
          <div key={`${stage.name}-${i}`} className="flex flex-col items-center gap-1.5">
            <div
              className={`h-2 w-2 rounded-full shadow-sm ${dotColor(stage.duration_ms)}`}
            />
            <span className="text-[10px] font-medium text-white/50">
              {stage.name}
            </span>
            <span className="font-mono text-[10px] text-white/30">
              {stage.duration_ms}ms
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
