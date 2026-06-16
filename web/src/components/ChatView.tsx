"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import ChatInput from "@/components/ChatInput";
import ChatMessage from "@/components/ChatMessage";
import { askQuestion } from "@/lib/api";
import type { AskMetadata, EvidenceChunk } from "@/lib/api";

interface Message {
  id: string;
  question: string;
  answer: string;
  streaming: boolean;
  metadata: AskMetadata | null;
  evidence: EvidenceChunk[];
  error: string | null;
}

export default function ChatView() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new content
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const handleSubmit = useCallback(
    async (question: string) => {
      if (loading) return;

      const id = crypto.randomUUID();
      const newMessage: Message = {
        id,
        question,
        answer: "",
        streaming: true,
        metadata: null,
        evidence: [],
        error: null,
      };

      setMessages((prev) => [...prev, newMessage]);
      setLoading(true);

      try {
        await askQuestion(
          question,
          // onToken
          (token) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === id ? { ...m, answer: m.answer + token } : m,
              ),
            );
          },
          // onEvidence
          (chunks) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === id ? { ...m, evidence: chunks } : m,
              ),
            );
          },
          // onDone
          (metadata) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === id
                  ? {
                      ...m,
                      streaming: false,
                      metadata,
                      evidence:
                        metadata.evidence.length > 0
                          ? metadata.evidence
                          : m.evidence,
                    }
                  : m,
              ),
            );
          },
        );
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Connection failed";
        setMessages((prev) =>
          prev.map((m) =>
            m.id === id
              ? {
                  ...m,
                  streaming: false,
                  error: errorMessage,
                  answer: m.answer || "Failed to get a response.",
                }
              : m,
          ),
        );
      } finally {
        setLoading(false);
      }
    },
    [loading],
  );

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header className="shrink-0 border-b border-white/[0.06] px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold tracking-tight text-white/90">
              Syntra RAG
            </h1>
            <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-widest text-sky-400/70 ring-1 ring-inset ring-sky-500/20">
              core
            </span>
          </div>
          <span className="text-[11px] text-white/25">
            {messages.length > 0
              ? `${messages.length} ${messages.length === 1 ? "exchange" : "exchanges"}`
              : "Ready"}
          </span>
        </div>
      </header>

      {/* Messages */}
      <main ref={scrollRef} className="chat-scroll flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-6 py-8">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-32 text-center">
              <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-sky-500/10 ring-1 ring-inset ring-sky-500/20">
                <svg
                  className="h-7 w-7 text-sky-400/70"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z"
                  />
                </svg>
              </div>
              <h2 className="mb-2 text-xl font-semibold tracking-tight text-white/70">
                Ask anything about your corpus
              </h2>
              <p className="max-w-sm text-sm leading-relaxed text-white/30">
                Questions are reshaped, matched against indexed evidence, and
                scored for faithfulness and relevance.
              </p>
            </div>
          )}

          <div className="flex flex-col gap-8">
            {messages.map((msg) => (
              <ChatMessage
                key={msg.id}
                question={msg.question}
                answer={msg.answer}
                streaming={msg.streaming}
                metadata={msg.metadata}
                evidence={msg.evidence}
              />
            ))}
          </div>
        </div>
      </main>

      {/* Input area */}
      <footer className="shrink-0 border-t border-white/[0.06] px-6 py-4">
        <div className="mx-auto max-w-3xl">
          <ChatInput onSubmit={handleSubmit} disabled={loading} />
        </div>
      </footer>
    </div>
  );
}
