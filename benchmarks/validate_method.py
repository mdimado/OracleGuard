#!/usr/bin/env python3
"""
OracleGuard Method Validation

Proves that the trust score actually works by testing oracles of KNOWN quality
against functions with KNOWN bugs. No LLM API needed — uses synthetic oracles
at four quality levels:

  STRONG:  Exact value assertions (assert result == 80.0)
  MEDIUM:  Type + range assertions (assert isinstance(result, float))
  WEAK:    Trivial assertions (assert result is not None)
  BAD:     Tautologies (assert True) or wrong assertions

For each quality level, we:
  1. Run OracleGuard's mutation-based validation → get trust score
  2. Run the oracle against independently seeded faults → get actual fault detection
  3. Check: does trust score predict fault detection?

If OracleGuard works:
  - STRONG oracles → high trust, high fault detection
  - BAD oracles → low trust, low fault detection
  - Trust score correlates with fault-detection rate
"""

import sys
import json
import time
import tempfile
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracleguard import (
    StaticAnalyzer, PrefixGenerator, DifferentialTester,
    OracleAnalyzer, Mutator, MUTATION_OPERATORS,
)
from oracleguard.assertion_generation import CandidateAssertion, TestCase
from oracleguard.prefix_generation import TestPrefix


# ---------------------------------------------------------------------------
# Test subject functions — simple enough to write exact oracles for
# ---------------------------------------------------------------------------

TEST_SUBJECTS = """
def calculate_discount(price: float, discount_percent: float) -> float:
    \"\"\"Calculate discounted price. Raises ValueError if discount_percent outside [0,100].\"\"\"
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("Discount must be between 0 and 100")
    discount_amount = price * (discount_percent / 100)
    return round(price - discount_amount, 2)


def factorial(n: int) -> int:
    \"\"\"Return factorial of n. Raises ValueError if n < 0.\"\"\"
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0 or n == 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def fibonacci(n: int) -> list:
    \"\"\"Return list of first n Fibonacci numbers.\"\"\"
    if n <= 0:
        return []
    if n == 1:
        return [0]
    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[-1] + fib[-2])
    return fib


def is_palindrome(text: str) -> bool:
    \"\"\"Check if text is a palindrome (case-insensitive).\"\"\"
    cleaned = text.lower().replace(" ", "")
    return cleaned == cleaned[::-1]


def find_max(numbers: list) -> int:
    \"\"\"Find maximum value in a list. Raises ValueError if empty.\"\"\"
    if not numbers:
        raise ValueError("List cannot be empty")
    max_val = numbers[0]
    for num in numbers[1:]:
        if num > max_val:
            max_val = num
    return max_val
"""


# ---------------------------------------------------------------------------
# Synthetic oracle definitions at four quality levels
# ---------------------------------------------------------------------------

