# syntra-rag-core — Architecture

Industry-neutral RAG pipeline. One core, many clients.

```
╔══════════════════════════════════════════════════════════════════════════╗
║                         syntra-rag-core                                 ║
║                  industry-neutral RAG pipeline                          ║
║                    one core, many clients                               ║
╚══════════════════════════════════════════════════════════════════════════╝


  ┌─────────────────────────────────────────────────────────────────────┐
  │  clients/<name>/                                                    │
  │                                                                     │
  │  Any industry. Any data format. Implements DomainParser.            │
  │                                                                     │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐  │
  │  │ parser.py│ │ schema.py│ │config.yml│ │prompt.md│ │gold_sets/│  │
  │  └─────┬────┘ └─────┬────┘ └─────┬────┘ └────┬────┘ └─────┬────┘  │
  └────────┼────────────┼────────────┼───────────┼────────────┼────────┘
           │            │            │           │            │
  ═══════════════════  THE SEAM  ══════════════════════════════════════
           │            │            │           │            │
           ▼            ▼            ▼           ▼            ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │  core/interfaces.py                                                │
  │                                                                    │
  │  Chunk(BaseModel)              DomainParser(Protocol)              │
  │    domain_key  ─ client names    parse(path) → Iterable[Chunk]    │
  │    kind        ─ client names    dedup_key(chunk) → str           │
  │    variant     ─ client names                                      │
  │    content     ─ retrieved text                                    │
  │    metadata    ─ anything                                          │
  └────────────────────────┬───────────────────────────────────────────┘
                           │
  ═════════════════════════╪═══════════════════════════════════════════
                           │
  ┌────────────────────────┼──────────────────────────────────────────┐
  │  core/                 │                                          │
  │                        │                                          │
  │  ┌────────────────────────────────────────────────────────────┐   │
  │  │  OFFLINE                                                   │   │
  │  │                                                            │   │
  │  │   raw files ──▶ ┌──────────┐  Chunks  ┌──────────┐        │   │
  │  │                 │ chunk.py │────────▶│ index.py │        │   │
  │  │                 │          │          │          │        │   │
  │  │                 │ calls    │          │ embed +  │        │   │
  │  │                 │ parser   │          │ upsert   │        │   │
  │  │                 │ dedup    │          │          │        │   │
  │  │                 └──────────┘          └────┬─────┘        │   │
  │  └────────────────────────────────────────────┼──────────────┘   │
  │                                               │                   │
  │                                        ┌──────▼──────┐            │
  │                                        │  Supabase   │            │
  │                                        │  pgvector   │            │
  │                                        │             │            │
  │                                        │ chunks tbl  │            │
  │                                        │ vector+fts  │            │
  │                                        └──────┬──────┘            │
  │                                               │                   │
  │  ┌────────────────────────────────────────────┼──────────────┐   │
  │  │  LIVE                                      │              │   │
  │  │                                            │              │   │
  │  │  question ──▶ ┌─────────┐  ┌──────────┐   │              │   │
  │  │               │reshape  │─▶│retrieve  │◀──┘              │   │
  │  │               │         │  │          │                   │   │
  │  │               │rewrite  │  │hybrid    │  top_k           │   │
  │  │               │question │  │search +  │─────┐            │   │
  │  │               └─────────┘  │rerank    │     │            │   │
  │  │                            └──────────┘     │            │   │
  │  │                                             ▼            │   │
  │  │                           ┌─────────────┐ ┌──────────┐   │   │
  │  │                           │orchestrate  │▶│generate  │   │   │
  │  │                           │             │ │          │   │   │
  │  │                           │route to     │ │Claude +  │   │   │
  │  │                           │simplest     │ │context   │──▶ answer
  │  │                           │capability   │ │          │   │   │
  │  │                           └─────────────┘ └──────────┘   │   │
  │  └──────────────────────────────────────────────────────────┘   │
  │                                                                  │
  │  ┌──────────────────────────────────────────────────────────┐   │
  │  │  TRUST                                                    │   │
  │  │                                                           │   │
  │  │  ┌────────────┐  ┌────────────┐  ┌────────────┐          │   │
  │  │  │validate.py │  │rubrics.py  │  │calibrate.py│          │   │
  │  │  │            │  │            │  │            │          │   │
  │  │  │Pydantic on │  │LLM judge   │  │judge vs    │          │   │
  │  │  │EVERY       │  │1-5 against │  │human gold  │          │   │
  │  │  │artifact    │  │evidence    │  │set drift   │          │   │
  │  │  │(cheap)     │  │(selective) │  │            │          │   │
  │  │  └────────────┘  └────────────┘  └────────────┘          │   │
  │  │                                                           │   │
  │  │               ┌──────────────┐                            │   │
  │  │               │regression/   │                            │   │
  │  │               │run.py        │                            │   │
  │  │               │on every      │                            │   │
  │  │               │change        │                            │   │
  │  │               └──────────────┘                            │   │
  │  └──────────────────────────────────────────────────────────┘   │
  │                                                                  │
  │  ┌──────────────────────────────────────────────────────────┐   │
  │  │  OBSERVABILITY                                            │   │
  │  │  trace.py — logs: retrieved, kept, generated, flagged     │   │
  │  └──────────────────────────────────────────────────────────┘   │
  │                                                                  │
  │  ┌──────────────────────────────────────────────────────────┐   │
  │  │  MCP SERVER                                               │   │
  │  │  ask(question)    get_chunk(key)                          │   │
  │  └──────────────────────────────────────────────────────────┘   │
  └──────────────────────────────────────────────────────────────────┘


  PIPELINE FLOW
  ═════════════

  validate ──▶ route ──▶ check

  OFFLINE:  raw files ──▶ parse ──▶ dedup ──▶ embed ──▶ store
  LIVE:     question ──▶ reshape ──▶ retrieve ──▶ orchestrate ──▶ generate
  TRUST:    pydantic on everything (cheap) │ llm judge on output + retrieval (selective)
```

## Build Order

| Step | File | Code | Wired | Tested |
|------|------|:----:|:-----:|:------:|
| 1 | `core/interfaces.py` | done | done | — |
| 2 | `clients/fhir_mapping/parser.py` | done | done | — |
| 3 | `core/ingestion/chunk.py` | done | done | — |
| 4 | `core/trust/validate.py` + `clients/fhir_mapping/schema.py` | done | partial | — |
| 5 | `core/trust/evals/*` | done | partial | — |
| 6 | `core/ingestion/index.py` + `core/query/retrieve.py` | done | done | — |
| 7 | `core/query/reshape.py` | done | done | — |
| 8 | `core/query/generate.py` + `core/query/orchestrate.py` | done | done | — |
| 9 | `core/observability/trace.py` | done | done | — |
| 10 | `core/mcp_server.py` | done | done | — |

> **"partial"** = code exists but some functions are never called (see PLAN.md Phase 1)

## Neutrality Test

```bash
grep -ri "loinc\|snomed\|fhir\|hl7\|observation" core/
# Must return nothing. Any hit = domain leak.
```
