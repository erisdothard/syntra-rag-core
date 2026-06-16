# syntra-rag-core — Build Plan

> Living document. Check off tasks as completed. Each phase is a logical unit
> with a clear "done" gate. Do not advance to the next phase until the gate passes.

---

## Status Key

- [x] Done
- [ ] Not started
- [~] In progress

---

## Phase 0 — Foundation + Silent Bugs

Everything else depends on this. Scaffolding, the retrieval quality bug,
and a corpus sanity check.

- [x] `core/interfaces.py` — Chunk + DomainParser protocol
- [x] `pyproject.toml` — project metadata, dependencies, tooling config
- [x] `.gitignore` — standard Python ignores
- [x] `.env.example` — documents required env vars (no values)
- [x] `CLAUDE.md` — build spec / project constitution
- [x] `ARCHITECTURE.md` — ASCII architecture diagram
- [x] `DATA_SHAPE.md` — Synthea data shape reference
- [x] **Update `ARCHITECTURE.md` build-order table** — mark all 10 steps as "done"
- [ ] **Initialize git repo** — `git init`, initial commit with all existing code
- [x] **Fix declared dependencies** — add `httpx` and `python-dotenv` to `pyproject.toml`
- [x] **Rename `clients/fhir-mapping/` → `clients/fhir_mapping/`** — hyphens in Python package names are non-standard, break normal imports, require `importlib` workarounds. Update all references in `scripts/ingest.py`, `config.yaml`, etc. Updated Supabase rows (1,450) from `fhir-mapping` → `fhir_mapping`.
- [x] **Create `db/migrations/001_init.sql`** — the `chunks` table DDL + `hybrid_search` RPC function as a runnable SQL file (not just in docstrings)
- [x] **Create shared `core/db.py`** — single `get_supabase()` function, replace the 3 duplicate implementations in `index.py`, `retrieve.py`, `mcp_server.py`
- [x] **Fix `embed_texts()` input_type bug** — accept an `input_type` parameter, use `"document"` for indexing and `"query"` for retrieval. `retrieve.py` now passes `input_type="query"`.
- [x] **Verify dedup correctness** — 269,875 raw → 1,450 distinct dedup keys confirmed against source. Match: True.

**Gate:** `pip install -e .` works. `psql < db/migrations/001_init.sql` creates the schema. `git log` shows a clean initial commit. All imports use underscores. `embed_texts` uses correct `input_type` per call site. Dedup count verified against source.

---

## Phase 1 — Wire the dead code

Code that exists but is never called. This is the gap between "I wrote it"
and "the system uses it." No new code — just connecting what's already there.

- [ ] **Wire `validate_chunk()`** into `core/ingestion/chunk.py` or `core/ingestion/index.py` — every chunk gets validated before indexing
- [ ] **Wire `validate_retrieval()`** into `core/query/retrieve.py` or `core/query/orchestrate.py` — every retrieval result gets validated before generation
- [ ] **Wire `validate_domain_chunk()`** from `clients/fhir_mapping/schema.py` into the client's ingestion flow — domain-specific shape validation before indexing
- [ ] **Create `scripts/regression.py`** — a runnable script that invokes `core/trust/evals/regression/run.py` against the configured client

**Gate:** Re-run ingestion — chunks pass both core and domain validation. Re-run an e2e query — retrieval result is validated. `grep -r "validate_chunk\|validate_retrieval\|validate_domain_chunk" core/ clients/` shows real call sites, not just definitions.

---

## Phase 2 — Product correctness (gold cases FIRST)

The gold set tells you whether the **product** works. Unit tests tell you
whether the **code** works. Product correctness is higher-risk: a wrong
mapping in a demo kills a sale; an untested `_parse_response` does not.

This phase runs parallel with Phase 3 (unit tests). Start here.

### 2a — Critical gold cases (4 minimum, covering the hard variants)

