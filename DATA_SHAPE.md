# Synthea FHIR R4 — Data Shape Reference

Derived from the actual dataset: `synthea_sample_data_fhir_r4_sep2019.zip`. Build ingestion against these real shapes, not the documented-in-theory format.

## Dataset facts

- **1,179 patient files** in `fhir/`, one JSON per patient. Total ~1.3 GB unzipped.
- Filenames: `FirstName###_LastName###_<uuid>.json`. The trailing numbers are the Synthea tell that this is synthetic (no real PHI).
- There are **no separate hospital/practitioner files** in this release. Organizations and Practitioners are embedded inside each patient bundle.
- Largest single file is ~42 MB. Stream-parse; do not assume small files.

## Bundle structure

Each file is one FHIR `Bundle`:

```
{
  "resourceType": "Bundle",
  "type": "transaction",
  "entry": [ { "fullUrl": "...", "resource": {...}, "request": {...} }, ... ]
}
```

- Every entry has three keys: `fullUrl`, `resource`, `request`.
- `fullUrl` is a `urn:uuid:<id>`. **This is how resources reference each other** (see References below).
- `request` is just the transaction directive (`{"method":"POST","url":"Patient"}`), ignore it for RAG.
- One sample bundle had **319 entries**. Distribution (one patient):

| Resource | Count | Use for mapping assistant |
|---|---|---|
| Observation | 187 | **PRIMARY TARGET** (OBX → Observation) |
| Claim | 22 | skip (billing) |
| Encounter | 21 | context only |
| ExplanationOfBenefit | 21 | skip (billing) |
| DiagnosticReport | 15 | secondary (OBR → DiagnosticReport) |
| Immunization | 13 | optional |
| Procedure | 13 | optional |
| Condition | 10 | secondary |
| Goal | 5 | skip |
| Organization, Practitioner, CareTeam, CarePlan | 2 each | reference data |
| Patient, Device, MedicationRequest, ImagingStudy | 1 each | Patient = PID mapping |

## Observation shape (the one that matters)

Three `value[x]` variants exist in the real data. Your chunker/validator MUST handle all three or it breaks on real input:

| Variant | Frequency (sample) | Trigger |
|---|---|---|
| `valueQuantity` | 167 | numeric result (height, weight, lab value) |
| `valueCodeableConcept` | 10 | coded result (e.g. a categorical finding) |
| `component[]` (no top-level value) | 10 | **panels** like Blood Pressure, where each sub-reading is its own coded component |

### valueQuantity example (simple numeric)
```json
{
  "resourceType": "Observation",
  "id": "...",
  "status": "final",
  "category": [{"coding":[{"system":".../observation-category","code":"vital-signs"}]}],
  "code": {
    "coding": [{"system":"http://loinc.org","code":"8302-2","display":"Body Height"}],
    "text": "Body Height"
  },
  "subject":   {"reference":"urn:uuid:<patient-id>"},
  "encounter": {"reference":"urn:uuid:<encounter-id>"},
  "effectiveDateTime": "2010-03-01T06:22:41-05:00",
  "issued": "2010-03-01T06:22:41.399-05:00",
  "valueQuantity": {"value":173.9,"unit":"cm","system":"http://unitsofmeasure.org","code":"cm"}
}
```

### component/panel example (Blood Pressure — no top-level value[x])
```json
{
  "resourceType": "Observation",
  "code": {"coding":[{"system":"http://loinc.org","code":"55284-4","display":"Blood Pressure"}]},
  "component": [
    {"code":{"coding":[{"system":"http://loinc.org","code":"8462-4","display":"Diastolic Blood Pressure"}]},
     "valueQuantity":{"value":84.5,"unit":"mm[Hg]","code":"mm[Hg]"}},
    {"code":{"coding":[{"system":"http://loinc.org","code":"8480-6","display":"Systolic Blood Pressure"}]},
     "valueQuantity":{"value":119.1,"unit":"mm[Hg]","code":"mm[Hg]"}}
  ]
}
```

### Key field paths for the OBX → Observation mapping
| Concept (HL7 v2 OBX) | FHIR path in this data |
|---|---|
| LOINC code (OBX-3) | `code.coding[].code` where `system == http://loinc.org` |
| Result name | `code.text` or `code.coding[].display` |
| Value (OBX-5) | `valueQuantity.value` OR `valueCodeableConcept` OR per-`component[].valueQuantity` |
| Units (OBX-6) | `valueQuantity.unit` / `valueQuantity.code` (UCUM) |
| Status (OBX-11) | `status` (e.g. "final") |
| Obs datetime (OBX-14) | `effectiveDateTime` |
| Category (vital-signs/laboratory) | `category[].coding[].code` |

## Other resources you'll touch

- **Patient**: keys `id, identifier, name, telecom, gender, birthDate, address, maritalStatus, communication`. Maps to HL7 v2 PID.
- **Condition**: `code.coding[]` uses **SNOMED** (`http://snomed.info/sct`), not LOINC. Different code system, note it in mapping logic.

## References between resources

- Resources point to each other by `{"reference":"urn:uuid:<id>"}` matching another entry's `fullUrl`.
- To resolve "which patient does this Observation belong to," match `Observation.subject.reference` against the `Patient` entry's `fullUrl`.
- **Implication for chunking**: an Observation alone loses patient/encounter context. Decide whether to denormalize (inline patient age/sex into the chunk) or keep references and resolve at retrieval. For a mapping assistant, the Observation's own `code` + `value[x]` is usually self-sufficient; denormalization is optional.

## Chunking guidance specific to this data

- **Do not chunk by character count.** One Observation = one natural chunk. It's already an atomic, self-describing unit.
- The mapping assistant's corpus is really "distinct Observation *shapes*," not 187×1179 individual readings. **Deduplicate by LOINC code** during ingestion or you index the same "Body Height / 8302-2" structure thousands of times and bloat the store for nothing. Keep one canonical example per unique `code.coding[].code` + `value[x]`-variant.
- That dedup step is the single most important ingestion decision for this corpus. Raw = ~200k near-identical Observations. Deduped = a few hundred distinct mapping patterns. The deduped set is the actual knowledge base.
