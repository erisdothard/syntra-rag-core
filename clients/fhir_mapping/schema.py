"""
clients/fhir_mapping/schema.py

Client-specific Pydantic validation models for the FHIR mapping assistant.

These extend the core's generic validation with domain rules:
- Observation chunks MUST have a LOINC code and a recognized value[x] variant
- Condition chunks MUST have a SNOMED code
- Patient chunks MUST have an ID

The core validates structure. This file validates domain correctness.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Valid value[x] variants for Observations in Synthea data
_VALID_VARIANTS = frozenset({"valueQuantity", "valueCodeableConcept", "component", "none"})

# Known code systems this client expects
_KNOWN_SYSTEMS = frozenset({"LOINC", "SNOMED"})


class ObservationChunkSchema(BaseModel):
    """Domain validation for an Observation chunk.

    Enforces that every Observation has a LOINC code and a recognized
    value[x] variant. Catches parser bugs early — before indexing.
    """

    domain_key: str = Field(description="LOINC code")
    kind: Literal["Observation"]
    variant: str
    content: str
    metadata: ObservationMetadata

    @field_validator("variant")
    @classmethod
    def valid_variant(cls, v: str) -> str:
        if v not in _VALID_VARIANTS:
            raise ValueError(
                f"Unknown value[x] variant '{v}'. Expected one of: {sorted(_VALID_VARIANTS)}"
            )
        return v


class ObservationMetadata(BaseModel):
    """Expected metadata shape for Observation chunks."""

    code_system: str
    code_display: str
    category: str
    status: str
    resource_json: dict

    @field_validator("code_system")
    @classmethod
    def system_is_loinc(cls, v: str) -> str:
        if v != "LOINC":
            raise ValueError(f"Observation code_system must be LOINC, got '{v}'")
        return v


class ConditionChunkSchema(BaseModel):
    """Domain validation for a Condition chunk.

    Enforces SNOMED coding.
    """

    domain_key: str = Field(description="SNOMED code")
    kind: Literal["Condition"]
    variant: None = None
    content: str
    metadata: ConditionMetadata


class ConditionMetadata(BaseModel):
    """Expected metadata shape for Condition chunks."""

    code_system: str
    code_display: str
    clinical_status: str

    @field_validator("code_system")
    @classmethod
    def system_is_snomed(cls, v: str) -> str:
        if v != "SNOMED":
            raise ValueError(f"Condition code_system must be SNOMED, got '{v}'")
        return v


class PatientChunkSchema(BaseModel):
    """Domain validation for a Patient chunk."""

    domain_key: str = Field(description="Patient ID")
    kind: Literal["Patient"]
    variant: None = None
    content: str
    metadata: PatientMetadata


class PatientMetadata(BaseModel):
    """Expected metadata shape for Patient chunks."""

    gender: str
    birth_date: str


# ---------------------------------------------------------------------------
# Dispatch — validate a chunk dict against the right domain schema
# ---------------------------------------------------------------------------

_SCHEMA_MAP = {
    "Observation": ObservationChunkSchema,
    "Condition": ConditionChunkSchema,
    "Patient": PatientChunkSchema,
}


def validate_domain_chunk(chunk_dict: dict) -> BaseModel:
    """Validate a chunk against its domain-specific schema.

    Args:
        chunk_dict: A dict with at least 'kind' to dispatch on.

    Returns:
        The validated Pydantic model instance.

    Raises:
        ValueError: If kind is unknown or validation fails.
    """
    kind = chunk_dict.get("kind")
    schema_cls = _SCHEMA_MAP.get(kind)  # type: ignore[arg-type]
    if schema_cls is None:
        raise ValueError(f"No domain schema for kind '{kind}'")
    return schema_cls(**chunk_dict)