- [ ] **Gold case: valueQuantity** — body height (LOINC 8302-2). Already have one happy-path result. Formalize it.
- [ ] **Gold case: component[] panel** — blood pressure (LOINC 85354-9). Systolic + diastolic components. This is the variant most likely to break.
- [ ] **Gold case: valueCodeableConcept** — e.g. smoking status. Tests non-numeric value mapping.
- [ ] **Gold case: Condition (SNOMED routing)** — e.g. "How do I represent Cardiac Arrest in FHIR?" Tests that the retriever finds Conditions, not just Observations.
- [ ] **Gold case: should-refuse** — a question the corpus cannot answer (e.g. a Medication question when no Medication resources are indexed). Should trigger `no_evidence` route with an honest "I don't know."

### 2b — Explain the faithfulness 4/5

The one real result we have scored faithfulness=4/5. Before building a calibration
harness, read the trace and explain why it lost a point.

- [ ] **Read the full trace** of the body-height query result — what evidence was cited, what the answer said, what the judge's reasoning was
- [ ] **Determine: strict-and-right or strict-and-noisy?** — did the judge correctly identify a gap (e.g. the answer added info not in evidence), or is the rubric too harsh? This informs whether to adjust the rubric before calibrating against it.
- [ ] **Document the finding** in `clients/fhir_mapping/gold_sets/JUDGE_NOTES.md`

### 2c — Expand to full gold set

- [ ] **6 more gold cases** (total 10+) — cover: valueString, Patient demographics, multi-resource questions, edge cases from real Synthea data
- [ ] **5+ deterministic cases** in `clients/fhir_mapping/gold_sets/deterministic.json` — question + required substrings that must appear in any correct answer
- [ ] **Run all gold cases through the live pipeline** — record pass/fail per variant
- [ ] **Document baseline metrics** in `clients/fhir_mapping/gold_sets/BASELINE.md` — agreement rate, MAE, pass rates per variant

**Gate:** All 4 critical gold cases pass (correct answer, faithfulness ≥ 3, relevance ≥ 4). The should-refuse case returns `no_evidence` route. Judge behavior is understood and documented. Baseline metrics recorded.

---

## Phase 3 — Unit tests

Now that product correctness is verified, build the code-level safety net.

### Directory structure
```
tests/
  conftest.py               — shared fixtures (mock Supabase, mock Anthropic, sample chunks)
  fixtures/                 — 5 real Synthea JSON files for parser testing
  test_interfaces.py        — Chunk validation, DomainParser contract
  test_parser.py            — FHIRParser against 5 real Synthea files
  test_chunk.py             — ingest(), dedup logic, file resolution
  test_validate.py          — all 3 validate_* functions, edge cases
  test_schema.py            — domain schema validation (FHIR-specific)
  test_index.py             — embed_texts (mocked), index_chunks (mocked Supabase)
  test_retrieve.py          — hybrid_search (mocked), rerank (mocked LLM), _parse_ranking
  test_reshape.py           — reshape (mocked LLM), _parse_response edge cases
  test_generate.py          — generate (mocked LLM), _format_evidence
  test_orchestrate.py       — full pipeline with mocked deps, all 3 routes
  test_judge.py             — rubrics, _parse_judge_response edge cases
  test_trace.py             — trace_result, ring buffer, get_recent, get_flagged
  test_mcp_server.py        — tool registration, basic smoke tests
  test_neutrality.py        — grep core/ for domain terms (automated proof #2)
```

