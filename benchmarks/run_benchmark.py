#!/usr/bin/env python3
"""
OracleGuard Benchmark Runner

Evaluates the pipeline against HumanEval+ problems and measures:
  1. Trust score distribution across correct functions
  2. Fault detection rate — do VERIFIED oracles catch seeded mutations?
  3. Mutation operator effectiveness — which operators survive most?
  4. Comparison of OracleGuard oracles vs. human-written ground-truth oracles
  5. Trust score correlation with actual fault-detection ability

Usage:
    uv run benchmarks/run_benchmark.py                 # quick (10 problems)
    uv run benchmarks/run_benchmark.py --limit 50      # medium
    uv run benchmarks/run_benchmark.py --full           # all 164
    uv run benchmarks/run_benchmark.py --output results.json
"""

import argparse
import json
import os
import sys
import time
import tempfile
import subprocess
from dataclasses import dataclass, field, asdict
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
from typing import List, Dict, Optional, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracleguard import (
    StaticAnalyzer, PrefixGenerator, MockLLMProvider, AssertionGenerator,
    DifferentialTester, OracleAnalyzer, OracleStatus, Mutator,
)
from benchmarks.humaneval_loader import (
    load_humaneval, materialize_all, BenchmarkProblem,
)


class LoggingProvider:
    """Wraps an LLM provider to capture raw responses."""

    def __init__(self, provider):
        self.provider = provider
        self.last_response = ""

    def generate_assertions(self, prompt: str) -> str:
        self.last_response = self.provider.generate_assertions(prompt)
        return self.last_response


@dataclass
class ProblemResult:
    """Result of benchmarking one HumanEval problem."""
    task_id: str
    entry_point: str
    complexity: int = 0
    num_methods_found: int = 0
    # OracleGuard outputs
    trust_score: float = 0.0
    status: str = ""
    mutation_score: float = 0.0
    mutants_killed: int = 0
    mutants_total: int = 0
    num_assertions: int = 0
    weaknesses: List[str] = field(default_factory=list)
    # Fault detection evaluation
    ground_truth_asserts: int = 0
    og_catches_seeded_faults: int = 0
    og_misses_seeded_faults: int = 0
    gt_catches_seeded_faults: int = 0
    gt_misses_seeded_faults: int = 0
    # Per-operator breakdown
    killed_by_operator: Dict[str, int] = field(default_factory=dict)
    survived_by_operator: Dict[str, int] = field(default_factory=dict)
    # LLM response log
    llm_raw_response: str = ""
    llm_assertions: List[Dict[str, Any]] = field(default_factory=list)
    generated_test_code: str = ""
    # Mutation details
    mutant_details: List[Dict[str, str]] = field(default_factory=list)
    # Timing
    elapsed_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class BenchmarkSummary:
    """Aggregate statistics across all problems."""
    total_problems: int = 0
    problems_analyzed: int = 0
    problems_skipped: int = 0
    problems_errored: int = 0
    # Trust score distribution
    verified_count: int = 0
    suspicious_count: int = 0
    needs_refinement_count: int = 0
    rejected_count: int = 0
    mean_trust_score: float = 0.0
    mean_mutation_score: float = 0.0
    # Fault detection
    mean_og_fault_detection_rate: float = 0.0
    mean_gt_fault_detection_rate: float = 0.0
    # Mutation operator breakdown
    survived_by_operator: Dict[str, int] = field(default_factory=dict)
    killed_by_operator: Dict[str, int] = field(default_factory=dict)
    # Timing
    total_elapsed_seconds: float = 0.0


def _create_provider(llm: str, model: Optional[str] = None,
                     base_url: Optional[str] = None,
                     call_interval: float = 0.0,
                     api_key: Optional[str] = None):
    """Create an LLM provider from CLI args."""
    from oracleguard import OpenAIProvider
    if llm == 'openai':
        return OpenAIProvider(
            api_key=api_key,
            model=model or 'gpt-4',
            base_url=base_url,
            call_interval=call_interval,
        )
    return MockLLMProvider()


