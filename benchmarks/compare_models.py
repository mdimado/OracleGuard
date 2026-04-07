#!/usr/bin/env python3
"""
Compare multiple LLM models on the same HumanEval problems.

Runs each model on the same set of problems and produces a comparison
table showing trust scores, verdict distributions, and fault detection
rates per model.

Usage:
    uv run benchmarks/compare_models.py
    uv run benchmarks/compare_models.py --limit 10 --mutants 20
    uv run benchmarks/compare_models.py --models "qwen/qwen3.6-plus:free,openai/gpt-oss-20b:free"
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracleguard import OpenAIProvider, MockLLMProvider
from benchmarks.humaneval_loader import load_humaneval, materialize_all
from benchmarks.run_benchmark import (
    run_oracleguard_on_problem, compute_summary, ProblemResult,
    LoggingProvider,
)


# Models to test — filtered to those that returned usable output
DEFAULT_MODELS = [
    "qwen/qwen3.6-plus:free",
    "openai/gpt-oss-20b:free",
    "minimax/minimax-m2.5:free",
]


def test_model_availability(api_key: str, base_url: str,
                            models: list[str]) -> list[str]:
    """Quick probe each model. Return list of working models."""
    import openai
    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    prompt = ('Return JSON only: {"assertions":[{"code":"assert 1==1",'
              '"explanation":"test","confidence":0.9,"type":"value"}]}')

    working = []
    for model in models:
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.7,
            )
            content = r.choices[0].message.content or ""
            if "{" in content and "assert" in content:
                print(f"  [OK]   {model}")
                working.append(model)
            else:
                print(f"  [SKIP] {model} — no usable JSON (len={len(content)})")
        except Exception as e:
            err = str(e)[:80]
            print(f"  [FAIL] {model} — {err}")
        time.sleep(3)

    return working


def run_model_benchmark(model: str, problems, api_key: str, base_url: str,
                        num_mutants: int, call_interval: float):
    """Run benchmark for a single model."""
    provider = OpenAIProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        call_interval=call_interval,
    )

    results = []
    for i, problem in enumerate(problems):
        print(f"    [{i+1}/{len(problems)}] {problem.task_id}", end="", flush=True)
        r = run_oracleguard_on_problem(problem, num_mutants=num_mutants,
                                        provider=provider)
        results.append(r)
        if r.error:
            print(f" ERROR: {r.error[:60]}")
        else:
            print(f" {r.status:<18} trust={r.trust_score:.2f}")

    return results


def print_comparison(model_results: dict[str, list[ProblemResult]]):
    """Print a side-by-side comparison table."""
    print("\n" + "=" * 90)
    print("MODEL COMPARISON")
    print("=" * 90)

    # Header
    models = list(model_results.keys())
    short_names = [m.split("/")[-1].replace(":free", "") for m in models]

    print(f"\n{'Metric':<35}", end="")
    for name in short_names:
        print(f" {name:>16}", end="")
    print()
    print("-" * (35 + 17 * len(models)))

    # Compute summaries
    summaries = {}
    for model, results in model_results.items():
        summaries[model] = compute_summary(results)

    # Rows
    metrics = [
        ("Problems Analyzed", lambda s: f"{s.problems_analyzed}"),
        ("Errors", lambda s: f"{s.problems_errored}"),
        ("", None),
        ("VERIFIED", lambda s: f"{s.verified_count}"),
        ("SUSPICIOUS", lambda s: f"{s.suspicious_count}"),
        ("NEEDS_REFINEMENT", lambda s: f"{s.needs_refinement_count}"),
        ("REJECTED", lambda s: f"{s.rejected_count}"),
        ("", None),
        ("Mean Trust Score", lambda s: f"{s.mean_trust_score:.3f}"),
        ("Mean Mutation Score", lambda s: f"{s.mean_mutation_score:.3f}"),
        ("Mean OG Fault Detection", lambda s: f"{s.mean_og_fault_detection_rate:.1%}"),
        ("Mean GT Fault Detection", lambda s: f"{s.mean_gt_fault_detection_rate:.1%}"),
        ("", None),
        ("Total Time (s)", lambda s: f"{s.total_elapsed_seconds:.0f}"),
    ]

    for label, fn in metrics:
        if fn is None:
            print()
            continue
        print(f"  {label:<33}", end="")
        for model in models:
            print(f" {fn(summaries[model]):>16}", end="")
        print()

    # Per-problem comparison
    print(f"\n{'Problem':<20}", end="")
    for name in short_names:
        print(f" {name:>16}", end="")
    print()
    print("-" * (20 + 17 * len(models)))

    # Get all task IDs
    all_tasks = []
    for results in model_results.values():
        for r in results:
            if r.task_id not in all_tasks:
                all_tasks.append(r.task_id)

    for task_id in all_tasks:
        short_task = task_id.split("/")[-1]
        print(f"  {short_task:<18}", end="")
        for model in models:
            results = model_results[model]
            r = next((x for x in results if x.task_id == task_id), None)
            if r is None or r.error:
                print(f" {'ERR':>16}", end="")
            else:
                print(f" {r.trust_score:>5.2f} {r.status[:8]:>10}", end="")
        print()

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Compare LLM models on HumanEval benchmark",
    )
    parser.add_argument("--limit", type=int, default=10,
                        help="Number of problems (default: 10)")
    parser.add_argument("--mutants", type=int, default=15,
                        help="Mutants per test case (default: 15)")
    parser.add_argument("--call-interval", type=float,
                        default=float(os.getenv("LLM_CALL_INTERVAL", "5")))
    parser.add_argument("--models", help="Comma-separated model list (overrides default)")
    parser.add_argument("--output", help="Save results to JSON")
    parser.add_argument("--skip-probe", action="store_true",
                        help="Skip model availability check")
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")

    if not api_key:
        print("Error: Set OPENROUTER_API_KEY in .env")
        sys.exit(1)

    if args.models:
        models = [m.strip() for m in args.models.split(",")]
    else:
        models = DEFAULT_MODELS

    # Probe models
    if not args.skip_probe:
        print("Probing model availability...")
        models = test_model_availability(api_key, base_url, models)
        if not models:
            print("No working models found!")
            sys.exit(1)
        print(f"\n{len(models)} model(s) available\n")

    # Load problems once
    print(f"Loading HumanEval+ (limit={args.limit})...")
    problems = load_humaneval(limit=args.limit)
    out_dir = materialize_all(problems)
    print(f"Loaded {len(problems)} problems\n")

    # Run each model
    model_results: dict[str, list[ProblemResult]] = {}

    for i, model in enumerate(models):
        print(f"\n{'='*70}")
        print(f"MODEL {i+1}/{len(models)}: {model}")
        print(f"{'='*70}")

        results = run_model_benchmark(
            model, problems, api_key, base_url,
            num_mutants=args.mutants,
            call_interval=args.call_interval,
        )
        model_results[model] = results

        # Brief pause between models
        if i < len(models) - 1:
            print("  Cooling down (10s)...")
            time.sleep(10)

    # Print comparison
    print_comparison(model_results)

    # Save
    if args.output:
        output = {}
        for model, results in model_results.items():
            s = compute_summary(results)
            output[model] = {
                "summary": asdict(s),
                "results": [asdict(r) for r in results],
            }
        Path(args.output).write_text(json.dumps(output, indent=2, default=str))
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
