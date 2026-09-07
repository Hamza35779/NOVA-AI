"""Coding task scorer — test pass rate + structural validation.

Extracts the function/class from model output and runs test cases
to determine correctness.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from nova_ai.evals.core.scorer import Scorer
from nova_ai.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

LOGGER = logging.getLogger(__name__)


def _extract_code(answer: str) -> str:
    """Extract Python code from model answer, handling markdown fences.

    Models frequently open with a small illustrative snippet in their
    explanation before presenting the real implementation. Scoring the FIRST
    fence therefore scores the wrong code. Heuristic: when multiple fenced
    blocks exist, prefer the last one containing a ``def``/``class``
    definition — implementations come after examples far more often than
    before. Single-fence answers (the common case) behave exactly as before.
    """
    fence_matches = re.findall(
        # Cover the language-tag variants models actually emit: bare fence,
        # ``python``, ``py``, ``python3``.
        r"```(?:py|python3|python)?\s*\n(.*?)```",
        answer,
        re.DOTALL,
    )
    if fence_matches:
        if len(fence_matches) == 1:
            return fence_matches[0].strip()
        definitional = [
            block
            for block in fence_matches
            if re.search(r"^\s*(def |class |async def )", block, re.MULTILINE)
        ]
        return (definitional or fence_matches)[-1].strip()

    # Look for function/class definitions
    lines = answer.strip().split("\n")
    code_lines = []
    in_code = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(("def ", "class ", "from ", "import ")):
            in_code = True
        if in_code:
            code_lines.append(line)

    if code_lines:
        return "\n".join(code_lines)

    # Last resort: return the whole answer
    return answer.strip()


def _run_tests(code: str, test_cases: str) -> Tuple[int, int, str]:
    """Execute code + tests in a restricted namespace. Returns (passed, total, error)."""
    namespace: Dict[str, Any] = {}

    try:
        exec(code, namespace)  # noqa: S102
    except Exception as exc:
        return 0, 0, f"Code execution error: {exc}"

    # Parse individual test assertions
    test_lines = [
        line.strip() for line in test_cases.strip().split("\n") if line.strip()
    ]

    passed = 0
    total = 0

    # Some tests span multiple lines (setup + assert), so we run
    # the whole block together but count assertions
    try:
        exec(test_cases, namespace)  # noqa: S102
        # Count assertions in the test code
        total = sum(1 for line in test_lines if "assert " in line)
        passed = total
        return passed, total, ""
    except AssertionError as exc:
        # Whole-block scoring: an AssertionError somewhere in the block means
        # the block did NOT fully pass. Fine-grained line-by-line exec was
        # tried here and mis-counts badly — many tests span multiple lines
        # (setup/arrange lines without ``assert``, parenthesized assertions,
        # try/except), so executing bare lines either raises NameError (setup
        # never ran) or "succeeds" vacuously. The only trustworthy signal is
        # the whole block, so: any AssertionError => 0 of N passed.
        total = sum(1 for line in test_lines if "assert " in line)
        return 0, total, str(exc)
    except Exception as exc:
        total = sum(1 for line in test_lines if "assert " in line)
        return 0, max(total, 1), f"Test execution error: {exc}"


class CodingTaskScorer(Scorer):
    """Score coding tasks by running test cases against model output."""

    scorer_id = "coding_task"

    def __init__(self, judge_backend=None, judge_model: str = "") -> None:
        # Accept same constructor args as LLMJudgeScorer for compatibility
        # but don't need the judge for this scorer
        pass

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        test_cases = record.metadata.get("test_cases", "")
        if not test_cases:
            return None, {"reason": "no_test_cases"}

        code = _extract_code(model_answer)
        if not code:
            return False, {"reason": "no_code_extracted"}

        passed, total, error = _run_tests(code, test_cases)

        if total == 0:
            # total=0 with an error means the code itself crashed on exec.
            # That is a model failure (broken code), not "no assertions" —
            # converting it to None excludes it from resolve-rate and
            # inflates the score. Report it as False. (#515)
            if error:
                return False, {
                    "reason": "code_execution_error",
                    "error": error,
                    "match_type": "test_execution",
                    "tests_passed": 0,
                    "tests_total": 0,
                    "pass_rate": 0.0,
                }
            return None, {"reason": "no_assertions_found"}

        pass_rate = passed / total
        is_correct = pass_rate == 1.0

        meta: Dict[str, Any] = {
            "match_type": "test_execution",
            "tests_passed": passed,
            "tests_total": total,
            "pass_rate": pass_rate,
        }
        if error:
            meta["error"] = error

        return is_correct, meta


__all__ = ["CodingTaskScorer"]