def run_oracleguard_on_problem(
    problem: BenchmarkProblem, num_mutants: int = 15,
    provider=None,
) -> ProblemResult:
    """Run the full OracleGuard pipeline on one HumanEval problem."""
    if provider is None:
        provider = MockLLMProvider()

    result = ProblemResult(
        task_id=problem.task_id,
        entry_point=problem.entry_point,
        ground_truth_asserts=len(problem.ground_truth_asserts),
    )
    start = time.time()

    try:
        source_path = str(problem.source_path)

        # Stage 1: Static Analysis — skip complexity filter for HumanEval
        all_methods = StaticAnalyzer.analyze(source_path)
        result.num_methods_found = len(all_methods)

        target = next((m for m in all_methods if m.name == problem.entry_point), None)
        if target is None:
            result.error = f"Entry point '{problem.entry_point}' not found"
            result.elapsed_seconds = time.time() - start
            return result

        result.complexity = target.complexity_score

        # Stage 2: Prefix Generation
        prefix = PrefixGenerator(target, source_path).generate()

        # Stage 3: LLM Assertion Generation (with response capture)
        logging_provider = LoggingProvider(provider)
        test_cases = AssertionGenerator(
            logging_provider, target, prefix
        ).generate_test_cases(count=1)
        tc = test_cases[0]
        result.num_assertions = len(tc.assertions)
        result.llm_raw_response = logging_provider.last_response
        result.llm_assertions = [
            {'code': a.assertion_code, 'confidence': a.confidence,
             'type': a.oracle_type, 'explanation': a.explanation}
            for a in tc.assertions
        ]
        result.generated_test_code = tc.full_test_code

        # Stage 4: Differential Testing
        diff_report = DifferentialTester(
            source_path, tc
        ).run_differential_test(num_mutants=num_mutants)

        result.mutants_killed = diff_report.mutants_killed
        result.mutants_total = len(diff_report.mutation_results)
        result.mutation_score = diff_report.mutation_score

        # Track per-operator outcomes
        for mr in diff_report.mutation_results:
            if mr.killed:
                result.killed_by_operator[mr.mutation_type] = \
                    result.killed_by_operator.get(mr.mutation_type, 0) + 1
            else:
                result.survived_by_operator[mr.mutation_type] = \
                    result.survived_by_operator.get(mr.mutation_type, 0) + 1
            result.mutant_details.append({
                'id': mr.mutant_id,
                'type': mr.mutation_type,
                'original': mr.original_code,
                'mutated': mr.mutated_code,
                'killed': mr.killed,
                'oracle_killed': mr.oracle_killed,
            })

        # Stage 5: Analysis
        verdict = OracleAnalyzer(tc, diff_report, target).analyze()
        result.trust_score = verdict.trust_score
        result.status = verdict.status.value
        result.weaknesses = verdict.weaknesses

        # --- Fault Detection Evaluation ---
        # Generate fresh mutants and test OracleGuard's oracles vs ground-truth
        fault_detection = evaluate_fault_detection(
            problem, tc, num_faults=10
        )
        result.og_catches_seeded_faults = fault_detection['og_catches']
        result.og_misses_seeded_faults = fault_detection['og_misses']
        result.gt_catches_seeded_faults = fault_detection['gt_catches']
        result.gt_misses_seeded_faults = fault_detection['gt_misses']

    except Exception as e:
        result.error = str(e)

    result.elapsed_seconds = time.time() - start
    return result


def evaluate_fault_detection(
    problem: BenchmarkProblem,
    test_case,
    num_faults: int = 10,
) -> Dict[str, int]:
    """Compare OracleGuard oracles vs ground-truth asserts on seeded faults.

    For each mutant:
      - Run OracleGuard's generated test → did it catch the fault?
      - Run ground-truth asserts → did they catch the fault?
    """
    source_code = problem.source_path.read_text()
    mutator = Mutator(source_code)
    mutants = mutator.generate_mutants(count=num_faults)

    og_catches = 0
    og_misses = 0
    gt_catches = 0
    gt_misses = 0

    for mutant in mutants:
        mutated_src = mutant['source_code']

        # Test with OracleGuard's generated assertions
        og_killed = _run_test_on_source(
            mutated_src, test_case.full_test_code, test_case.test_name
        )
        if og_killed:
            og_catches += 1
        else:
            og_misses += 1

        # Test with ground-truth assertions
        gt_killed = _run_ground_truth_on_source(
            mutated_src, problem
        )
        if gt_killed:
            gt_catches += 1
        else:
            gt_misses += 1

    return {
        'og_catches': og_catches,
        'og_misses': og_misses,
        'gt_catches': gt_catches,
        'gt_misses': gt_misses,
    }


