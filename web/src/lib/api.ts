const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

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

/**
 * Parse a complete SSE message block (may have `event:` and `data:` lines).
 *
 * Backend format:
 *   event: token\n
 *   data: {"text": "hello"}\n\n
 *
 *   event: evidence\n
 *   data: [{...}, ...]\n\n
 *
 *   event: done\n
 *   data: {"route": "direct", "judge": {...}, ...}\n\n
 */
function parseSSEBlock(block: string): SSEEvent | null {
  let eventType = "";
  let dataStr = "";

  for (const line of block.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("event:")) {
      eventType = trimmed.slice(6).trim();
    } else if (trimmed.startsWith("data:")) {
      dataStr = trimmed.slice(5).trim();
    }
  }

  if (!dataStr) return null;

  try {
    const parsed = JSON.parse(dataStr);

    if (eventType === "token" && typeof parsed.text === "string") {
      return { type: "token", data: parsed.text };
    }

    if (eventType === "evidence" && Array.isArray(parsed)) {
      return { type: "evidence", data: parsed as EvidenceChunk[] };
    }

    if (eventType === "done") {
      const meta: AskMetadata = {
        route: parsed.route ?? "direct",
        faithfulness: parsed.judge?.faithfulness ?? 0,
        relevance: parsed.judge?.relevance ?? 0,
        pipeline: [],
        evidence: [],
      };
      return { type: "done", data: meta };
    }
  } catch {
    // If data isn't JSON and event is token, treat as plain text
    if (eventType === "token") {
      return { type: "token", data: dataStr };
    }
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

    // SSE messages are separated by double newlines
    const blocks = buffer.split("\n\n");
    // Last element is incomplete — keep in buffer
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const trimmed = block.trim();
      if (!trimmed) continue;

      const event = parseSSEBlock(trimmed);
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
    const event = parseSSEBlock(buffer.trim());
    if (event?.type === "done") onDone(event.data);
    else if (event?.type === "token") onToken(event.data);
    else if (event?.type === "evidence") onEvidence(event.data);
  }
}
