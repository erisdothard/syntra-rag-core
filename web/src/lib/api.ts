const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface EvidenceChunk {
  domain_key: string | null;
  kind: string;
  score: number;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface PipelineStage {
  name: string;
  duration_ms: number;
}

export interface AskMetadata {
  route: "direct" | "decomposed" | "no_evidence";
  faithfulness: number;
  relevance: number;
  pipeline: PipelineStage[];
  evidence: EvidenceChunk[];
}

type SSEEvent =
  | { type: "token"; data: string }
  | { type: "evidence"; data: EvidenceChunk[] }
  | { type: "done"; data: AskMetadata };

function parseSSELine(line: string): SSEEvent | null {
  if (!line.startsWith("data: ")) return null;
  const raw = line.slice(6).trim();
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;

    if (parsed.type === "token" && typeof parsed.text === "string") {
      return { type: "token", data: parsed.text };
    }

    if (parsed.type === "evidence" && Array.isArray(parsed.chunks)) {
      return { type: "evidence", data: parsed.chunks as EvidenceChunk[] };
    }

    if (parsed.type === "done") {
      return { type: "done", data: parsed as unknown as AskMetadata };
    }
  } catch {
    // Plain text token (non-JSON SSE)
    return { type: "token", data: raw };
  }

  return null;
}

export async function askQuestion(
  question: string,
  onToken: (text: string) => void,
  onEvidence: (chunks: EvidenceChunk[]) => void,
  onDone: (metadata: AskMetadata) => void,
): Promise<void> {
  const response = await fetch(`${API_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, stream: true }),
  });

  if (!response.ok) {
    throw new Error(`API responded with ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      const event = parseSSELine(trimmed);
      if (!event) continue;

      switch (event.type) {
        case "token":
          onToken(event.data);
          break;
        case "evidence":
          onEvidence(event.data);
          break;
        case "done":
          onDone(event.data);
          break;
      }
    }
  }

  // Flush remaining buffer
  if (buffer.trim()) {
    const event = parseSSELine(buffer.trim());
    if (event?.type === "done") onDone(event.data);
    else if (event?.type === "token") onToken(event.data);
    else if (event?.type === "evidence") onEvidence(event.data);
  }
}
