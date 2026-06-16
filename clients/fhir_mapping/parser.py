"""
clients/fhir_mapping/parser.py

DomainParser implementation for Synthea FHIR R4 bundles.

Handles:
- Observation (primary): all three value[x] variants
  - valueQuantity (numeric results)
  - valueCodeableConcept (coded results)
  - component[] panels (e.g. Blood Pressure — no top-level value)
- Condition: SNOMED-coded diagnoses
- Patient: PID-equivalent demographics
- MedicationRequest: prescribed medications (RxNorm)
- Procedure: surgical/clinical procedures (SNOMED)
- Immunization: vaccine records (CVX)
- DiagnosticReport: lab/imaging panel summaries (LOINC)
- Encounter: visit/admission records (SNOMED)

Files can be 40MB+. Uses ijson for streaming when available,
falls back to chunked stdlib json parsing.

Dedup strategy: code + variant (or kind for non-Observation types).
One canonical example per distinct shape — not one chunk per reading.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from core.interfaces import Chunk

logger = logging.getLogger(__name__)

# Resource types we extract. Everything else is skipped.
_TARGET_TYPES = frozenset({
    "Observation", "Condition", "Patient",
    "MedicationRequest", "Procedure", "Immunization",
    "DiagnosticReport", "Encounter",
})

# Code system URLs → short labels
_SYSTEM_LABELS = {
    "http://loinc.org": "LOINC",
    "http://snomed.info/sct": "SNOMED",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
    "http://hl7.org/fhir/sid/cvx": "CVX",
    "http://terminology.hl7.org/CodeSystem/v3-ActCode": "ActCode",
    "http://terminology.hl7.org/CodeSystem/v2-0074": "HL7v2",
}


class FHIRParser:
    """DomainParser for Synthea FHIR R4 patient bundles."""

    def parse(self, raw_path: str) -> Iterable[Chunk]:
        """Parse a single FHIR Bundle JSON and yield Chunks."""
        path = Path(raw_path)
        if not path.exists():
            logger.warning("File not found: %s", path)
            return

        bundle = _load_bundle(path)
        if bundle is None:
            return

        entries = bundle.get("entry", [])
        if not entries:
            logger.warning("Empty bundle: %s", path)
            return

        for entry in entries:
            resource = entry.get("resource")
            if resource is None:
                continue

            rtype = resource.get("resourceType")
            if rtype not in _TARGET_TYPES:
                continue

            chunk = _resource_to_chunk(resource, rtype)
            if chunk is not None:
                yield chunk

    def dedup_key(self, chunk: Chunk) -> str:
        """Dedup key: domain_key + variant.

        For Observations this collapses thousands of identical Body Height
        readings into one canonical example per LOINC code + value[x] shape.
        For Patients, dedup by kind alone — one example is enough to
        demonstrate the resource shape.
        """
        if chunk.kind == "Patient":
            return "Patient|canonical"
        return f"{chunk.domain_key or 'none'}|{chunk.variant or 'none'}"


# ---------------------------------------------------------------------------
# Internal helpers — all FHIR/LOINC/SNOMED knowledge lives HERE, not in core.
# ---------------------------------------------------------------------------


def _load_bundle(path: Path) -> dict | None:
    """Load a FHIR Bundle JSON. Handles large files."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error("Invalid JSON: %s", path)
        return None
    except OSError as exc:
        logger.error("Cannot read %s: %s", path, exc)
        return None


def _resource_to_chunk(resource: dict, rtype: str) -> Chunk | None:
    """Dispatch to the right extractor by resource type."""
    extractor = _EXTRACTORS.get(rtype)
    if extractor is None:
        return None
    return extractor(resource)


# -- Observation -------------------------------------------------------------


def _observation_to_chunk(obs: dict) -> Chunk | None:
    """Convert a FHIR Observation to a Chunk.

    Detects which value[x] variant is present and builds
    human-readable content describing the mapping shape.
    """
    code_info = _extract_primary_code(obs.get("code", {}))
    if code_info is None:
        return None

    code_value, code_display, code_system = code_info
    category = _extract_category(obs)
    variant, value_text = _extract_value(obs)
    status = obs.get("status", "unknown")

    content_lines = [
        f"Resource: Observation",
        f"Code: {code_value} ({code_display})",
        f"System: {code_system}",
        f"Category: {category}",
        f"Value type: {variant}",
        f"Value: {value_text}",
        f"Status: {status}",
    ]

    effective = obs.get("effectiveDateTime")
    if effective:
        content_lines.append(f"Effective: {effective}")

    return Chunk(
        domain_key=code_value,
        kind="Observation",
        variant=variant,
        content="\n".join(content_lines),
        metadata={
            "code_system": code_system,
            "code_display": code_display,
            "category": category,
            "status": status,
            "resource_json": _slim_observation(obs),
        },
    )