ORACLE_DEFINITIONS = {
    "calculate_discount": {
        "call_args": "100.0, 20.0",
        "strong": [
            ("assert result == 80.0", "Exact expected value", 0.95, "value"),
            ("assert isinstance(result, float)", "Type check", 0.95, "value"),
            ("assert 0 <= result <= 100.0", "Range within input price", 0.90, "property"),
        ],
        "medium": [
            ("assert isinstance(result, float)", "Type check", 0.85, "value"),
            ("assert result >= 0", "Non-negative result", 0.80, "property"),
        ],
        "weak": [
            ("assert result is not None", "Not null", 0.70, "value"),
        ],
        "bad": [
            ("assert True", "Tautology", 0.50, "value"),
            ("assert result != 'hello'", "Irrelevant check", 0.40, "value"),
        ],
    },
    "factorial": {
        "call_args": "5",
        "strong": [
            ("assert result == 120", "Exact value 5! = 120", 0.95, "value"),
            ("assert isinstance(result, int)", "Type check", 0.95, "value"),
            ("assert result > 0", "Positive result", 0.90, "property"),
        ],
        "medium": [
            ("assert isinstance(result, int)", "Type check", 0.85, "value"),
            ("assert result > 0", "Positive result", 0.80, "property"),
        ],
        "weak": [
            ("assert result is not None", "Not null", 0.70, "value"),
        ],
        "bad": [
            ("assert True", "Tautology", 0.50, "value"),
        ],
    },
    "fibonacci": {
        "call_args": "6",
        "strong": [
            ("assert result == [0, 1, 1, 2, 3, 5]", "Exact sequence", 0.95, "value"),
            ("assert isinstance(result, list)", "Type check", 0.95, "value"),
            ("assert len(result) == 6", "Length check", 0.90, "property"),
        ],
        "medium": [
            ("assert isinstance(result, list)", "Type check", 0.85, "value"),
            ("assert len(result) == 6", "Length check", 0.80, "property"),
        ],
        "weak": [
            ("assert result is not None", "Not null", 0.70, "value"),
        ],
        "bad": [
            ("assert True", "Tautology", 0.50, "value"),
        ],
    },
    "is_palindrome": {
        "call_args": '"racecar"',
        "strong": [
            ("assert result == True", "Known palindrome", 0.95, "value"),
            ("assert isinstance(result, bool)", "Type check", 0.95, "value"),
        ],
        "medium": [
            ("assert isinstance(result, bool)", "Type check", 0.85, "value"),
        ],
        "weak": [
            ("assert result is not None", "Not null", 0.70, "value"),
        ],
        "bad": [
            ("assert True", "Tautology", 0.50, "value"),
        ],
    },
    "find_max": {
        "call_args": "[3, 7, 2, 9, 1]",
        "strong": [
            ("assert result == 9", "Exact max", 0.95, "value"),
            ("assert isinstance(result, int)", "Type check", 0.95, "value"),
            ("assert result >= 3", "At least first element", 0.90, "property"),
        ],
        "medium": [
            ("assert isinstance(result, int)", "Type check", 0.85, "value"),
            ("assert result > 0", "Positive", 0.80, "property"),
        ],
        "weak": [
            ("assert result is not None", "Not null", 0.70, "value"),
        ],
        "bad": [
            ("assert True", "Tautology", 0.50, "value"),
        ],
    },
}

QUALITY_LEVELS = ["strong", "medium", "weak", "bad"]


# ---------------------------------------------------------------------------
# Build synthetic test cases
# ---------------------------------------------------------------------------

