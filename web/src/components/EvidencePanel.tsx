"use client";

import { useState } from "react";
import type { EvidenceChunk } from "@/lib/api";

interface EvidencePanelProps {
  chunks: EvidenceChunk[];
}

function ChunkCard({ chunk }: { chunk: EvidenceChunk }) {
  const [expanded, setExpanded] = useState(false);
  const truncateAt = 240;
  const needsTruncation = chunk.content.length > truncateAt;
  const displayContent = expanded
    ? chunk.content
    : chunk.content.slice(0, truncateAt);

  return (
    <div className="rounded-md bg-white/[0.03] p-3 ring-1 ring-inset ring-white/[0.06] transition-colors duration-200 hover:bg-white/[0.05]">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {chunk.domain_key && (
          <span className="rounded bg-sky-500/10 px-1.5 py-0.5 font-mono text-[11px] text-sky-300 ring-1 ring-inset ring-sky-500/20">
            {chunk.domain_key}
          </span>
        )}
        <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[11px] font-medium text-violet-300 ring-1 ring-inset ring-violet-500/20">
          {chunk.kind}
        </span>
        <span className="ml-auto font-mono text-[11px] text-white/30">
          score: {chunk.score.toFixed(3)}
        </span>
      </div>

      <p className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-white/60">
        {displayContent}
        {needsTruncation && !expanded && (
          <span className="text-white/30">&hellip;</span>
        )}
      </p>

      {needsTruncation && (
        <button
          onClick={() => setExpanded((prev) => !prev)}
          className="mt-2 text-[11px] font-medium text-sky-400/70 transition-colors hover:text-sky-300"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

export default function EvidencePanel({ chunks }: EvidencePanelProps) {
  const [open, setOpen] = useState(false);

  if (chunks.length === 0) return null;

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="group flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-white/35 transition-colors hover:text-white/60"
      >
        <svg
          className={`h-3 w-3 transition-transform duration-200 ${open ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        Evidence ({chunks.length} chunks)
      </button>

      <div
        className={`grid transition-all duration-300 ease-out ${
          open ? "mt-3 grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        }`}
      >
        <div className="overflow-hidden">
          <div className="flex flex-col gap-2">
            {chunks.map((chunk, i) => (
              <ChunkCard key={`${chunk.domain_key}-${i}`} chunk={chunk} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
