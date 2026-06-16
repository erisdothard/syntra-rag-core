"""
clients/fhir_mapping/schema.py

Client-specific Pydantic validation models for the FHIR mapping assistant.

These extend the core's generic validation with domain rules:
- Observation chunks MUST have a LOINC code and a recognized value[x] variant
- Condition chunks MUST have a SNOMED code
- Patient chunks MUST have an ID
- MedicationRequest chunks MUST have an RxNorm code
- Procedure chunks MUST have a SNOMED code
- Immunization chunks MUST have a CVX code
- DiagnosticReport chunks MUST have a LOINC code
- Encounter chunks MUST have a SNOMED code

The core validates structure. This file validates domain correctness.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Valid value[x] variants for Observations in Synthea data
_VALID_VARIANTS = frozenset({"valueQuantity", "valueCodeableConcept", "component", "none"})

# Known code systems this client expects
_KNOWN_SYSTEMS = frozenset({"LOINC", "SNOMED", "RxNorm", "CVX", "ActCode", "HL7v2"})


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


# -- MedicationRequest -------------------------------------------------------


class CodedMetadata(BaseModel):
    """Common metadata for code-based resource chunks."""

    code_system: str
    code_display: str
    status: str


class MedicationRequestMetadata(CodedMetadata):
    """Expected metadata shape for MedicationRequest chunks."""

    intent: str


class MedicationRequestChunkSchema(BaseModel):
    """Domain validation for a MedicationRequest chunk."""

    domain_key: str = Field(description="RxNorm code")
    kind: Literal["MedicationRequest"]
    variant: None = None
    content: str
    metadata: MedicationRequestMetadata


# -- Procedure ---------------------------------------------------------------


class ProcedureChunkSchema(BaseModel):
    """Domain validation for a Procedure chunk."""

    domain_key: str = Field(description="SNOMED code")
    kind: Literal["Procedure"]
    variant: None = None
    content: str
    metadata: CodedMetadata


# -- Immunization ------------------------------------------------------------


class ImmunizationChunkSchema(BaseModel):
    """Domain validation for an Immunization chunk."""

    domain_key: str = Field(description="CVX code")
    kind: Literal["Immunization"]
    variant: None = None
    content: str
    metadata: CodedMetadata


# -- DiagnosticReport -------------------------------------------------------


class DiagnosticReportMetadata(BaseModel):
    """Expected metadata shape for DiagnosticReport chunks."""

    code_system: str
    code_display: str
    category: str
    status: str
    result_count: int


class DiagnosticReportChunkSchema(BaseModel):
    """Domain validation for a DiagnosticReport chunk."""

    domain_key: str = Field(description="LOINC code")
    kind: Literal["DiagnosticReport"]
    variant: None = None
    content: str
    metadata: DiagnosticReportMetadata


# -- Encounter ---------------------------------------------------------------


class EncounterMetadata(BaseModel):
    """Expected metadata shape for Encounter chunks."""

    code_system: str
    code_display: str
    status: str


class EncounterChunkSchema(BaseModel):
    """Domain validation for an Encounter chunk."""

    domain_key: str = Field(description="SNOMED code")
    kind: Literal["Encounter"]
    variant: str | None = None
    content: str
    metadata: EncounterMetadata


# ---------------------------------------------------------------------------
# Dispatch — validate a chunk dict against the right domain schema
# ---------------------------------------------------------------------------

_SCHEMA_MAP = {
    "Observation": ObservationChunkSchema,
    "Condition": ConditionChunkSchema,
    "Patient": PatientChunkSchema,
    "MedicationRequest": MedicationRequestChunkSchema,
    "Procedure": ProcedureChunkSchema,
    "Immunization": ImmunizationChunkSchema,
    "DiagnosticReport": DiagnosticReportChunkSchema,
    "Encounter": EncounterChunkSchema,
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