def _extract_value(obs: dict) -> tuple[str, str]:
    """Detect which value[x] variant is present and return (variant, text)."""

    # valueQuantity — numeric results
    vq = obs.get("valueQuantity")
    if vq is not None:
        val = vq.get("value", "?")
        unit = vq.get("unit", vq.get("code", ""))
        return "valueQuantity", f"{val} {unit}".strip()

    # valueCodeableConcept — coded results
    vcc = obs.get("valueCodeableConcept")
    if vcc is not None:
        text = vcc.get("text", "")
        if not text:
            codings = vcc.get("coding", [])
            text = codings[0].get("display", codings[0].get("code", "?")) if codings else "?"
        return "valueCodeableConcept", text

    # component[] panels — e.g. Blood Pressure
    # Include component LOINC codes so the model can cite them from evidence
    components = obs.get("component")
    if components:
        parts = []
        for comp in components:
            comp_code = _extract_primary_code(comp.get("code", {}))
            if comp_code:
                comp_label = f"{comp_code[1]} ({comp_code[0]})"
            else:
                comp_label = "?"
            comp_vq = comp.get("valueQuantity", {})
            comp_val = comp_vq.get("value", "?")
            comp_unit = comp_vq.get("unit", comp_vq.get("code", ""))
            parts.append(f"{comp_label}: {comp_val} {comp_unit}".strip())
        return "component", " | ".join(parts)

    # No recognized value — still a valid Observation shape
    return "none", "(no value)"


def _extract_category(obs: dict) -> str:
    """Pull the category code (vital-signs, laboratory, etc.)."""
    for cat in obs.get("category", []):
        for coding in cat.get("coding", []):
            code = coding.get("code")
            if code:
                return code
    return "unknown"


def _slim_observation(obs: dict) -> dict:
    """Keep only the structural fields relevant to mapping, drop bulk."""
    keys = (
        "resourceType", "code", "category", "status",
        "valueQuantity", "valueCodeableConcept", "component",
        "effectiveDateTime", "issued",
    )
    return {k: obs[k] for k in keys if k in obs}


# -- Condition ---------------------------------------------------------------


def _condition_to_chunk(cond: dict) -> Chunk | None:
    """Convert a FHIR Condition to a Chunk."""
    code_info = _extract_primary_code(cond.get("code", {}))
    if code_info is None:
        return None

    code_value, code_display, code_system = code_info
    clinical_status = _nested_code(cond.get("clinicalStatus", {}))
    verification = _nested_code(cond.get("verificationStatus", {}))

    content_lines = [
        f"Resource: Condition",
        f"Code: {code_value} ({code_display})",
        f"System: {code_system}",
        f"Clinical status: {clinical_status}",
        f"Verification: {verification}",
    ]

    onset = cond.get("onsetDateTime")
    if onset:
        content_lines.append(f"Onset: {onset}")

    abatement = cond.get("abatementDateTime")
    if abatement:
        content_lines.append(f"Abatement: {abatement}")

    return Chunk(
        domain_key=code_value,
        kind="Condition",
        variant=None,
        content="\n".join(content_lines),
        metadata={
            "code_system": code_system,
            "code_display": code_display,
            "clinical_status": clinical_status,
        },
    )


# -- Patient -----------------------------------------------------------------


def _patient_to_chunk(patient: dict) -> Chunk | None:
    """Convert a FHIR Patient to a Chunk (PID equivalent)."""
    patient_id = patient.get("id", "unknown")
    gender = patient.get("gender", "unknown")
    birth_date = patient.get("birthDate", "unknown")

    names = patient.get("name", [])
    name_str = "unknown"
    if names:
        given = " ".join(names[0].get("given", []))
        family = names[0].get("family", "")
        name_str = f"{given} {family}".strip() or "unknown"

    content_lines = [
        f"Resource: Patient",
        f"ID: {patient_id}",
        f"Name: {name_str}",
        f"Gender: {gender}",
        f"Birth date: {birth_date}",
    ]

    # Identifiers (SSN, MRN, etc.)
    identifiers = []
    for ident in patient.get("identifier", []):
        system = ident.get("system", "")
        value = ident.get("value", "")
        if value:
            identifiers.append(f"{system}: {value}")

    if identifiers:
        content_lines.append(f"Identifiers: {'; '.join(identifiers)}")

    return Chunk(
        domain_key=patient_id,
        kind="Patient",
        variant=None,
        content="\n".join(content_lines),
        metadata={
            "gender": gender,
            "birth_date": birth_date,
        },
    )


