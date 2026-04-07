"""
Loads HumanEval / EvalPlus problems into a format OracleGuard can consume.

Each problem becomes a self-contained .py file on disk so the pipeline can
analyze it with its normal file-based workflow.
"""

import json
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from evalplus.data import get_human_eval_plus


@dataclass
class BenchmarkProblem:
    """One HumanEval problem ready for OracleGuard."""
    task_id: str                     # e.g. "HumanEval/0"
    entry_point: str                 # function name
    prompt: str                      # signature + docstring
    canonical_solution: str          # correct body
    full_source: str                 # prompt + canonical_solution
    ground_truth_tests: str          # human-written check() function
    ground_truth_asserts: List[str]  # individual assert statements
    plus_inputs: List               # EvalPlus extended inputs
    source_path: Optional[Path] = None  # temp file path when materialized


def load_humaneval(limit: Optional[int] = None) -> List[BenchmarkProblem]:
    """Load HumanEval+ problems.

    Args:
        limit: Max number of problems to load (None = all 164).
    """
    data = get_human_eval_plus()
    problems: List[BenchmarkProblem] = []

    for i, (task_id, item) in enumerate(data.items()):
        if limit is not None and i >= limit:
            break

        prompt = item["prompt"]
        solution = item["canonical_solution"]
        full_source = prompt + solution
        test_code = item.get("test", "")

        # Extract individual assert statements from the check() function
        asserts = [
            line.strip()
            for line in test_code.splitlines()
            if line.strip().startswith("assert ")
        ]

        problems.append(BenchmarkProblem(
            task_id=task_id,
            entry_point=item["entry_point"],
            prompt=prompt,
            canonical_solution=solution,
            full_source=full_source,
            ground_truth_tests=test_code,
            ground_truth_asserts=asserts,
            plus_inputs=item.get("plus_input", []),
        ))

    return problems


def materialize(problem: BenchmarkProblem, directory: Path) -> Path:
    """Write the problem's source code to a .py file on disk.

    Returns the path to the created file.
    """
    safe_name = problem.task_id.replace("/", "_").lower()
    path = directory / f"{safe_name}.py"
    path.write_text(problem.full_source)
    problem.source_path = path
    return path


def materialize_all(problems: List[BenchmarkProblem],
                    directory: Optional[Path] = None) -> Path:
    """Write all problems to disk. Returns the output directory."""
    if directory is None:
        directory = Path(tempfile.mkdtemp(prefix="oracleguard_bench_"))
    directory.mkdir(parents=True, exist_ok=True)

    for p in problems:
        materialize(p, directory)

    return directory