def _run_test_on_source(mutated_src: str, test_code: str,
                         test_name: str) -> bool:
    """Run a test function against mutated source. Returns True if fault caught."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(mutated_src)
        f.write("\n\n")
        f.write(test_code)
        f.write(f"\n\n{test_name}()\n")
        tmp = Path(f.name)

    try:
        result = subprocess.run(
            [sys.executable, str(tmp)],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode != 0  # non-zero = fault caught
    except subprocess.TimeoutExpired:
        return True  # timeout counts as catching the fault
    finally:
        tmp.unlink(missing_ok=True)


def _run_ground_truth_on_source(mutated_src: str,
                                 problem: BenchmarkProblem) -> bool:
    """Run ground-truth assertions against mutated source.

    HumanEval tests use a `check(candidate)` pattern where `candidate`
    is the function under test. We inject the mutated source, then call
    check() with the entry point function.
    """
    gt_test = mutated_src + "\n\n" + problem.ground_truth_tests
    gt_test += f"\ncheck({problem.entry_point})\n"

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(gt_test)
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


def compute_summary(results: List[ProblemResult]) -> BenchmarkSummary:
    """Aggregate results into a summary."""
    s = BenchmarkSummary(total_problems=len(results))

    trust_scores = []
    mutation_scores = []
    og_rates = []
    gt_rates = []

    for r in results:
        if r.error:
            s.problems_errored += 1
            continue
        if not r.status:
            s.problems_skipped += 1
            continue

        s.problems_analyzed += 1
        trust_scores.append(r.trust_score)
        mutation_scores.append(r.mutation_score)

        if r.status == 'verified':
            s.verified_count += 1
        elif r.status == 'suspicious':
            s.suspicious_count += 1
        elif r.status == 'needs_refinement':
            s.needs_refinement_count += 1
        elif r.status == 'rejected':
            s.rejected_count += 1

        total_faults = r.og_catches_seeded_faults + r.og_misses_seeded_faults
        if total_faults > 0:
            og_rates.append(r.og_catches_seeded_faults / total_faults)
            gt_total = r.gt_catches_seeded_faults + r.gt_misses_seeded_faults
            if gt_total > 0:
                gt_rates.append(r.gt_catches_seeded_faults / gt_total)

        # Aggregate operator stats
        for op, count in r.killed_by_operator.items():
            s.killed_by_operator[op] = s.killed_by_operator.get(op, 0) + count
        for op, count in r.survived_by_operator.items():
            s.survived_by_operator[op] = s.survived_by_operator.get(op, 0) + count

    s.mean_trust_score = sum(trust_scores) / len(trust_scores) if trust_scores else 0
    s.mean_mutation_score = sum(mutation_scores) / len(mutation_scores) if mutation_scores else 0
    s.mean_og_fault_detection_rate = sum(og_rates) / len(og_rates) if og_rates else 0
    s.mean_gt_fault_detection_rate = sum(gt_rates) / len(gt_rates) if gt_rates else 0
    s.total_elapsed_seconds = sum(r.elapsed_seconds for r in results)

    return s


def print_results(results: List[ProblemResult], summary: BenchmarkSummary):
    """Print a formatted report."""
    print("\n" + "=" * 80)
    print("ORACLEGUARD BENCHMARK RESULTS")
    print("=" * 80)

    # Per-problem table
    print(f"\n{'Task':<20} {'Status':<18} {'Trust':>6} {'MutScore':>9} "
          f"{'OG Catch':>9} {'GT Catch':>9} {'Time':>6}")
    print("-" * 80)

    for r in results:
        if r.error:
            print(f"{r.task_id:<20} ERROR: {r.error[:50]}")
            continue
        og_total = r.og_catches_seeded_faults + r.og_misses_seeded_faults
        gt_total = r.gt_catches_seeded_faults + r.gt_misses_seeded_faults
        og_rate = f"{r.og_catches_seeded_faults}/{og_total}" if og_total else "N/A"
        gt_rate = f"{r.gt_catches_seeded_faults}/{gt_total}" if gt_total else "N/A"
        print(f"{r.task_id:<20} {r.status:<18} {r.trust_score:>6.2f} "
              f"{r.mutation_score:>8.0%} {og_rate:>9} {gt_rate:>9} "
              f"{r.elapsed_seconds:>5.1f}s")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  Problems analyzed: {summary.problems_analyzed}/{summary.total_problems}")
    print(f"  Errored: {summary.problems_errored}")
    print(f"  Skipped: {summary.problems_skipped}")
    print()
    print(f"  Trust Score Distribution:")
    print(f"    VERIFIED:         {summary.verified_count}")
    print(f"    SUSPICIOUS:       {summary.suspicious_count}")
    print(f"    NEEDS_REFINEMENT: {summary.needs_refinement_count}")
    print(f"    REJECTED:         {summary.rejected_count}")
    print()
    print(f"  Mean Trust Score:          {summary.mean_trust_score:.3f}")
    print(f"  Mean Mutation Score:       {summary.mean_mutation_score:.3f}")
    print(f"  Mean OG Fault Detection:   {summary.mean_og_fault_detection_rate:.1%}")
    print(f"  Mean GT Fault Detection:   {summary.mean_gt_fault_detection_rate:.1%}")
    print(f"  Total Time:                {summary.total_elapsed_seconds:.1f}s")

    # Operator breakdown
    all_ops = set(summary.killed_by_operator) | set(summary.survived_by_operator)
    if all_ops:
        print(f"\n  Mutation Operator Breakdown:")
        print(f"    {'Operator':<25} {'Killed':>8} {'Survived':>10} {'Kill Rate':>10}")
        print(f"    {'-'*55}")
        for op in sorted(all_ops):
            k = summary.killed_by_operator.get(op, 0)
            s = summary.survived_by_operator.get(op, 0)
            total = k + s
            rate = f"{k/total:.0%}" if total > 0 else "N/A"
            print(f"    {op:<25} {k:>8} {s:>10} {rate:>10}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="OracleGuard Benchmark on HumanEval+",
    )
    parser.add_argument("--limit", type=int, default=10,
                        help="Number of problems to evaluate (default: 10)")
    parser.add_argument("--full", action="store_true",
                        help="Run on all 164 problems")
    parser.add_argument("--llm", choices=['openai', 'mock'],
                        default='mock', help="LLM provider (default: mock)")
    parser.add_argument("--model",
                        default=os.getenv("LLM_MODEL"),
                        help="Model name (env: LLM_MODEL)")
    parser.add_argument("--base-url",
                        default=os.getenv("LLM_BASE_URL"),
                        help="API base URL (env: LLM_BASE_URL)")
    parser.add_argument("--call-interval", type=float,
                        default=float(os.getenv("LLM_CALL_INTERVAL", "4")),
                        help="Min seconds between API calls (env: LLM_CALL_INTERVAL)")
    parser.add_argument("--api-key",
                        help="API key (overrides env vars)")
    parser.add_argument("--mutants", type=int, default=15,
                        help="Mutants per test case (default: 15)")
    parser.add_argument("--faults", type=int, default=10,
                        help="Seeded faults for fault-detection eval (default: 10)")
    parser.add_argument("--output", help="Save results to JSON file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    limit = None if args.full else args.limit
    provider = _create_provider(
        args.llm, args.model,
        base_url=args.base_url,
        call_interval=args.call_interval,
        api_key=args.api_key,
    )

    print(f"Loading HumanEval+ problems (limit={limit or 'all'})...")
    print(f"LLM provider: {args.llm}" +
          (f" ({args.model})" if args.model else ""))
    problems = load_humaneval(limit=limit)
    print(f"Loaded {len(problems)} problems")

    print("Materializing source files...")
    out_dir = materialize_all(problems)
    print(f"Written to {out_dir}")

    results: List[ProblemResult] = []
    for i, problem in enumerate(problems):
        label = f"[{i + 1}/{len(problems)}]"
        print(f"\n{label} {problem.task_id} ({problem.entry_point})")

        r = run_oracleguard_on_problem(
            problem, num_mutants=args.mutants, provider=provider,
        )
        results.append(r)

        if r.error:
            print(f"  ERROR: {r.error}")
        else:
            print(f"  Status: {r.status}  Trust: {r.trust_score:.2f}  "
                  f"Mutation: {r.mutation_score:.0%}  "
                  f"OG Catches: {r.og_catches_seeded_faults}  "
                  f"Time: {r.elapsed_seconds:.1f}s")

    summary = compute_summary(results)
    print_results(results, summary)

    if args.output:
        output = {
            'summary': asdict(summary),
            'results': [asdict(r) for r in results],
        }
        Path(args.output).write_text(json.dumps(output, indent=2, default=str))
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
