# syntra-rag-core

**Production RAG pipeline with built-in trust scoring.** One core serves any domain — healthcare, logistics, legal — without changing a single line of pipeline code.

[Live Demo](https://syntra-rag-core.vercel.app) | [Architecture](ARCHITECTURE.md) | [Build Plan](PLAN.md)

---

## Why this exists

Most RAG demos retrieve chunks and hope for the best. This pipeline **validates every artifact**, **scores every answer** for faithfulness and relevance (LLM-as-judge, 1-5 rubric), and **traces every request** end-to-end. Domain knowledge is fully separated from pipeline mechanics — adding a new industry is a folder, not a fork.

## What it does

```
Question → Reshape → Retrieve (hybrid pgvector + FTS) → Rerank → Generate → Judge
                                                                         ↓
                                                               Faithfulness + Relevance
                                                                    (1-5 rubric scored
                                                                     against evidence)
```

- **Offline pipeline:** parse → chunk → dedup → embed → upsert (Supabase pgvector)
- **Live pipeline:** reshape → retrieve → rerank → generate → judge → trace
- **Trust layer:** Pydantic validation on every artifact, LLM-as-judge on final output, regression harness, judge calibration

## Proof it works

| Proof | Status |
|-------|--------|
| Ask a FHIR mapping question → grounded answer with faithfulness score and trace | Passing |
| `grep -ri "loinc\|snomed\|fhir\|hl7" core/` returns nothing | Passing |
| 11 gold cases across all value[x] variants, Conditions, and should-refuse | Passing |
| Logistics client runs on same core, zero core changes | Passing |
| 136 unit tests | Passing |

## Two clients, one core

**Healthcare (FHIR Mapping)** — 644 chunks across 8 FHIR resource types (Observation, Condition, Patient, MedicationRequest, Procedure, Immunization, DiagnosticReport, Encounter). Parses Synthea patient bundles, maps HL7 v2 segments to FHIR R4 resources.

**Logistics** — Carriers, rates, and service documents. Parses structured freight data with domain-specific validation. Added without touching any file in `core/`.

## Stack

| Layer | Technology |
|-------|-----------|
| Vector store | Supabase pgvector (hybrid: cosine + full-text search) |
| Embeddings | Voyage AI (voyage-3, 1024 dims) |
| Generation | Anthropic Claude (Sonnet 4.6) |
| Judging | Anthropic Claude (Haiku 4.5, rubric-based, no self-grading) |
| Validation | Pydantic v2 on every artifact |
| Backend | FastAPI with SSE streaming |
| Frontend | Next.js, Tailwind CSS, react-markdown |
| Delivery | MCP server + REST API |

## Quick start

```bash
git clone https://github.com/erisdothard/syntra-rag-core.git
cd syntra-rag-core
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, VOYAGE_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

# Create the database schema
psql $DATABASE_URL < db/migrations/001_init.sql

# Ingest data
export FHIR_DATA_DIR=/path/to/synthea/fhir
make ingest

# Start the backend
make serve

# Start the frontend
cd web && npm install && npm run dev
```

## Adding a new client

1. Create `clients/<name>/` with:
   - `parser.py` — implements `DomainParser` from `core/interfaces.py`
   - `schema.py` — Pydantic models for domain-specific validation
   - `config.yaml` — retrieval dials, vocabulary hints, model settings
   - `prompt.md` — system prompt
   - `gold_sets/` — evaluation cases

2. Run ingestion pointing to your data.

3. Set `RAG_CLIENT_CONFIG` to your new config.

**Zero core changes required.** The core never knows what domain it's serving.

## Project structure

```
syntra-rag-core/
  core/                          # Industry-neutral pipeline (zero domain terms)
    ingestion/                   # Offline: chunk + index
    query/                       # Live: reshape + retrieve + generate + orchestrate
    trust/                       # Validation + eval (judge, calibrate, regression)
    observability/               # Structured tracing (ring buffer + JSON logs)
    interfaces.py                # The seam: Chunk + DomainParser protocol
    db.py                        # Supabase singleton
    llm.py                       # Anthropic singleton (max_retries=3)
    mcp_server.py                # MCP tool exposure
  clients/
    fhir_mapping/                # Healthcare: FHIR mapping assistant (8 resource types)
    logistics/                   # Freight: carriers, rates, services
  api/                           # FastAPI backend (SSE streaming, traces, health)
  web/                           # Next.js chat UI (evidence panel, judge badges, pipeline trace)
  tests/                         # 136 unit tests across 16 files
  db/migrations/                 # SQL schema + hybrid_search RPC
  scripts/                       # Ingestion + regression runners
```

## Commands

| Command | Description |
|---------|-------------|
| `make test` | Run 136 tests with coverage |
| `make lint` | Lint with ruff |
| `make ingest` | Run offline ingestion pipeline |
| `make serve` | Start FastAPI server |
| `make mcp` | Start MCP server |
| `make regression` | Run full regression harness |
| `make neutrality` | Verify core has zero domain terms |