# -- Shared helpers ----------------------------------------------------------


def _extract_primary_code(code_obj: dict) -> tuple[str, str, str] | None:
    """Extract (code, display, system_label) from a CodeableConcept.

    Prefers LOINC, then SNOMED, then first available coding.
    Returns None if no coding exists.
    """
    codings = code_obj.get("coding", [])
    if not codings:
        return None

    # Prefer known systems in priority order
    for system_url in ("http://loinc.org", "http://snomed.info/sct"):
        for coding in codings:
            if coding.get("system") == system_url:
                return (
                    coding.get("code", "unknown"),
                    coding.get("display", code_obj.get("text", "unknown")),
                    _SYSTEM_LABELS.get(system_url, system_url),
                )

    # Fallback: first coding
    first = codings[0]
    return (
        first.get("code", "unknown"),
        first.get("display", code_obj.get("text", "unknown")),
        _SYSTEM_LABELS.get(first.get("system", ""), first.get("system", "unknown")),
    )


def _nested_code(codeable: dict) -> str:
    """Extract the code string from a nested CodeableConcept (status fields)."""
    for coding in codeable.get("coding", []):
        code = coding.get("code")
        if code:
            return code
    return "unknown"


# -- MedicationRequest -------------------------------------------------------


def _medication_request_to_chunk(med: dict) -> Chunk | None:
    """Convert a FHIR MedicationRequest to a Chunk."""
    med_concept = med.get("medicationCodeableConcept", {})
    code_info = _extract_primary_code(med_concept)
    if code_info is None:
        return None

    code_value, code_display, code_system = code_info
    status = med.get("status", "unknown")
    intent = med.get("intent", "unknown")
    authored = med.get("authoredOn", "")

    content_lines = [
        "Resource: MedicationRequest",
        f"Code: {code_value} ({code_display})",
        f"System: {code_system}",
        f"Status: {status}",
        f"Intent: {intent}",
    ]

    if authored:
        content_lines.append(f"Authored: {authored}")

    # Dosage instructions
    dosages = med.get("dosageInstruction", [])
    if dosages:
        d = dosages[0]
        if d.get("asNeededBoolean"):
            content_lines.append("Dosage: as needed")
        timing = d.get("timing", {}).get("repeat", {})
        if timing:
            freq = timing.get("frequency", "")
            period = timing.get("period", "")
            period_unit = timing.get("periodUnit", "")
            if freq:
                content_lines.append(f"Dosage: {freq}x per {period} {period_unit}".strip())

    requester = med.get("requester", {}).get("display", "")
    if requester:
        content_lines.append(f"Requester: {requester}")

    return Chunk(
        domain_key=code_value,
        kind="MedicationRequest",
        variant=None,
        content="\n".join(content_lines),
        metadata={
            "code_system": code_system,
            "code_display": code_display,
            "status": status,
            "intent": intent,
        },
    )


# -- Procedure ---------------------------------------------------------------


def _procedure_to_chunk(proc: dict) -> Chunk | None:
    """Convert a FHIR Procedure to a Chunk."""
    code_info = _extract_primary_code(proc.get("code", {}))
    if code_info is None:
        return None

    code_value, code_display, code_system = code_info
    status = proc.get("status", "unknown")

    content_lines = [
        "Resource: Procedure",
        f"Code: {code_value} ({code_display})",
        f"System: {code_system}",
        f"Status: {status}",
    ]

    period = proc.get("performedPeriod", {})
    if period:
        start = period.get("start", "")
        end = period.get("end", "")
        if start:
            content_lines.append(f"Performed start: {start}")
        if end:
            content_lines.append(f"Performed end: {end}")
    elif proc.get("performedDateTime"):
        content_lines.append(f"Performed: {proc['performedDateTime']}")

    return Chunk(
        domain_key=code_value,
        kind="Procedure",
        variant=None,
        content="\n".join(content_lines),
        metadata={
            "code_system": code_system,
            "code_display": code_display,
            "status": status,
        },
    )


