#!/usr/bin/env python3
"""
Analyze and compare saved benchmark results across models.

Usage:
    uv run benchmarks/analyze_results.py results/*.json
"""

import json
import sys
from pathlib import Path
from typing import Any


def load_result_file(path: str) -> dict:
    """Load a results JSON file and detect its format."""
    data = json.loads(Path(path).read_text())

    # Multi-model format (from compare_models.py)
    if isinstance(data, dict) and all(
        isinstance(v, dict) and 'summary' in v for v in data.values()
    ):
        return data

    # Single-model format (from run_benchmark.py)
    if isinstance(data, dict) and 'results' in data:
        model_name = _detect_model(data)
        return {model_name: data}

    print(f"Warning: unrecognized format in {path}")
    return {}


def _detect_model(data: dict) -> str:
    """Try to detect model name from result data."""
    results = data.get('results', [])
    for r in results:
        resp = r.get('llm_raw_response', '')
        if resp:
            return "real_llm"
    return "unknown"


def analyze(all_data: dict[str, dict]):
    """Print comparison across all models."""

    print("=" * 90)
    print("ORACLEGUARD BENCHMARK COMPARISON")
    print("=" * 90)

    models = list(all_data.keys())
    short = [m.split("/")[-1].replace(":free", "").replace("_", " ")[:18] for m in models]

    # Summary row
    print(f"\n{'Metric':<30}", end="")
    for s in short:
        print(f"  {s:>18}", end="")
    print()
    print("-" * (30 + 20 * len(models)))

    summaries = []
    for model in models:
        d = all_data[model]
        if 'summary' in d:
            summaries.append(d['summary'])
        else:
            summaries.append(_compute_summary(d.get('results', [])))

    rows = [
        ("Problems Analyzed", "problems_analyzed"),
        ("Errors", "problems_errored"),
        ("", None),
        ("VERIFIED", "verified_count"),
        ("SUSPICIOUS", "suspicious_count"),
        ("NEEDS_REFINEMENT", "needs_refinement_count"),
        ("REJECTED", "rejected_count"),
        ("", None),
        ("Mean Trust Score", "mean_trust_score"),
        ("Mean Mutation Score", "mean_mutation_score"),
        ("OG Fault Detection", "mean_og_fault_detection_rate"),
        ("GT Fault Detection", "mean_gt_fault_detection_rate"),
        ("", None),
        ("Total Time (s)", "total_elapsed_seconds"),
    ]

    for label, key in rows:
        if key is None:
            print()
            continue
        print(f"  {label:<28}", end="")
        for s in summaries:
            val = s.get(key, 0)
            if isinstance(val, float):
                if val < 1.1 and key not in ('total_elapsed_seconds',):
                    print(f"  {val:>17.3f}", end="")
                else:
                    print(f"  {val:>17.1f}", end="")
            else:
                print(f"  {val:>17}", end="")
        print()

    # Operator breakdown
    print(f"\n{'Operator Kill Rate':<30}", end="")
    for s in short:
        print(f"  {s:>18}", end="")
    print()
    print("-" * (30 + 20 * len(models)))

    all_ops = set()
    for s in summaries:
        all_ops.update(s.get('killed_by_operator', {}).keys())
        all_ops.update(s.get('survived_by_operator', {}).keys())

    for op in sorted(all_ops):
        op_short = op.replace('_', ' ')[:28]
        print(f"  {op_short:<28}", end="")
        for s in summaries:
            k = s.get('killed_by_operator', {}).get(op, 0)
            sv = s.get('survived_by_operator', {}).get(op, 0)
            total = k + sv
            if total > 0:
                rate = k / total
                print(f"  {rate:>13.0%} ({k}/{total})", end="")
            else:
                print(f"  {'N/A':>17}", end="")
        print()

    # Per-problem comparison
    print(f"\n{'Problem':<25}", end="")
    for s in short:
        print(f"  {s:>18}", end="")
    print()
    print("-" * (25 + 20 * len(models)))

    all_tasks = []
    for model in models:
        for r in all_data[model].get('results', []):
            tid = r.get('task_id', '')
            if tid and tid not in all_tasks:
                all_tasks.append(tid)

    for tid in all_tasks:
        short_tid = tid.split("/")[-1] if "/" in tid else tid
        print(f"  {short_tid:<23}", end="")
        for model in models:
            results = all_data[model].get('results', [])
            r = next((x for x in results if x.get('task_id') == tid), None)
            if r is None:
                print(f"  {'—':>18}", end="")
            elif r.get('error'):
                print(f"  {'ERR':>18}", end="")
            else:
                score = r.get('trust_score', 0)
                status = r.get('status', '?')[:8]
                print(f"  {score:>5.2f} {status:>12}", end="")
        print()

    # Assertion quality samples
    print(f"\n{'='*90}")
    print("SAMPLE ASSERTIONS (first problem per model)")
    print(f"{'='*90}")
    for model in models:
        results = all_data[model].get('results', [])
        for r in results:
            if r.get('error'):
                continue
            assertions = r.get('llm_assertions', [])
            if not assertions:
                continue
            mshort = model.split("/")[-1].replace(":free", "")
            print(f"\n  [{mshort}] {r.get('task_id', '?')} "
                  f"(trust={r.get('trust_score', 0):.2f}, "
                  f"status={r.get('status', '?')}):")
            for a in assertions[:4]:
                if isinstance(a, dict):
                    print(f"    {a.get('code', '?'):<55} "
                          f"conf={a.get('confidence', '?')}")
                else:
                    print(f"    {a}")
            break

    print()