### Tasks
- [ ] **Create `tests/conftest.py`** — fixtures: sample Chunk objects, mock Supabase client, mock Anthropic client, path to test Synthea files
- [ ] **Copy 5 real Synthea files** to `tests/fixtures/` for parser testing
- [ ] **`test_interfaces.py`** — Chunk model validation, DomainParser protocol conformance
- [ ] **`test_parser.py`** — parse real Synthea bundles, verify all 3 value[x] variants, dedup_key correctness
- [ ] **`test_chunk.py`** — ingest with mock parser, dedup behavior, empty input, file glob
- [ ] **`test_validate.py`** — validate_chunk passes/rejects, validate_retrieval passes/rejects, validate_generation passes/rejects
- [ ] **`test_schema.py`** — ObservationChunkSchema, ConditionChunkSchema, PatientChunkSchema, validate_domain_chunk dispatch
- [ ] **`test_index.py`** — embed_texts with mocked Voyage API (200, 429, failure), index_chunks with mocked Supabase
- [ ] **`test_retrieve.py`** — _hybrid_search mocked, _rerank mocked, _parse_ranking edge cases (malformed JSON, out-of-range indices)
- [ ] **`test_reshape.py`** — reshape with mocked LLM, _parse_response edge cases (code fences, invalid JSON, empty response)
- [ ] **`test_generate.py`** — generate with mocked LLM, _format_evidence (empty chunks, many chunks)
- [ ] **`test_orchestrate.py`** — all 3 routes (direct, decomposed, no_evidence), config loading, prompt loading
- [ ] **`test_judge.py`** — judge with mocked LLM, _parse_judge_response edge cases, threshold behavior
- [ ] **`test_trace.py`** — trace_result builds correct structure, ring buffer eviction, get_flagged filters correctly
- [ ] **`test_mcp_server.py`** — tools are registered, ask_question smoke test with mocks
- [ ] **`test_neutrality.py`** — automated grep: no domain terms in core/
- [ ] **Coverage ≥ 80%** — run `pytest --cov=core --cov=clients --cov-report=term-missing`

**Gate:** `pytest` passes. Coverage ≥ 80%. `test_neutrality.py` passes.

---

## Phase 4 — Production hardening

The code works but wouldn't survive real traffic. This phase fixes the
operational gaps.

### Connection management
- [ ] **Singleton Anthropic client** — create once in `core/llm.py`, share across reshape, retrieve, generate, judge. Stop creating a new client per function call.
- [ ] **Singleton Supabase client** — `core/db.py` (from Phase 0) used everywhere