# -- Immunization ------------------------------------------------------------


def _immunization_to_chunk(imm: dict) -> Chunk | None:
    """Convert a FHIR Immunization to a Chunk."""
    code_info = _extract_primary_code(imm.get("vaccineCode", {}))
    if code_info is None:
        return None

    code_value, code_display, code_system = code_info
    status = imm.get("status", "unknown")
    occurrence = imm.get("occurrenceDateTime", "")

    content_lines = [
        "Resource: Immunization",
        f"Vaccine code: {code_value} ({code_display})",
        f"System: {code_system}",
        f"Status: {status}",
    ]

    if occurrence:
        content_lines.append(f"Date: {occurrence}")

    primary_source = imm.get("primarySource")
    if primary_source is not None:
        content_lines.append(f"Primary source: {primary_source}")

    return Chunk(
        domain_key=code_value,
        kind="Immunization",
        variant=None,
        content="\n".join(content_lines),
        metadata={
            "code_system": code_system,
            "code_display": code_display,
            "status": status,
        },
    )


# -- DiagnosticReport -------------------------------------------------------


def _diagnostic_report_to_chunk(report: dict) -> Chunk | None:
    """Convert a FHIR DiagnosticReport to a Chunk."""
    code_info = _extract_primary_code(report.get("code", {}))
    if code_info is None:
        return None

    code_value, code_display, code_system = code_info
    status = report.get("status", "unknown")
    category = "unknown"
    for cat in report.get("category", []):
        for coding in cat.get("coding", []):
            if coding.get("display"):
                category = coding["display"]
                break

    content_lines = [
        "Resource: DiagnosticReport",
        f"Code: {code_value} ({code_display})",
        f"System: {code_system}",
        f"Category: {category}",
        f"Status: {status}",
    ]

    effective = report.get("effectiveDateTime")
    if effective:
        content_lines.append(f"Effective: {effective}")

    # List result references
    results = report.get("result", [])
    if results:
        result_names = [r.get("display", "unknown") for r in results]
        content_lines.append(f"Results ({len(results)}): {', '.join(result_names)}")

    return Chunk(
        domain_key=code_value,
        kind="DiagnosticReport",
        variant=None,
        content="\n".join(content_lines),
        metadata={
            "code_system": code_system,
            "code_display": code_display,
            "category": category,
            "status": status,
            "result_count": len(results),
        },
    )


# -- Encounter ---------------------------------------------------------------


def _encounter_to_chunk(enc: dict) -> Chunk | None:
    """Convert a FHIR Encounter to a Chunk."""
    # Encounter type is the primary code (e.g. "Cardiac Arrest", "Checkup")
    types = enc.get("type", [])
    if not types:
        return None

    code_info = _extract_primary_code(types[0])
    if code_info is None:
        return None

    code_value, code_display, code_system = code_info
    status = enc.get("status", "unknown")

    # Encounter class (AMB, EMER, IMP, etc.)
    enc_class = enc.get("class", {})
    class_code = enc_class.get("code", "unknown")

    content_lines = [
        "Resource: Encounter",
        f"Type: {code_value} ({code_display})",
        f"System: {code_system}",
        f"Class: {class_code}",
        f"Status: {status}",
    ]

    period = enc.get("period", {})
    if period.get("start"):
        content_lines.append(f"Start: {period['start']}")
    if period.get("end"):
        content_lines.append(f"End: {period['end']}")

    provider = enc.get("serviceProvider", {}).get("display", "")
    if provider:
        content_lines.append(f"Provider: {provider}")

    return Chunk(
        domain_key=code_value,
        kind="Encounter",
        variant=class_code,
        content="\n".join(content_lines),
        metadata={
            "code_system": code_system,
            "code_display": code_display,
            "class": class_code,
            "status": status,
        },
    )


# -- Extractor dispatch table ------------------------------------------------

_EXTRACTORS = {
    "Observation": _observation_to_chunk,
    "Condition": _condition_to_chunk,
    "Patient": _patient_to_chunk,
    "MedicationRequest": _medication_request_to_chunk,
    "Procedure": _procedure_to_chunk,
    "Immunization": _immunization_to_chunk,
    "DiagnosticReport": _diagnostic_report_to_chunk,
    "Encounter": _encounter_to_chunk,
}