def build_test_case(func_name: str, quality: str, source_path: str) -> TestCase:
    """Build a TestCase with synthetic assertions at the given quality level.

    The test wraps the function call in try/except so that if a mutation causes
    the function to crash (RuntimeError, TypeError, etc.), the test still PASSES.
    Only assertion failures count as "catching" the fault — this is what matters
    for evaluating oracle quality.
    """
    defn = ORACLE_DEFINITIONS[func_name]
    assertion_defs = defn[quality]
    call_args = defn["call_args"]

    module = Path(source_path).stem

    assertions = [
        CandidateAssertion(
            assertion_code=code,
            explanation=expl,
            confidence=conf,
            oracle_type=otype,
            metadata={},
        )
        for code, expl, conf, otype in assertion_defs
    ]

    test_name = f"test_{func_name}_{quality}"
    method_call = f"result = {func_name}({call_args})"

    # Wrap in try/except: if the function crashes, the test passes (oracle didn't
    # catch anything). Only AssertionError means the oracle worked.
    # No import — functions are in the same file when run by DifferentialTester.
    # Wrap call in try/except so function crashes don't masquerade as catches.
    lines = [
        f"def {test_name}():",
        f"    try:",
        f"        {method_call}",
        f"    except Exception:",
        f"        return  # function crashed — oracle did NOT catch this",
    ]
    for a in assertions:
        lines.append(f"    {a.assertion_code}")

    return TestCase(
        test_name=test_name,
        prefix_code="",
        method_call=method_call,
        assertions=assertions,
        full_test_code="\n".join(lines),
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class QualityResult:
    func_name: str
    quality_level: str
    num_assertions: int = 0
    # OracleGuard scores
    trust_score: float = 0.0
    mutation_score: float = 0.0
    status: str = ""
    mutants_killed: int = 0
    mutants_total: int = 0
    killed_by_operator: Dict[str, int] = field(default_factory=dict)
    survived_by_operator: Dict[str, int] = field(default_factory=dict)
    # Independent fault detection
    faults_caught: int = 0
    faults_missed: int = 0
    fault_detection_rate: float = 0.0
    error: Optional[str] = None


def evaluate_quality(func_name: str, quality: str, source_path: str,
                     num_mutants: int = 20,
                     num_faults: int = 15) -> QualityResult:
    """Run OracleGuard + independent fault detection for one (func, quality) pair."""
    r = QualityResult(func_name=func_name, quality_level=quality)

    try:
        tc = build_test_case(func_name, quality, source_path)
        r.num_assertions = len(tc.assertions)

        # Get method metadata
        methods = StaticAnalyzer.analyze(source_path)
        target = next((m for m in methods if m.name == func_name), None)
        if not target:
            r.error = f"Function {func_name} not found"
            return r

        # Stage 4: Differential Testing
        diff = DifferentialTester(source_path, tc).run_differential_test(num_mutants)
        r.mutants_killed = diff.mutants_killed
        r.mutants_total = len(diff.mutation_results)
        r.mutation_score = diff.mutation_score

        for mr in diff.mutation_results:
            bucket = r.killed_by_operator if mr.killed else r.survived_by_operator
            bucket[mr.mutation_type] = bucket.get(mr.mutation_type, 0) + 1

        # Stage 5: Analysis
        verdict = OracleAnalyzer(tc, diff, target).analyze()
        r.trust_score = verdict.trust_score
        r.status = verdict.status.value

        # Independent fault detection (fresh mutants, not the same ones)
        source_code = Path(source_path).read_text()
        fresh_mutants = Mutator(source_code).generate_mutants(count=num_faults)

        caught = 0
        for mutant in fresh_mutants:
            killed = _run_test(mutant['source_code'], tc.full_test_code, tc.test_name)
            if killed:
                caught += 1

        r.faults_caught = caught
        r.faults_missed = len(fresh_mutants) - caught
        total = len(fresh_mutants)
        r.fault_detection_rate = caught / total if total > 0 else 0.0

    except Exception as e:
        r.error = str(e)

    return r


def _run_test(source: str, test_code: str, test_name: str) -> bool:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(source + "\n\n" + test_code + f"\n\n{test_name}()\n")
        tmp = Path(f.name)
    try:
        result = subprocess.run(
            [sys.executable, str(tmp)],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode != 0
    except subprocess.TimeoutExpired:
        return True
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate that OracleGuard's trust score predicts fault detection",
    )
    parser.add_argument("--mutants", type=int, default=20)
    parser.add_argument("--faults", type=int, default=15)
    parser.add_argument("--output", help="Save results to JSON")
    args = parser.parse_args()

    # Write test subjects to a temp file
    tmp_dir = Path(tempfile.mkdtemp(prefix="og_validate_"))
    source_path = tmp_dir / "subjects.py"
    source_path.write_text(TEST_SUBJECTS)

    print("=" * 85)
    print("ORACLEGUARD METHOD VALIDATION")
    print("Does the trust score predict actual fault-detection ability?")
    print("=" * 85)

    all_results: List[QualityResult] = []

    for func_name in ORACLE_DEFINITIONS:
        print(f"\n--- {func_name} ---")
        for quality in QUALITY_LEVELS:
            r = evaluate_quality(
                func_name, quality, str(source_path),
                num_mutants=args.mutants, num_faults=args.faults,
            )
            all_results.append(r)

            if r.error:
                print(f"  {quality:<8} ERROR: {r.error}")
            else:
                print(f"  {quality:<8}  trust={r.trust_score:.2f}  "
                      f"mut_score={r.mutation_score:.0%}  "
                      f"status={r.status:<18}  "
                      f"fault_detect={r.fault_detection_rate:.0%} "
                      f"({r.faults_caught}/{r.faults_caught + r.faults_missed})")

    # --- Aggregate analysis ---
    print("\n" + "=" * 85)
    print("AGGREGATE ANALYSIS")
    print("=" * 85)

    by_quality: Dict[str, List[QualityResult]] = {}
    for r in all_results:
        if r.error:
            continue
        by_quality.setdefault(r.quality_level, []).append(r)

    print(f"\n{'Quality':<10} {'Avg Trust':>10} {'Avg MutScore':>13} "
          f"{'Avg FaultDet':>13} {'Verdicts':>30}")
    print("-" * 85)

    for quality in QUALITY_LEVELS:
        group = by_quality.get(quality, [])
        if not group:
            continue
        avg_trust = sum(r.trust_score for r in group) / len(group)
        avg_mut = sum(r.mutation_score for r in group) / len(group)
        avg_fd = sum(r.fault_detection_rate for r in group) / len(group)

        verdicts = {}
        for r in group:
            verdicts[r.status] = verdicts.get(r.status, 0) + 1
        verdict_str = ", ".join(f"{k}={v}" for k, v in sorted(verdicts.items()))

        print(f"  {quality:<8} {avg_trust:>10.3f} {avg_mut:>12.1%} "
              f"{avg_fd:>12.1%}   {verdict_str}")

    # --- Correlation check ---
    print("\n" + "=" * 85)
    print("CORRELATION: Trust Score vs Fault Detection Rate")
    print("=" * 85)

    valid = [r for r in all_results if not r.error]
    if len(valid) >= 4:
        # Simple rank correlation
        trust_ranks = _rank([r.trust_score for r in valid])
        fd_ranks = _rank([r.fault_detection_rate for r in valid])
        spearman = _spearman(trust_ranks, fd_ranks)
        print(f"\n  Spearman rank correlation: {spearman:.3f}")

        if spearman > 0.6:
            print("  STRONG positive correlation — trust score predicts fault detection")
        elif spearman > 0.3:
            print("  MODERATE positive correlation")
        elif spearman > 0:
            print("  WEAK positive correlation")
        else:
            print("  NO positive correlation — trust score does NOT predict fault detection")

    # --- Discrimination check ---
    print("\n" + "=" * 85)
    print("DISCRIMINATION: Can OracleGuard tell strong from bad oracles?")
    print("=" * 85)

    strong_group = by_quality.get("strong", [])
    bad_group = by_quality.get("bad", [])
    if strong_group and bad_group:
        strong_trust = sum(r.trust_score for r in strong_group) / len(strong_group)
        bad_trust = sum(r.trust_score for r in bad_group) / len(bad_group)
        strong_fd = sum(r.fault_detection_rate for r in strong_group) / len(strong_group)
        bad_fd = sum(r.fault_detection_rate for r in bad_group) / len(bad_group)
        gap = strong_trust - bad_trust

        print(f"\n  Strong oracles:  avg trust = {strong_trust:.3f}, "
              f"avg fault detection = {strong_fd:.0%}")
        print(f"  Bad oracles:     avg trust = {bad_trust:.3f}, "
              f"avg fault detection = {bad_fd:.0%}")
        print(f"  Trust gap:       {gap:.3f}")

        if gap > 0.15:
            print("  CLEAR discrimination — OracleGuard distinguishes quality levels")
        elif gap > 0.05:
            print("  MODERATE discrimination")
        else:
            print("  POOR discrimination — OracleGuard cannot distinguish quality levels")

    print()

    if args.output:
        Path(args.output).write_text(json.dumps(
            [asdict(r) for r in all_results], indent=2, default=str
        ))
        print(f"Results saved to {args.output}")


def _rank(values: list) -> list:
    """Assign ranks to values (1-based, average ties)."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = sum(range(i + 1, j + 1)) / (j - i)
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def _spearman(ranks_a: list, ranks_b: list) -> float:
    """Spearman rank correlation coefficient."""
    n = len(ranks_a)
    if n < 2:
        return 0.0
    d_sq = sum((a - b) ** 2 for a, b in zip(ranks_a, ranks_b))
    return 1 - (6 * d_sq) / (n * (n ** 2 - 1))


if __name__ == "__main__":
    main()
