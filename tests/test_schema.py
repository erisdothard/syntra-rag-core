"""
Tests for clients/fhir_mapping/schema.py — domain-specific validation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clients.fhir_mapping.schema import (
    ConditionChunkSchema,
    ObservationChunkSchema,
    PatientChunkSchema,
    validate_domain_chunk,
)


def _observation_dict(**overrides) -> dict:
    """Build a valid observation chunk dict with optional overrides."""
    base = {
        "domain_key": "8302-2",
        "kind": "Observation",
        "variant": "valueQuantity",
        "content": "Resource: Observation\nCode: 8302-2 (Body Height)",
        "metadata": {
            "code_system": "LOINC",
            "code_display": "Body Height",
            "category": "vital-signs",
            "status": "final",
            "resource_json": {"resourceType": "Observation"},
        },
    }
    base.update(overrides)
    return base


def _condition_dict(**overrides) -> dict:
    """Build a valid condition chunk dict with optional overrides."""
    base = {
        "domain_key": "44054006",
        "kind": "Condition",
        "variant": None,
        "content": "Resource: Condition\nCode: 44054006 (Diabetes)",
        "metadata": {
            "code_system": "SNOMED",
            "code_display": "Diabetes",
            "clinical_status": "active",
        },
    }
    base.update(overrides)
    return base


def _patient_dict(**overrides) -> dict:
    """Build a valid patient chunk dict with optional overrides."""
    base = {
        "domain_key": "patient-001",
        "kind": "Patient",
        "variant": None,
        "content": "Resource: Patient\nID: patient-001",
        "metadata": {
            "gender": "male",
            "birth_date": "1990-01-01",
        },
    }
    base.update(overrides)
    return base


class TestObservationChunkSchema:
    """ObservationChunkSchema domain validation."""

    def test_validates_good_observation(self):
        result = ObservationChunkSchema(**_observation_dict())
        assert result.domain_key == "8302-2"
        assert result.variant == "valueQuantity"

    def test_rejects_invalid_variant(self):
        with pytest.raises(ValidationError, match="variant"):
            ObservationChunkSchema(**_observation_dict(variant="invalidType"))

    def test_accepts_all_valid_variants(self):
        for variant in ("valueQuantity", "valueCodeableConcept", "component", "none"):
            result = ObservationChunkSchema(**_observation_dict(variant=variant))
            assert result.variant == variant

    def test_rejects_non_loinc_system(self):
        bad_meta = {
            "code_system": "SNOMED",
            "code_display": "Test",
            "category": "vital-signs",
            "status": "final",
            "resource_json": {},
        }
        with pytest.raises(ValidationError, match="LOINC"):
            ObservationChunkSchema(**_observation_dict(metadata=bad_meta))


class TestConditionChunkSchema:
    """ConditionChunkSchema domain validation."""

    def test_validates_good_condition(self):
        result = ConditionChunkSchema(**_condition_dict())
        assert result.domain_key == "44054006"
        assert result.kind == "Condition"

    def test_rejects_non_snomed_system(self):
        bad_meta = {
            "code_system": "LOINC",
            "code_display": "Test",
            "clinical_status": "active",
        }
        with pytest.raises(ValidationError, match="SNOMED"):
            ConditionChunkSchema(**_condition_dict(metadata=bad_meta))


class TestPatientChunkSchema:
    """PatientChunkSchema domain validation."""

    def test_validates_good_patient(self):
        result = PatientChunkSchema(**_patient_dict())
        assert result.domain_key == "patient-001"
        assert result.kind == "Patient"

    def test_requires_gender_in_metadata(self):
        bad_meta = {"birth_date": "1990-01-01"}
        with pytest.raises(ValidationError):
            PatientChunkSchema(**_patient_dict(metadata=bad_meta))


class TestValidateDomainChunk:
    """validate_domain_chunk dispatches to the right schema."""

    def test_dispatches_observation(self):
        result = validate_domain_chunk(_observation_dict())
        assert isinstance(result, ObservationChunkSchema)

    def test_dispatches_condition(self):
        result = validate_domain_chunk(_condition_dict())
        assert isinstance(result, ConditionChunkSchema)

    def test_dispatches_patient(self):
        result = validate_domain_chunk(_patient_dict())
        assert isinstance(result, PatientChunkSchema)

    def test_rejects_unknown_kind(self):
        with pytest.raises(ValueError, match="No domain schema"):
            validate_domain_chunk({"kind": "UnknownType", "content": "test"})

    def test_rejects_missing_kind(self):
        with pytest.raises(ValueError, match="No domain schema"):
            validate_domain_chunk({"content": "test"})
