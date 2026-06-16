# Judge Behavior Analysis

Analyzed 2026-06-15 after Phase 2a gold case runs.

## Verdict: Judge is strict-and-right

The judge correctly identifies when the answer adds claims not present in the
evidence. It is not overly harsh — it rewards well-grounded answers with 5/5
and correctly penalizes hallucinated details.

---

## Case-by-case analysis

### Body Height (f=5/5) — what good looks like

The evidence chunk contains: LOINC 8302-2, "Body Height", 173.9018914060253 cm,
status: final, effective: 2010-03-01.

The answer constructs an OBX-to-FHIR mapping table where every value
(code, display, value, unit, status, datetime) traces directly back to the
evidence chunk. The model builds an OBX segment example using the same values.

Judge correctly gives 5/5 — nothing is fabricated.

### Blood Pressure (f=2/5) — the product break

The evidence chunk contains: LOINC 55284-4, "Blood Pressure", value type:
component, "Diastolic Blood Pressure: 84.51... mm[Hg] | Systolic Blood
Pressure: 119.11... mm[Hg]", status: final.

The answer correctly cites 55284-4 and the actual values. But it introduces:
- **LOINC 8480-6 (Systolic BP)** — NOT in the evidence
- **LOINC 8462-4 (Diastolic BP)** — NOT in the evidence
- **OBX segment structure** — NOT in the evidence
- **Individual component.code mappings** — NOT in the evidence

These are all *correct* from general FHIR/HL7 knowledge, but the faithfulness
rubric measures against the retrieved evidence, not general correctness.

**Root cause:** The blood pressure chunk stores "Systolic Blood Pressure" and
"Diastolic Blood Pressure" as display text but does NOT include the individual
component LOINC codes (8480-6, 8462-4). The parser's `_slim_observation()`
strips the raw resource JSON down to text, losing the structured component data.

**Fix options (ranked):**
1. Enrich the chunk content — include component LOINC codes in the text output
   from the parser when value type is "component". This gives the model
   grounded data to cite.
2. Accept f=3-4 as the realistic ceiling for component mappings and adjust
   the faithfulness threshold. Not ideal — a demo should be fully grounded.

**Recommended: Option 1.** Fix the parser to emit component codes.

### Smoking Status (f=4/5)

Minor extrapolation — the model adds FHIR JSON structure details (system URLs,
coding arrays) that are standard FHIR boilerplate but not explicitly in the
evidence text. Reasonable. Human agrees with f=4.

### Atrial Fibrillation (f=4/5)

Same pattern as smoking status. The SNOMED code and clinical status come
from evidence. FHIR JSON structure is standard extrapolation. Human agrees
with f=4.

### Medication / Should-Refuse (f=1/5)

Two failures stacked:

**Failure 1 — Retriever:** The query "map a Medication resource for aspirin"
has no matching data (no Medication resources indexed). But the retriever
returned Condition chunks (sinusitis, atrial fibrillation, asthma) because
hybrid search has no minimum score threshold — it always returns top_k results
even when they're irrelevant.

**Failure 2 — Generator:** The model acknowledged "retrieved evidence contains
only Condition resources" but still generated a full Medication mapping guide
from general knowledge. The `no_evidence` route never triggered because the
retriever returned chunks.

**Fix options:**
1. Add a minimum score threshold to `retrieve.py` — if the best result scores
   below e.g. 0.3, return empty and let orchestrator route to `no_evidence`.
2. Add relevance pre-check in orchestrator — if retrieved chunks don't match
   the query's domain intent, treat as no_evidence.
3. Strengthen the system prompt to refuse when evidence doesn't match.

**Recommended: Option 1 + 3.** Score threshold is the cleanest fix. Prompt
reinforcement as defense in depth.

---

## Summary

| Issue | Root Cause | Fix Location |
|-------|-----------|-------------|
| BP component faithfulness | Chunk content lacks component LOINC codes | `parser.py` — enrich component text |
| Medication hallucination | No minimum retrieval score threshold | `retrieve.py` — add score floor |
| Medication hallucination | Model generates despite irrelevant evidence | `prompt.md` — strengthen refusal |