def _compute_summary(results: list[dict]) -> dict:
    """Compute summary from raw results list."""
    s = {
        'problems_analyzed': 0, 'problems_errored': 0,
        'verified_count': 0, 'suspicious_count': 0,
        'needs_refinement_count': 0, 'rejected_count': 0,
        'mean_trust_score': 0, 'mean_mutation_score': 0,
        'mean_og_fault_detection_rate': 0, 'mean_gt_fault_detection_rate': 0,
        'total_elapsed_seconds': 0,
        'killed_by_operator': {}, 'survived_by_operator': {},
    }

    trusts, muts, og_rates, gt_rates = [], [], [], []
    for r in results:
        if r.get('error'):
            s['problems_errored'] += 1
            continue
        if not r.get('status'):
            continue
        s['problems_analyzed'] += 1
        s[f"{r['status']}_count"] = s.get(f"{r['status']}_count", 0) + 1
        trusts.append(r.get('trust_score', 0))
        muts.append(r.get('mutation_score', 0))
        s['total_elapsed_seconds'] += r.get('elapsed_seconds', 0)

        og = r.get('og_catches_seeded_faults', 0)
        og_miss = r.get('og_misses_seeded_faults', 0)
        if og + og_miss > 0:
            og_rates.append(og / (og + og_miss))
        gt = r.get('gt_catches_seeded_faults', 0)
        gt_miss = r.get('gt_misses_seeded_faults', 0)
        if gt + gt_miss > 0:
            gt_rates.append(gt / (gt + gt_miss))

        for op, cnt in r.get('killed_by_operator', {}).items():
            s['killed_by_operator'][op] = s['killed_by_operator'].get(op, 0) + cnt
        for op, cnt in r.get('survived_by_operator', {}).items():
            s['survived_by_operator'][op] = s['survived_by_operator'].get(op, 0) + cnt

    s['mean_trust_score'] = sum(trusts) / len(trusts) if trusts else 0
    s['mean_mutation_score'] = sum(muts) / len(muts) if muts else 0
    s['mean_og_fault_detection_rate'] = sum(og_rates) / len(og_rates) if og_rates else 0
    s['mean_gt_fault_detection_rate'] = sum(gt_rates) / len(gt_rates) if gt_rates else 0
    return s


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run benchmarks/analyze_results.py results/*.json")
        sys.exit(1)

    all_data = {}
    for path in sys.argv[1:]:
        if path.startswith("-"):
            continue
        p = Path(path)
        if not p.exists():
            print(f"File not found: {path}")
            continue
        loaded = load_result_file(path)
        # Use filename as model key if we can't detect
        for model, data in loaded.items():
            key = model if model not in ('unknown', 'real_llm') else p.stem
            all_data[key] = data

    if not all_data:
        print("No results loaded!")
        sys.exit(1)

    analyze(all_data)


if __name__ == "__main__":
    main()
