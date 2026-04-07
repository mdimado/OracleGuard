"""
Pipeline orchestrator — runs all five stages end-to-end.
"""

from dataclasses import dataclass
from typing import Optional, List

from oracleguard.static_analysis import StaticAnalyzer, MUTMetadata
from oracleguard.prefix_generation import PrefixGenerator, AdvancedPrefixGenerator
from oracleguard.assertion_generation import (
    LLMProvider, OpenAIProvider, MockLLMProvider,
    AssertionGenerator, TestCase,
)
from oracleguard.differential_testing import DifferentialTester, DifferentialReport
from oracleguard.analysis import OracleAnalyzer, OracleVerdict


@dataclass
class PipelineConfig:
    """Typed configuration for the OracleGuard pipeline."""
    llm_provider: str = 'mock'       # 'openai' or 'mock'
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None  # set for OpenRouter etc.
    llm_api_key: Optional[str] = None
    call_interval: float = 0.0       # seconds between API calls
    num_mutants: int = 10
    test_count: int = 2
    min_complexity: int = 2
    max_complexity: int = 20
    prefix_strategy: str = 'random'
    verbose: bool = False


@dataclass
class PipelineResult:
    """Result of running the pipeline on one test case."""
    method: MUTMetadata
    test_case: TestCase
    diff_report: DifferentialReport
    verdict: OracleVerdict


class OracleGuard:
    """Main OracleGuard pipeline orchestrator."""

    def __init__(self, config: PipelineConfig):
        self.config = config

    def run(self, source_file: str,
            method_name: Optional[str] = None) -> List[PipelineResult]:
        """Run the complete five-stage pipeline."""
        print("\n" + "=" * 70)
        print("ORACLEGUARD: Automated Test Oracle Generation")
        print("=" * 70 + "\n")

        # Stage 1
        print("[Stage 1] Static Analysis")
        methods = StaticAnalyzer.analyze(source_file)
        methods = StaticAnalyzer.filter_methods(
            methods,
            min_complexity=self.config.min_complexity,
            max_complexity=self.config.max_complexity,
        )
        if method_name:
            methods = [m for m in methods if m.name == method_name]
        if not methods:
            print("  No qualifying methods found.")
            return []
        print(f"  Found {len(methods)} method(s)")
        for m in methods:
            print(f"    {m.name} (complexity {m.complexity_score})")

        provider = self._create_provider()
        results: List[PipelineResult] = []

        for method in methods:
            print(f"\n--- {method.name} ---")

            # Stage 2
            print("[Stage 2] Test Prefix Generation")
            if self.config.prefix_strategy == 'random':
                prefix = PrefixGenerator(method, source_file).generate()
            else:
                prefix = AdvancedPrefixGenerator(
                    method, source_file, strategy=self.config.prefix_strategy,
                ).generate()
            print(f"  Variables: {list(prefix.variable_bindings.keys())}")

            # Stage 3
            print("[Stage 3] LLM Assertion Generation")
            test_cases = AssertionGenerator(
                provider, method, prefix,
            ).generate_test_cases(count=self.config.test_count)
            print(f"  Generated {len(test_cases)} test case(s)")

            for tc in test_cases:
                # Stage 4
                print(f"[Stage 4] Differential Testing ({tc.test_name})")
                diff_report = DifferentialTester(
                    source_file, tc,
                ).run_differential_test(num_mutants=self.config.num_mutants)
                print(f"  Killed {diff_report.mutants_killed}/"
                      f"{len(diff_report.mutation_results)} "
                      f"(total {diff_report.mutation_score:.0%}, "
                      f"oracle {diff_report.oracle_kill_rate:.0%})")

                # Stage 5
                print("[Stage 5] Analysis & Refinement")
                verdict = OracleAnalyzer(tc, diff_report, method).analyze()
                print(f"  Status: {verdict.status.value.upper()} "
                      f"(trust {verdict.trust_score:.2f})")

                results.append(PipelineResult(
                    method=method, test_case=tc,
                    diff_report=diff_report, verdict=verdict,
                ))

        return results

    def _create_provider(self) -> LLMProvider:
        if self.config.llm_provider == 'openai':
            return OpenAIProvider(
                api_key=self.config.llm_api_key,
                model=self.config.llm_model or 'gpt-4',
                base_url=self.config.llm_base_url,
                call_interval=self.config.call_interval,
            )
        return MockLLMProvider()
