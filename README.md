# syntra-rag-core

Industry-neutral RAG pipeline. One core, many clients.

## What this is

A reusable Retrieval-Augmented Generation pipeline that separates **domain knowledge** from **pipeline mechanics**. The core handles chunking, embedding, retrieval, generation, and evaluation — all without knowing what domain it's serving. Each client (healthcare, logistics, legal) lives in its own `clients/<name>/` folder.

**First client:** HL7 v2 OBX → FHIR R4 Observation mapping assistant, running on 1,450 indexed Synthea chunks.

## Architecture

```
Question → Reshape → Retrieve (hybrid pgvector + FTS) → Rerank → Generate → Judge
                                                                         ↓
                                                               Faithfulness + Relevance
                                                                    (1-5 rubric)
```

- **Offline:** parse → chunk → dedup → embed → upsert (Supabase pgvector)
- **Live:** reshape → retrieve → generate → judge → trace
- **Trust layer:** Pydantic validation on every artifact, LLM-as-judge on final output

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full diagram.

## Stack

| Layer | Technology |
|-------|-----------|
| Vector store | Supabase pgvector (hybrid: cosine + full-text) |
| Embeddings | Voyage AI (voyage-3, 1024 dims) |
| Generation | Anthropic Claude |
| Judging | Anthropic Claude (rubric-based, no self-grading) |
| Validation | Pydantic v2 |
| Delivery | MCP server + FastAPI |

## Quick start

```bash
# Clone and install
git clone <repo-url>
cd syntra-rag-core
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Configure
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, VOYAGE_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

# Create the database schema
psql $DATABASE_URL < db/migrations/001_init.sql

# Ingest data (FHIR client)
export FHIR_DATA_DIR=/path/to/synthea/fhir
make ingest

# Run the API
make serve

# Run tests
make test

# Check core neutrality
make neutrality
```

## Adding a new client

1. Create `clients/<name>/` with:
   - `parser.py` — implements `DomainParser` from `core/interfaces.py`
   - `schema.py` — Pydantic models for domain-specific validation
   - `config.yaml` — retrieval dials, vocabulary hints, model settings
   - `prompt.md` — system prompt for generation
   - `gold_sets/` — evaluation cases

2. Run ingestion: `FHIR_DATA_DIR=/your/data make ingest`

3. Update `RAG_CLIENT_CONFIG` in `.env` to point to the new config.

**Zero core changes required.** The core never knows what domain it's serving.

## Project structure

```
syntra-rag-core/
  core/                          # Industry-neutral pipeline
    ingestion/                   # Offline: chunk + index
    query/                       # Live: reshape + retrieve + generate + orchestrate
    trust/                       # Validation + eval (judge, calibrate, regression)
    observability/               # Structured tracing
    interfaces.py                # The seam: Chunk + DomainParser
    db.py                        # Shared Supabase singleton
    llm.py                       # Shared Anthropic singleton
    mcp_server.py                # MCP tool exposure
  clients/
    fhir_mapping/                # First client: FHIR mapping assistant
  api/                           # FastAPI server for the chat UI
  tests/                         # Unit tests (80%+ coverage target)
  db/migrations/                 # SQL schema
  scripts/                       # Ingestion + regression runners
```

## Commands

| Command | Description |
|---------|-------------|
| `make install` | Install dependencies |
| `make test` | Run tests with coverage |
| `make lint` | Lint with ruff |
| `make ingest` | Run offline ingestion |
| `make serve` | Start FastAPI server |
| `make mcp` | Start MCP server |
| `make regression` | Run full regression harness |
| `make neutrality` | Verify core has no domain terms |

## Done criteria

1. **Instance works:** Ask a FHIR mapping question → grounded answer with faithfulness score and trace
2. **Core is neutral:** `grep -ri "loinc\|snomed\|fhir\|hl7\|observation" core/` returns nothing
3. **Trust layer is real:** Gold set passes across all value[x] variants
4. **Architecture is real:** Second client runs on same core with zero core changes
