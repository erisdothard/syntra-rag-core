"use client";

interface JudgeBadgeProps {
  label: string;
  score: number;
}

function scoreColor(score: number): string {
  if (score >= 4) return "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30";
  if (score >= 3) return "bg-amber-500/15 text-amber-300 ring-amber-500/30";
  return "bg-red-500/15 text-red-300 ring-red-500/30";
}

export default function JudgeBadge({ label, score }: JudgeBadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center gap-1 rounded-full px-2.5 py-0.5
        text-xs font-semibold tracking-wide ring-1 ring-inset
        transition-colors duration-200
        ${scoreColor(score)}
      `}
    >
      {label}: {score}/5
    </span>
  );
}
