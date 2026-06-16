# CLAUDE.md — syntra-rag-core build spec

You are building **one reusable, industry-neutral RAG pipeline** (`syntra-rag-core`) and **one client instance** that runs on top of it. The core knows nothing about any specific domain. The first client is a healthcare FHIR mapping assistant, but it lives entirely in `clients/fhir-mapping/` and must never leak domain logic into the core.

The model: **one core, many clients.** A non-healthcare customer is a new folder under `clients/`, never a new pipeline and never a forked skeleton.

## Two layers, hard separation

**The core (`syntra-rag-core/`) is industry-neutral. It must contain ZERO domain knowledge.**
No LOINC, no SNOMED, no FHIR, no HL7, no healthcare strings, no client-specific schema columns. If a healthcare term appears anywhere in the core, that is a bug.

**The client (`clients/<name>/`) holds ALL domain specifics:** how to parse that client's data, their schema, their prompt, their rubric, their gold set.

The test that proves the separation held: **could you serve a logistics client by adding only a new `clients/<name>/` folder, without editing a single file in the core?** If no, domain logic leaked into the core. Fix it.

## Core principle

The pipeline is **validate → route → check**, true for any corpus (contracts, carrier docs, policies, clinical data):
- **Offline** (runs once, on data change): chunk → index.
- **Live** (runs per question): reshape → retrieve → orchestrate → generate.
- **Trust layer** wraps both: cheap Pydantic validation on every artifact, selective LLM-as-judge faithfulness scoring on the final output + the retrieval result, regression + judge calibration.

Context collapse is NOT a component. It is the failure prevented by tight retrieval (reshape + rerank). Do not build a module for it.

## Stack

- Python 3.11+
- Vector store: **Supabase pgvector**. One database for vectors + app data. `vector` extension, cosine distance, HNSW index on the embedding column.
- Embeddings + generation + judging: Anthropic Claude API.
- Validation: Pydantic v2.
- Eval: rubric-based LLM-as-judge (custom, or RAGAS if preferred).
- Delivery: expose the pipeline as an MCP server.

## Repo structure

```
syntra-rag-core/                  # THE CORE — industry-neutral, built once, never forked
  core/
    ingestion/
      chunk.py        # generic: takes a domain parser (injected), returns chunks. Knows NO formats.
      index.py        # embed + upsert to Supabase pgvector. Generic schema.
    query/
      reshape.py      # rewrite question using vocabulary supplied by client config
      retrieve.py     # hybrid (vector + full-text) search, then rerank, return top_k
      orchestrate.py  # route to simplest capability that answers; escalate only when proven necessary
      generate.py     # Claude call with retrieved context
    trust/
      validate.py     # Pydantic base models; runs on EVERY artifact (cheap)
      evals/
        judge/
          rubrics.py    # 1-5 graded faithfulness/relevance vs retrieved evidence
          calibrate.py  # check judge scores vs human-labeled gold set; flag drift
        regression/
          run.py        # runs deterministic + judge on every change
    observability/
      trace.py        # log every live request: retrieved, kept, generated, flagged
    mcp_server.py     # exposes generic tools: ask(question), get_chunk(key)
    interfaces.py     # the DomainParser protocol every client must implement (see below)
  clients/
    fhir-mapping/                 # THE FIRST CLIENT — all healthcare lives here, nowhere else
      config.yaml     # dials: top_k, thresholds, models, vocabulary hints
      parser.py       # implements DomainParser: parses FHIR bundles, LOINC/SNOMED, value[x]
      schema.py       # client-specific Pydantic models (Observation shape, etc.)
      gold_sets/      # this client's known-good cases
      prompt.md       # this client's system prompt
  README.md
```

## The seam: DomainParser

The core never parses anyone's data directly. It defines an interface in `core/interfaces.py`; each client implements it. This is the mechanism that keeps the core neutral.

