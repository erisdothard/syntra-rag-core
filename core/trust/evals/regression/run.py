"""
core/trust/evals/regression/run.py

Regression harness: runs deterministic + judge evaluations on every change.

Two eval modes:
  1. Deterministic — exact-match checks on gold set answers (fast, free).
     Catches regressions from chunking, retrieval, or prompt changes.
  2. Judge — rubric-based LLM scoring (slow, costs tokens).
     Catches quality drift that deterministic checks miss.

Loads gold sets from the client's gold_sets/ directory.
The harness is generic — it doesn't know what domain the gold cases cover.

Build order: Step 5.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

from core.trust.evals.judge.calibrate import CalibrationResult, GoldCase, load_gold_set, calibrate
from core.trust.evals.judge.rubrics import JudgeResult, judge

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeterministicCase:
    """A gold case with expected substrings or exact outputs for fast checking."""

    question: str
    expected_substrings: list[str]  # answer must contain all of these
    blocked_substrings: list[str]  # answer must contain none of these


@dataclass(frozen=True)
class DeterministicResult:
    """Result of a single deterministic check."""

    question: str
    passed: bool
    missing: list[str]  # expected substrings not found
    blocked_found: list[str]  # blocked substrings that appeared


@dataclass(frozen=True)
class RegressionReport:
    """Full regression run output."""

    timestamp: float
    deterministic_total: int
    deterministic_passed: int
    judge_total: int
    judge_passed: int
    calibration: CalibrationResult | None
    deterministic_results: list[DeterministicResult]
    judge_results: list[JudgeResult]
    all_passed: bool


def load_deterministic_cases(gold_dir: str | Path) -> list[DeterministicCase]:
    """Load deterministic regression cases from gold_sets/deterministic.json.

    Expected format:
    [
        {
            "question": "...",
            "expected_substrings": ["some_code", "12345"],
            "blocked_substrings": ["I don't know"]
        }
    ]
    """
    path = Path(gold_dir) / "deterministic.json"
    if not path.exists():
        logger.info("No deterministic cases found at %s", path)
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cases = [
            DeterministicCase(
                question=item["question"],
                expected_substrings=item.get("expected_substrings", []),
                blocked_substrings=item.get("blocked_substrings", []),
            )
            for item in raw
        ]
        logger.info("Loaded %d deterministic cases", len(cases))
        return cases
    except (json.JSONDecodeError, KeyError):
        logger.exception("Failed to parse deterministic cases from %s", path)
        return []


def run_deterministic(
    cases: list[DeterministicCase],
    answer_fn: Callable[[str], str],
) -> list[DeterministicResult]:
    """Run deterministic checks: expected substrings present, blocked absent.

    Args:
        cases:     Deterministic gold cases.
        answer_fn: Synchronous function that takes a question and returns an answer.
                   This is the pipeline under test.
    """
    results: list[DeterministicResult] = []

    for case in cases:
        answer = answer_fn(case.question)
        answer_lower = answer.lower()

        missing = [s for s in case.expected_substrings if s.lower() not in answer_lower]
        blocked_found = [s for s in case.blocked_substrings if s.lower() in answer_lower]
        passed = len(missing) == 0 and len(blocked_found) == 0

        results.append(DeterministicResult(
            question=case.question,
            passed=passed,
            missing=missing,
            blocked_found=blocked_found,
        ))

    return results


async def run_judge_eval(
    gold_cases: list[GoldCase],
    answer_fn: Callable[[str], str],
    evidence_fn: Callable[[str], list[str]],
    model: str,
    faithfulness_threshold: int = 3,
    relevance_threshold: int = 3,
) -> list[JudgeResult]:
    """Run judge evaluation on gold cases using the live pipeline.

    Args:
        gold_cases:    Human-labeled cases (question + evidence + human scores).
        answer_fn:     Synchronous function: question → answer (pipeline under test).
        evidence_fn:   Synchronous function: question → list of evidence chunk strings.
        model:         Anthropic model ID for the judge.
    """
    results: list[JudgeResult] = []

    for case in gold_cases:
        # Get live pipeline output
        answer = answer_fn(case.question)
        evidence = evidence_fn(case.question)

        result = await judge(
            question=case.question,
            answer=answer,
            evidence_chunks=evidence,
            model=model,
            faithfulness_threshold=faithfulness_threshold,
            relevance_threshold=relevance_threshold,
        )
        results.append(result)

    return results


async def run_regression(
    *,
    gold_dir: str | Path,
    answer_fn: Callable[[str], str],
    evidence_fn: Callable[[str], list[str]],
    judge_model: str,
    faithfulness_threshold: int = 3,
    relevance_threshold: int = 3,
    agreement_threshold: float = 0.8,
    run_calibration: bool = True,
) -> RegressionReport:
    """Full regression run: deterministic + judge + optional calibration.

    Args:
        gold_dir:               Path to the client's gold_sets/ directory.
        answer_fn:              Pipeline under test: question → answer.
        evidence_fn:            Pipeline under test: question → evidence chunks.
        judge_model:            Anthropic model ID for judging.
        run_calibration:        Whether to also run judge calibration against gold labels.

    Returns:
        RegressionReport with all results and an overall pass/fail.
    """
    start = time.time()

    # Deterministic
    det_cases = load_deterministic_cases(gold_dir)
    det_results = run_deterministic(det_cases, answer_fn) if det_cases else []
    det_passed = sum(1 for r in det_results if r.passed)

    # Judge
    gold_cases = load_gold_set(gold_dir)
    judge_results = await run_judge_eval(
        gold_cases=gold_cases,
        answer_fn=answer_fn,
        evidence_fn=evidence_fn,
        model=judge_model,
        faithfulness_threshold=faithfulness_threshold,
        relevance_threshold=relevance_threshold,
    ) if gold_cases else []
    judge_passed = sum(1 for r in judge_results if r.passed)

    # Calibration
    cal_result = None
    if run_calibration and gold_cases:
        cal_result = await calibrate(
            gold_cases=gold_cases,
            model=judge_model,
            faithfulness_threshold=faithfulness_threshold,
            relevance_threshold=relevance_threshold,
            agreement_threshold=agreement_threshold,
        )

    all_passed = (
        det_passed == len(det_results)
        and judge_passed == len(judge_results)
        and (cal_result is None or not cal_result.drifted)
    )

    report = RegressionReport(
        timestamp=start,
        deterministic_total=len(det_results),
        deterministic_passed=det_passed,
        judge_total=len(judge_results),
        judge_passed=judge_passed,
        calibration=cal_result,
        deterministic_results=det_results,
        judge_results=judge_results,
        all_passed=all_passed,
    )

    if all_passed:
        logger.info(
            "Regression PASSED: %d/%d deterministic, %d/%d judge",
            det_passed, len(det_results), judge_passed, len(judge_results),
        )
    else:
        logger.warning(
            "Regression FAILED: %d/%d deterministic, %d/%d judge, drift=%s",
            det_passed, len(det_results),
            judge_passed, len(judge_results),
            cal_result.drifted if cal_result else "n/a",
        )

    return report
