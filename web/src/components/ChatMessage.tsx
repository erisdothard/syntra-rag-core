"use client";

import type { AskMetadata, EvidenceChunk } from "@/lib/api";
import JudgeBadge from "./JudgeBadge";
import EvidencePanel from "./EvidencePanel";
import PipelineTrace from "./PipelineTrace";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ChatMessageProps {
  question: string;
  answer: string;
  streaming: boolean;
  metadata: AskMetadata | null;
  evidence: EvidenceChunk[];
}

function routeLabel(route: string): string {
  switch (route) {
    case "direct":
      return "Direct";
    case "decomposed":
      return "Decomposed";
    case "no_evidence":
      return "No evidence";
    default:
      return route;
  }
}

function routeStyle(route: string): string {
  switch (route) {
    case "direct":
      return "bg-emerald-500/10 text-emerald-300 ring-emerald-500/20";
    case "decomposed":
      return "bg-amber-500/10 text-amber-300 ring-amber-500/20";
    case "no_evidence":
      return "bg-red-500/10 text-red-300 ring-red-500/20";
    default:
      return "bg-white/5 text-white/50 ring-white/10";
  }
}

export default function ChatMessage({
  question,
  answer,
  streaming,
  metadata,
  evidence,
}: ChatMessageProps) {
  return (
    <article className="group">
      {/* Question */}
      <div className="mb-4 flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-sky-500/15 px-4 py-3 text-sm leading-relaxed text-sky-100 ring-1 ring-inset ring-sky-500/20">
          {question}
        </div>
      </div>

      {/* Answer */}
      <div className="mb-2">
        <div className="max-w-[90%]">
          <div className="rounded-2xl rounded-bl-sm bg-white/[0.04] px-5 py-4 ring-1 ring-inset ring-white/[0.06]">
            <div className="prose prose-invert prose-sm max-w-none prose-headings:text-white/90 prose-headings:font-semibold prose-p:text-white/75 prose-p:leading-[1.7] prose-strong:text-white/85 prose-code:text-sky-300 prose-code:bg-white/[0.06] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:before:content-none prose-code:after:content-none prose-pre:bg-white/[0.04] prose-pre:ring-1 prose-pre:ring-inset prose-pre:ring-white/[0.08] prose-pre:rounded-lg prose-th:text-white/70 prose-td:text-white/60 prose-hr:border-white/[0.08] prose-a:text-sky-400 prose-li:text-white/70 prose-table:text-xs">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {answer}
              </ReactMarkdown>
              {streaming && (
                <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-sky-400" />
              )}
            </div>

            {/* Metadata bar */}
            {metadata && (
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-3">
                <JudgeBadge label="F" score={metadata.faithfulness} />
                <JudgeBadge label="R" score={metadata.relevance} />
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${routeStyle(metadata.route)}`}
                >
                  {routeLabel(metadata.route)}
                </span>
              </div>
            )}

            {/* Pipeline trace */}
            {metadata?.pipeline && metadata.pipeline.length > 0 && (
              <PipelineTrace stages={metadata.pipeline} />
            )}

            {/* Evidence */}
            <EvidencePanel chunks={evidence} />
          </div>
        </div>
      </div>
    </article>
  );
}