### Parallelism
- [ ] **Parallelize judge calls** — faithfulness + relevance via `asyncio.gather()` in `rubrics.py` (they're independent)
- [ ] **Parallelize sub-query retrieval** — `asyncio.gather()` in `orchestrate._retrieve_decomposed()` (each sub-query is independent)

### Error handling
- [ ] **Add retry logic to Anthropic API calls** — at minimum in `generate.py` (currently zero error handling) and `reshape.py`
- [ ] **Surface reranker failures** — log warning + degrade gracefully but don't silently swallow the error in `retrieve.py`

### Observability
- [ ] **Per-stage timing** — pass timestamps through the pipeline so `trace.py` records real `duration_ms` per event (currently all hardcoded to `0.0`)
- [ ] **Thread-safe trace buffer** — replace `list` with `collections.deque(maxlen=200)` in `trace.py`

### Caching
- [ ] **Cache config at startup** — `orchestrate.py` and `mcp_server.py` re-read + re-parse YAML on every request for data that never changes at runtime

### Streaming (for the UI)
- [ ] **Add streaming option to `generate.py`** — `client.messages.stream()` instead of `.create()`, yield tokens as they arrive. Required for the chat UI in Phase 6.

**Gate:** Single user question creates exactly 1 Anthropic client and 1 Supabase client (not 4+). Judge latency drops measurably from parallelism. `trace.py` shows real per-stage ms. Generate can stream.

---

## Phase 5 — Deployment infra

No Dockerfile, no CI, no migrations runner. This phase makes it deployable
by someone other than you.

- [ ] **`Dockerfile`** — Python 3.11+, installs deps, runs the MCP server or FastAPI (depending on entry point)
- [ ] **`docker-compose.yml`** (optional) — local dev with the app container
- [ ] **`.github/workflows/ci.yml`** — on push/PR: lint (`ruff`), typecheck, test (`pytest --cov`), neutrality grep
- [ ] **`.github/workflows/regression.yml`** — on push to main: run the full regression harness
- [ ] **`Makefile` or `justfile`** — common commands: `make test`, `make lint`, `make ingest`, `make serve`, `make regression`
- [ ] **`README.md`** — project overview, architecture, setup instructions, how to add a new client, link to live demo

**Gate:** `docker build .` succeeds. GitHub Actions CI runs and passes on push. A new developer can clone, read the README, and have it running in < 15 minutes.

---

## Phase 6 — Chat UI + Deploy

The sales pitch. A clean web interface that demonstrates the pipeline
visually — not a template.

> **HARD GATE: Phase 6 does NOT start until Phase 2's gold set passes across
> all three value[x] variants plus the SNOMED Condition case.** A beautiful
> chat UI over an uncalibrated, partially-validated pipeline is a liability —
> it makes wrong answers look more authoritative.

### Backend (FastAPI)
- [ ] **`api/main.py`** — FastAPI app wrapping the pipeline
- [ ] **`POST /ask`** — streams the answer via SSE (Server-Sent Events)
- [ ] **`GET /traces`** — recent traces for the UI
- [ ] **CORS config** — allow the Vercel frontend
- [ ] **Deploy to Railway** — Python runtime, env vars, no timeout issues

### Frontend (Next.js)
- [ ] **Chat interface** — question input, streaming answer display
- [ ] **Evidence panel** — collapsible, shows which chunks were cited with relevance scores
- [ ] **Judge badges** — faithfulness + relevance scores displayed per answer
- [ ] **Pipeline trace** — visual timeline showing reshape → retrieve → generate → judge with real ms durations
- [ ] **Deploy to Vercel** — connected to the Railway backend

**Gate:** Live URL works. Ask a FHIR mapping question in the browser → see the answer stream in with evidence citations and judge scores. All gold-set variants produce correct answers in the UI. Shareable link for portfolio and client demos.

---

## Phase 7 — Second client (proves the architecture)

The spec says: "could you serve a logistics client by adding only a new
`clients/<name>/` folder, without editing a single file in the core?"

This phase proves it. Pick a non-healthcare domain and add a second client.

- [ ] **Choose a domain** — logistics, contracts, or policy docs
- [ ] **`clients/<name>/parser.py`** — implements DomainParser for the new domain
- [ ] **`clients/<name>/schema.py`** — domain-specific Pydantic models
- [ ] **`clients/<name>/config.yaml`** — retrieval dials, vocabulary hints
- [ ] **`clients/<name>/prompt.md`** — system prompt for the domain
- [ ] **`clients/<name>/gold_sets/`** — at least 5 gold cases
- [ ] **Ingest + query** — run the full pipeline for the new client without touching core/
- [ ] **Tests** — parser tests for the new client

**Gate:** Two clients running on the same core, same database (row-level separation via `client` column), zero core changes. This is the proof that "one core, many clients" is real, not aspirational.

---

## Execution Order (corrected priority)

The phases are numbered for reference, but the execution order reflects
actual risk priority — product correctness before code polish.

```
Phase 0   Foundation + input_type fix + dedup verification
  │
  ▼
Phase 1   Wire dead validation code (trust layer must actually run)
  │
  ▼
Phase 2a  4 gold cases covering hard variants (find product breaks NOW)
  │
  ▼
Phase 2b  Read the faithfulness-4 trace, understand judge behavior
  │
  ├──────────────────────┐
  ▼                      ▼
Phase 2c + 3            Phase 4
Full gold set +         Production hardening
Unit tests (parallel)   (parallel with tests)
  │                      │
  ├──────────────────────┘
  ▼
Phase 5   Deployment infra
  │
  ▼
Phase 6   Chat UI (BLOCKED until gold set green on all variants)
  │
  ▼
Phase 7   Second client
```

---

## Done Criteria (from CLAUDE.md)

Both proofs, both required:

1. **The instance works:** A question like "how do I map an OBX segment for body height
   to a FHIR Observation" returns a grounded answer citing a real Observation shape from
   the indexed Synthea data, with a faithfulness score and a logged trace.
   **Status: PASSING** (verified 2026-06-15)

2. **The core is neutral:** `grep -ri "loinc\|snomed\|fhir\|hl7\|observation" core/`
   returns nothing.
   **Status: PASSING** (verified 2026-06-15)

Additional proofs:

3. **The trust layer is real:** Gold set passes across all three value[x] variants,
   SNOMED Condition, and the should-refuse case. Judge behavior documented.
   **Status: NOT STARTED**

4. **The architecture is real:** A second, non-healthcare client runs on the same core
   with zero core changes.
   **Status: NOT STARTED**
