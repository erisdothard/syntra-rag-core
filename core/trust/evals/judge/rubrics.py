"""
core/trust/evals/judge/rubrics.py

Rubric-based LLM-as-judge scoring. Industry-neutral.

Two dimensions, each scored 1-5 against retrieved evidence:
  - Faithfulness: does the answer only use information present in the chunks?
  - Relevance:    does the answer actually address the question asked?

The judge never grades its own confidence. It scores against *evidence* with
an explicit rubric. The model used for judging is set in client config.

Build order: Step 5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rubric definitions — the judge prompt references these levels explicitly
# ---------------------------------------------------------------------------

_FAITHFULNESS_RUBRIC = """
Score the FAITHFULNESS of the answer on a 1-5 scale.
Faithfulness = the answer ONLY uses information present in the provided evidence chunks.

1 — The answer fabricates claims with no basis in the evidence.
2 — The answer mixes some evidence-based claims with unsupported statements.
3 — The answer mostly uses the evidence but includes minor unsupported inferences.
4 — The answer is grounded in the evidence with only trivial extrapolations.
5 — Every claim in the answer is directly supported by the evidence.

Evidence chunks:
{evidence}

Question: {question}
Answer: {answer}

Respond with ONLY a JSON object: {{"score": <int>, "reasoning": "<1-2 sentences>"}}
""".strip()

_RELEVANCE_RUBRIC = """
Score the RELEVANCE of the answer on a 1-5 scale.
Relevance = the answer directly addresses the question that was asked.

1 — The answer is completely off-topic or addresses a different question.
2 — The answer is tangentially related but misses the core question.
3 — The answer partially addresses the question but omits key aspects.
4 — The answer addresses the question well with minor gaps.
5 — The answer directly and completely addresses the question.

Question: {question}
Answer: {answer}

Respond with ONLY a JSON object: {{"score": <int>, "reasoning": "<1-2 sentences>"}}
""".strip()


@dataclass(frozen=True)
class JudgeScore:
    """A single rubric score from the LLM judge."""

    dimension: str  # "faithfulness" or "relevance"
    score: int  # 1-5
    reasoning: str
    passed: bool  # score >= threshold


@dataclass(frozen=True)
class JudgeResult:
    """Combined judge output for a single query-answer pair."""

    faithfulness: JudgeScore
    relevance: JudgeScore
    passed: bool  # both dimensions passed


async def judge(
    *,
    question: str,
    answer: str,
    evidence_chunks: list[str],
    model: str,
    faithfulness_threshold: int = 3,
    relevance_threshold: int = 3,
) -> JudgeResult:
    """Run both rubric evaluations on a query-answer pair.

    Args:
        question:               The original user question.
        answer:                 The generated answer.
        evidence_chunks:        List of chunk content strings used as evidence.
        model:                  Anthropic model ID for the judge.
        faithfulness_threshold: Minimum passing score for faithfulness.
        relevance_threshold:    Minimum passing score for relevance.

    Returns:
        JudgeResult with both scores and an overall pass/fail.
    """
    evidence_text = "\n---\n".join(evidence_chunks)

    faithfulness = await _score_rubric(
        rubric_template=_FAITHFULNESS_RUBRIC,
        dimension="faithfulness",
        question=question,
        answer=answer,
        evidence=evidence_text,
        model=model,
        threshold=faithfulness_threshold,
    )

    relevance = await _score_rubric(
        rubric_template=_RELEVANCE_RUBRIC,
        dimension="relevance",
        question=question,
        answer=answer,
        evidence="",  # relevance doesn't need evidence
        model=model,
        threshold=relevance_threshold,
    )

    return JudgeResult(
        faithfulness=faithfulness,
        relevance=relevance,
        passed=faithfulness.passed and relevance.passed,
    )


async def _score_rubric(
    *,
    rubric_template: str,
    dimension: str,
    question: str,
    answer: str,
    evidence: str,
    model: str,
    threshold: int,
) -> JudgeScore:
    """Send a single rubric prompt to the judge model and parse the score."""
    prompt = rubric_template.format(
        question=question,
        answer=answer,
        evidence=evidence,
    )

    client = anthropic.AsyncAnthropic()

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=256,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        parsed = _parse_judge_response(raw)
        score = parsed["score"]
        reasoning = parsed["reasoning"]

    except Exception:
        logger.exception("Judge call failed for dimension=%s", dimension)
        # Fail safe: score 1 so the answer gets flagged
        score = 1
        reasoning = "Judge call failed — flagged for manual review"

    return JudgeScore(
        dimension=dimension,
        score=score,
        reasoning=reasoning,
        passed=score >= threshold,
    )


def _parse_judge_response(raw: str) -> dict[str, Any]:
    """Parse the judge's JSON response. Tolerant of minor formatting issues."""
    import json

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Drop first and last lines (fences)
        cleaned = "\n".join(lines[1:-1]).strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Judge returned unparseable response: %s", raw[:200])
        return {"score": 1, "reasoning": "Unparseable judge response — flagged"}

    score = result.get("score", 1)
    if not isinstance(score, int) or score < 1 or score > 5:
        score = 1

    return {
        "score": score,
        "reasoning": result.get("reasoning", "No reasoning provided"),
    }
