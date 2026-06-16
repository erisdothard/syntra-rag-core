"""
Tests for core neutrality — automated grep ensuring no domain terms leaked into core/.

The core directory must contain ZERO domain-specific terms. Any hit is a leak.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

CORE_DIR = Path(__file__).parent.parent / "core"

# Domain terms that must NEVER appear in core/
_DOMAIN_TERMS = [
    "loinc",
    "snomed",
    "fhir",
    "hl7",
    "observation",
]


class TestCoreNeutrality:
    """Grep core/ for domain terms. Any match is a failure."""

    def test_no_domain_terms_in_core(self):
        """Run case-insensitive grep for each domain term in core/."""
        pattern = "|".join(_DOMAIN_TERMS)
        result = subprocess.run(
            ["grep", "-ri", "-E", pattern, str(CORE_DIR)],
            capture_output=True,
            text=True,
        )
        # grep exit code 1 = no matches (good), 0 = matches found (bad)
        if result.returncode == 0:
            pytest.fail(
                f"Domain terms leaked into core/:\n{result.stdout}"
            )

    def test_each_term_individually(self):
        """Check each term separately for clearer error messages."""
        for term in _DOMAIN_TERMS:
            result = subprocess.run(
                ["grep", "-ri", term, str(CORE_DIR)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                pytest.fail(
                    f"Domain term '{term}' found in core/:\n{result.stdout}"
                )
