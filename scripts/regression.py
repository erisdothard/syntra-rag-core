"""
Regression harness runner for a client.

Usage:
    python scripts/regression.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import yaml
from core.query.orchestrate import ask
from core.trust.evals.regression.run import run_regression

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    import os
    config_path = os.environ.get("RAG_CLIENT_CONFIG", "")
    if not config_path:
        logger.error("RAG_CLIENT_CONFIG not set")
        sys.exit(1)

    # Load client config for gold_sets_dir and judge model
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    gold_dir = config.get("eval", {}).get("gold_sets_dir", "")
    if not gold_dir:
        logger.error("eval.gold_sets_dir not set in config")
        sys.exit(1)

    judge_model = config.get("judging", {}).get("model", "claude-haiku-4-5-20251001")
    f_threshold = config.get("judging", {}).get("faithfulness", {}).get("threshold", 3)
    r_threshold = config.get("judging", {}).get("relevance", {}).get("threshold", 3)

    # Pipeline functions — run the real orchestrator
    cache: dict[str, dict] = {}

    async def _ask(question: str) -> dict:
        if question not in cache:
            result = await ask(question, config_path=config_path)
            cache[question] = {
                "answer": result.generation.answer,
                "evidence": [c.get("content", "") for c in result.generation.chunks_used],
            }
        return cache[question]

    def answer_fn(question: str) -> str:
        result = asyncio.get_event_loop().run_until_complete(_ask(question))
        return result["answer"]

    def evidence_fn(question: str) -> list[str]:
        result = asyncio.get_event_loop().run_until_complete(_ask(question))
        return result["evidence"]

    report = await run_regression(
        gold_dir=gold_dir,
        answer_fn=answer_fn,
        evidence_fn=evidence_fn,
        judge_model=judge_model,
        faithfulness_threshold=f_threshold,
        relevance_threshold=r_threshold,
    )

    # Print summary
    print()
    print("=" * 60)
    print(f"REGRESSION {'PASSED' if report.all_passed else 'FAILED'}")
    print(f"  Deterministic: {report.deterministic_passed}/{report.deterministic_total}")
    print(f"  Judge:         {report.judge_passed}/{report.judge_total}")
    if report.calibration:
        print(f"  Calibration:   agreement={report.calibration.agreement_rate:.1%}, "
              f"MAE={report.calibration.mae:.2f}, drifted={report.calibration.drifted}")
    print("=" * 60)

    # Exit with failure code if regression failed
    if not report.all_passed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
