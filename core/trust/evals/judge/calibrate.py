"""
core/trust/evals/judge/calibrate.py

Calibration: check LLM judge scores against human-labeled gold sets.

The gold set is the source of truth. If the judge drifts from human labels
(e.g. after a model update or prompt change), calibration catches it before
bad scores reach production.

Metrics:
  - Agreement rate: % of cases where judge score is within ±1 of human label
  - Mean absolute error: average distance between judge and human scores
  - Drift flag: true if agreement drops below the client's threshold

Build order: Step 5.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.trust.evals.judge.rubrics import judge

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoldCase:
    """A single human-labeled evaluation case."""

    question: str
    answer: str
    evidence_chunks: list[str]
    human_faithfulness: int  # 1-5
    human_relevance: int  # 1-5


@dataclass(frozen=True)
class CalibrationResult:
    """Output of a calibration run."""

    total_cases: int
    agreement_rate: float  # 0.0 - 1.0 (within ±1 tolerance)
    mean_absolute_error: float
    drifted: bool  # agreement_rate < threshold
    per_case: list[CaseComparison]


@dataclass(frozen=True)
class CaseComparison:
    """Judge vs human for a single gold case."""

    question: str
    human_faithfulness: int
    judge_faithfulness: int
    human_relevance: int
    judge_relevance: int
    faithfulness_delta: int
    relevance_delta: int
    within_tolerance: bool


def load_gold_set(gold_dir: str | Path) -> list[GoldCase]:
    """Load gold cases from a directory of JSON files.

    Expected format per file:
    {
        "question": "...",
        "answer": "...",
        "evidence_chunks": ["...", "..."],
        "human_faithfulness": 4,
        "human_relevance": 5
    }

    Also supports a single file containing a JSON array of cases.
    """
    gold_dir = Path(gold_dir)
    cases: list[GoldCase] = []

    if not gold_dir.exists():
        logger.warning("Gold set directory does not exist: %s", gold_dir)
        return cases

    for path in sorted(gold_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else [raw]
            for item in items:
                cases.append(GoldCase(
                    question=item["question"],
                    answer=item["answer"],
                    evidence_chunks=item["evidence_chunks"],
                    human_faithfulness=item["human_faithfulness"],
                    human_relevance=item["human_relevance"],
                ))
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.exception("Failed to parse gold case: %s", path)

    logger.info("Loaded %d gold cases from %s", len(cases), gold_dir)
    return cases


async def calibrate(
    *,
    gold_cases: list[GoldCase],
    model: str,
    faithfulness_threshold: int = 3,
    relevance_threshold: int = 3,
    agreement_threshold: float = 0.8,
    tolerance: int = 1,
) -> CalibrationResult:
    """Run the judge on every gold case and compare against human labels.

    Args:
        gold_cases:              Human-labeled cases to calibrate against.
        model:                   Anthropic model ID for the judge.
        faithfulness_threshold:  Passed to the judge.
        relevance_threshold:     Passed to the judge.
        agreement_threshold:     Minimum agreement rate before flagging drift.
        tolerance:               Max score distance (±) to count as agreement.

    Returns:
        CalibrationResult with per-case comparisons and drift flag.
    """
    if not gold_cases:
        logger.warning("No gold cases provided — cannot calibrate")
        return CalibrationResult(
            total_cases=0,
            agreement_rate=0.0,
            mean_absolute_error=0.0,
            drifted=True,
            per_case=[],
        )

    comparisons: list[CaseComparison] = []

    for case in gold_cases:
        result = await judge(
            question=case.question,
            answer=case.answer,
            evidence_chunks=case.evidence_chunks,
            model=model,
            faithfulness_threshold=faithfulness_threshold,
            relevance_threshold=relevance_threshold,
        )

        f_delta = abs(result.faithfulness.score - case.human_faithfulness)
        r_delta = abs(result.relevance.score - case.human_relevance)

        comparisons.append(CaseComparison(
            question=case.question,
            human_faithfulness=case.human_faithfulness,
            judge_faithfulness=result.faithfulness.score,
            human_relevance=case.human_relevance,
            judge_relevance=result.relevance.score,
            faithfulness_delta=f_delta,
            relevance_delta=r_delta,
            within_tolerance=f_delta <= tolerance and r_delta <= tolerance,
        ))

    agreed = sum(1 for c in comparisons if c.within_tolerance)
    total_error = sum(c.faithfulness_delta + c.relevance_delta for c in comparisons)
    n = len(comparisons)

    agreement_rate = agreed / n
    mae = total_error / (n * 2)  # two dimensions per case

    drifted = agreement_rate < agreement_threshold

    if drifted:
        logger.warning(
            "Judge drift detected: agreement=%.2f (threshold=%.2f), MAE=%.2f",
            agreement_rate,
            agreement_threshold,
            mae,
        )
    else:
        logger.info(
            "Calibration passed: agreement=%.2f, MAE=%.2f",
            agreement_rate,
            mae,
        )

    return CalibrationResult(
        total_cases=n,
        agreement_rate=agreement_rate,
        mean_absolute_error=mae,
        drifted=drifted,
        per_case=comparisons,
    )
