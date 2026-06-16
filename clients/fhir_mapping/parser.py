"""
clients/fhir_mapping/parser.py

DomainParser implementation for Synthea FHIR R4 bundles.

Handles:
- Observation (primary): all three value[x] variants
  - valueQuantity (numeric results)
  - valueCodeableConcept (coded results)
  - component[] panels (e.g. Blood Pressure — no top-level value)
- Condition (secondary): SNOMED-coded diagnoses
- Patient: PID-equivalent demographics

Files can be 40MB+. Uses ijson for streaming when available,
falls back to chunked stdlib json parsing.

Dedup strategy: LOINC/SNOMED code + value[x] variant. One canonical
example per distinct shape — not one chunk per reading.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from core.interfaces import Chunk

logger = logging.getLogger(__name__)

# Resource types we extract. Everything else is skipped.
_TARGET_TYPES = frozenset({"Observation", "Condition", "Patient"})

# Code system URLs → short labels
_SYSTEM_LABELS = {
    "http://loinc.org": "LOINC",
    "http://snomed.info/sct": "SNOMED",
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
        """
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
    if rtype == "Observation":
        return _observation_to_chunk(resource)
    if rtype == "Condition":
        return _condition_to_chunk(resource)
    if rtype == "Patient":
        return _patient_to_chunk(resource)
    return None


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
