"""
Tests for clients/fhir_mapping/parser.py — FHIR DomainParser implementation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from clients.fhir_mapping.parser import FHIRParser
from core.interfaces import Chunk


@pytest.fixture
def parser() -> FHIRParser:
    return FHIRParser()


@pytest.fixture
def sample_bundle_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_bundle.json"


class TestFHIRParserParse:
    """FHIRParser.parse() with the fixture bundle."""

    def test_yields_correct_chunk_count(self, parser: FHIRParser, sample_bundle_path: Path):
        chunks = list(parser.parse(str(sample_bundle_path)))
        # 1 Patient + 3 Observations + 1 Condition = 5
        assert len(chunks) == 5

    def test_patient_chunk_extracted(self, parser: FHIRParser, sample_bundle_path: Path):
        chunks = list(parser.parse(str(sample_bundle_path)))
        patients = [c for c in chunks if c.kind == "Patient"]
        assert len(patients) == 1
        assert patients[0].domain_key == "test-patient-001"
        assert "John Doe" in patients[0].content

    def test_condition_chunk_extracted(self, parser: FHIRParser, sample_bundle_path: Path):
        chunks = list(parser.parse(str(sample_bundle_path)))
        conditions = [c for c in chunks if c.kind == "Condition"]
        assert len(conditions) == 1
        assert conditions[0].domain_key == "44054006"
        assert "Type 2 diabetes" in conditions[0].content

    def test_observation_chunks_extracted(self, parser: FHIRParser, sample_bundle_path: Path):
        chunks = list(parser.parse(str(sample_bundle_path)))
        observations = [c for c in chunks if c.kind == "Observation"]
        assert len(observations) == 3


class TestValueXVariants:
    """All three value[x] variants detected correctly."""

    def test_value_quantity_detected(self, parser: FHIRParser, sample_bundle_path: Path):
        chunks = list(parser.parse(str(sample_bundle_path)))
        height = [c for c in chunks if c.domain_key == "8302-2"]
        assert len(height) == 1
        assert height[0].variant == "valueQuantity"
        assert "175.5" in height[0].content
        assert "cm" in height[0].content

    def test_value_codeable_concept_detected(self, parser: FHIRParser, sample_bundle_path: Path):
        chunks = list(parser.parse(str(sample_bundle_path)))
        tobacco = [c for c in chunks if c.domain_key == "72166-2"]
        assert len(tobacco) == 1
        assert tobacco[0].variant == "valueCodeableConcept"
        assert "Never smoker" in tobacco[0].content

    def test_component_detected(self, parser: FHIRParser, sample_bundle_path: Path):
        chunks = list(parser.parse(str(sample_bundle_path)))
        bp = [c for c in chunks if c.domain_key == "85354-9"]
        assert len(bp) == 1
        assert bp[0].variant == "component"


class TestComponentChunks:
    """Component chunks include LOINC codes in content text."""

    def test_component_content_includes_loinc_codes(
        self, parser: FHIRParser, sample_bundle_path: Path
    ):
        chunks = list(parser.parse(str(sample_bundle_path)))
        bp = [c for c in chunks if c.domain_key == "85354-9"][0]
        # Component LOINC codes must be in the content for the model to cite them
        assert "8462-4" in bp.content  # Diastolic
        assert "8480-6" in bp.content  # Systolic

    def test_component_content_includes_values(
        self, parser: FHIRParser, sample_bundle_path: Path
    ):
        chunks = list(parser.parse(str(sample_bundle_path)))
        bp = [c for c in chunks if c.domain_key == "85354-9"][0]
        assert "80" in bp.content  # Diastolic value
        assert "120" in bp.content  # Systolic value


class TestDedupKey:
    """dedup_key format is 'domain_key|variant'."""

    def test_dedup_key_format(self, parser: FHIRParser, sample_chunk: Chunk):
        key = parser.dedup_key(sample_chunk)
        assert key == "CODE-001|test_variant"

    def test_dedup_key_with_none_values(self, parser: FHIRParser):
        chunk = Chunk(domain_key=None, kind="Test", variant=None, content="content")
        key = parser.dedup_key(chunk)
        assert key == "none|none"

    def test_dedup_key_with_none_variant(self, parser: FHIRParser):
        chunk = Chunk(domain_key="KEY-1", kind="Test", variant=None, content="content")
        key = parser.dedup_key(chunk)
        assert key == "KEY-1|none"


class TestEdgeCases:
    """Edge cases: missing files, invalid JSON, empty bundles."""

    def test_missing_file_returns_empty(self, parser: FHIRParser):
        chunks = list(parser.parse("/nonexistent/path/file.json"))
        assert chunks == []

    def test_invalid_json_returns_empty(self, parser: FHIRParser, tmp_path: Path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")
        chunks = list(parser.parse(str(bad_file)))
        assert chunks == []

    def test_empty_bundle_returns_empty(self, parser: FHIRParser, tmp_path: Path):
        empty_bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
        path = tmp_path / "empty.json"
        path.write_text(json.dumps(empty_bundle), encoding="utf-8")
        chunks = list(parser.parse(str(path)))
        assert chunks == []

    def test_bundle_with_unknown_resource_types_skipped(
        self, parser: FHIRParser, tmp_path: Path
    ):
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Medication",
                        "id": "med-001",
                    }
                }
            ],
        }
        path = tmp_path / "meds.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        chunks = list(parser.parse(str(path)))
        assert chunks == []