```python
# core/interfaces.py  (CORE — generic, no domain terms)
from typing import Protocol, Iterable
from pydantic import BaseModel

class Chunk(BaseModel):
    domain_key: str | None   # client decides meaning (LOINC code, contract id, policy num...)
    kind: str                # client decides (Observation, Clause, Policy...)
    variant: str | None      # client decides
    content: str             # the human-readable text retrieved
    metadata: dict           # anything client-specific goes here

class DomainParser(Protocol):
    def parse(self, raw_path: str) -> Iterable[Chunk]: ...
    def dedup_key(self, chunk: Chunk) -> str: ...
```

`chunk.py` calls `parser.parse(...)`. The FHIR client's `parser.py` is the only place that knows what an Observation or a LOINC code is. Swap the parser, serve a different industry, core untouched.

## Build order (do NOT reorder — each step testable before the next)

1. **`core/interfaces.py`** — define `Chunk` and `DomainParser` first. Everything depends on this seam.
2. **`clients/fhir-mapping/parser.py`** — implement `DomainParser` for FHIR per `DATA_SHAPE.md`. Handle all three `value[x]` variants (valueQuantity, valueCodeableConcept, component). Test against 5 real Synthea files.
3. **`core/ingestion/chunk.py`** — generic; calls the injected parser. Verify it works with the FHIR parser but contains no FHIR terms itself.
4. **`core/trust/validate.py`** + **`clients/fhir-mapping/schema.py`** — base models in core, client-specific shapes in the client.
5. **`core/trust/evals/`** — harness BEFORE retrieval/generation so everything later is measured.
6. **`core/ingestion/index.py`** + **`core/query/retrieve.py`** — hybrid search + rerank.
7. **`core/query/reshape.py`** — question rewriting using vocabulary from client config.
8. **`core/query/generate.py`** + **`core/query/orchestrate.py`**.
9. **`core/observability/trace.py`**.
10. **`core/mcp_server.py`** last.

## Hard rules

- **The core contains zero domain terms.** No LOINC/SNOMED/FHIR/HL7 anywhere under `core/`. Grep for them before declaring done; any hit is a leak.
- **Fix chunking before touching retrieval.** Over-engineered retriever on bad chunks is the most common failure.
- **Validation everywhere (cheap), judging selectively (expensive).** Pydantic on every artifact. LLM-as-judge only on the final output and the retrieval result.
- **No model self-confidence scores.** The judge scores against retrieved evidence with a rubric. The model never grades its own certainty.
- **Orchestrator defaults to the simplest tool that works.** If most requests route to agents, it is overbuilt.
- **Secrets in env vars, never in config.** Config holds dials, not credentials.

## Supabase schema (generic — no domain columns)

The table is industry-neutral. Domain meaning lives in `domain_key`/`kind`/`variant` (client-defined) and `metadata jsonb`.

```sql
create extension if not exists vector;

create table chunks (
  id uuid primary key default gen_random_uuid(),
  client text not null,            -- which client folder owns this row
  domain_key text,                 -- client-defined (LOINC code for FHIR; contract id elsewhere)
  kind text,                       -- client-defined (Observation, Clause, ...)
  variant text,                    -- client-defined
  content text not null,
  metadata jsonb default '{}',
  embedding vector(1536)           -- match your embedding model's dimension
);

create index on chunks using hnsw (embedding vector_cosine_ops);
create index on chunks using gin (to_tsvector('english', content));
```

- Hybrid search: pgvector cosine + Postgres full-text in one query, then rerank in `retrieve.py`. One system, no second store.
- `index.py` upserts; dedup key comes from the client's `dedup_key()`, not hardcoded. For FHIR that is `domain_key + variant`; the core does not know or care.
- Every row carries `client`, so one database can serve many clients with row-level separation.

## What "done" looks like

Two proofs, both required:

1. **The instance works:** an MCP question like "how do I map an OBX segment for body height to a FHIR Observation" returns a grounded answer citing a real Observation shape from the indexed Synthea data, with a faithfulness score and a logged trace.
2. **The core is neutral:** `grep -ri "loinc\|snomed\|fhir\|hl7\|observation" core/` returns nothing. All of it lives under `clients/fhir-mapping/`. If that grep is clean and proof 1 passes, you have a reusable platform, not a healthcare app.
