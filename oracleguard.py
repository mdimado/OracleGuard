#!/usr/bin/env python3
"""
OracleGuard - Automated Test Oracle Generation Framework
Main CLI that orchestrates all 5 pipeline stages
"""

import argparse
import sys
import json
from pathlib import Path

# Add stages to path
sys.path.insert(0, str(Path(__file__).parent / 'stages'))

from static_analysis import StaticAnalyzer
from prefix_generation import PrefixGenerator, AdvancedPrefixGenerator
from llm_assertion_gen import (
    OpenAIProvider, AnthropicProvider, MockLLMProvider, AssertionGenerator
)
from differential_testing import DifferentialTester
from analysis_refinement import OracleAnalyzer, RefinementEngine, OracleStatus



class OracleGuard:
    """Main OracleGuard pipeline orchestrator"""
    
    def __init__(self, config: dict):
        self.config = config
        self.results = {
            'stage_1': None,
            'stage_2': None,
            'stage_3': None,
            'stage_4': None,
            'stage_5': None
        }
    
    def run_full_pipeline(self, source_file: str, method_name: str = None):
        """Run complete 5-stage pipeline"""
        
        print("\n" + "="*70)
        print("ORACLEGUARD: Automated Test Oracle Generation")
        print("="*70 + "\n")
        
        # Stage 1: Static Analysis
        print("📊 Stage 1: Static Analysis")
        print("-" * 70)
        methods = self._run_stage_1(source_file, method_name)
        if not methods:
            print("❌ No methods found to analyze!")
            return None
        
        all_verdicts = []
        
        for method in methods:
            print(f"\n🎯 Analyzing method: {method.name}")
            print("=" * 70)
            
            # Stage 2: Test Prefix Generation
            print("\n🔧 Stage 2: Test Prefix Generation")
            print("-" * 70)
            prefix = self._run_stage_2(method, source_file)
            
            # Stage 3: LLM Assertion Generation
            print("\n🤖 Stage 3: LLM Assertion Generation")
            print("-" * 70)
            test_cases = self._run_stage_3(method, prefix, source_file)
            
            # For each test case, run stages 4 and 5
            for test_case in test_cases:
                print(f"\n Test Case: {test_case.test_name}")
                
                # Stage 4: Differential Testing
                print("\n Stage 4: Differential Testing")
                print("-" * 70)
                diff_report = self._run_stage_4(source_file, test_case)
                
                # Stage 5: Analysis & Refinement
                print("\n Stage 5: Analysis & Refinement")
                print("-" * 70)
                verdict = self._run_stage_5(test_case, diff_report, method)
                
                all_verdicts.append({
                    'method': method,
                    'test_case': test_case,
                    'verdict': verdict,
                    'diff_report': diff_report
                })
        
        return all_verdicts
    
    def _run_stage_1(self, source_file: str, method_name: str = None):
        """Stage 1: Extract methods"""
        try:
            methods = StaticAnalyzer.analyze(source_file)
            methods = StaticAnalyzer.filter_methods(
                methods,
                min_complexity=self.config.get('min_complexity', 2),
                max_complexity=self.config.get('max_complexity', 20)
            )
            
            if method_name:
                methods = [m for m in methods if m.name == method_name]
            
            self.results['stage_1'] = methods
            
            print(f"✓ Found {len(methods)} method(s) to analyze")
            for m in methods:
                print(f"  • {m.name} (complexity: {m.complexity_score})")
            
            return methods
            
        except Exception as e:
            print(f"❌ Stage 1 failed: {e}")
            return []
    
    def _run_stage_2(self, method, source_file: str):
        """Stage 2: Generate test prefix"""
        try:
            strategy = self.config.get('prefix_strategy', 'random')
            
            if strategy == 'random':
                generator = PrefixGenerator(method, source_file)
            else:
                generator = AdvancedPrefixGenerator(method, source_file, strategy=strategy)
            
            prefix = generator.generate()
            self.results['stage_2'] = prefix
            
            print(f"✓ Generated test prefix")
            print(f"  • Variables: {list(prefix.variable_bindings.keys())}")
            
            return prefix
            
        except Exception as e:
            print(f"❌ Stage 2 failed: {e}")
            raise
    
    def _run_stage_3(self, method, prefix, source_file: str):
        """Stage 3: Generate assertions with LLM"""
        try:
            # Select LLM provider
            provider_name = self.config.get('llm_provider', 'mock')
            
            if provider_name == 'openai':
                provider = OpenAIProvider(model=self.config.get('llm_model', 'gpt-4'))
            elif provider_name == 'anthropic':
                provider = AnthropicProvider(model=self.config.get('llm_model', 'claude-sonnet-4-5-20250929'))
            else:
                provider = MockLLMProvider()
                print("  ℹ️  Using mock LLM (no API calls)")
            
            generator = AssertionGenerator(provider, method, prefix)
            test_cases = generator.generate_test_cases(
                count=self.config.get('test_count', 2)
            )
            
            self.results['stage_3'] = test_cases
            
            print(f"✓ Generated {len(test_cases)} test case(s)")
            for tc in test_cases:
                print(f"  • {tc.test_name}: {len(tc.assertions)} assertion(s)")
            
            return test_cases
            
        except Exception as e:
            print(f"❌ Stage 3 failed: {e}")
            raise
    
    def _run_stage_4(self, source_file: str, test_case):
        """Stage 4: Differential testing"""
        try:
            tester = DifferentialTester(source_file, test_case)
            report = tester.run_differential_test(
                num_mutants=self.config.get('num_mutants', 10)
            )
            
            self.results['stage_4'] = report
            
            print(f"✓ Tested against {len(report.mutation_results)} mutants")
            print(f"  • Killed: {report.mutants_killed}")
            print(f"  • Survived: {report.mutants_survived}")
            print(f"  • Kill rate: {report.consistency_score:.1%}")
            
            return report
            
        except Exception as e:
            print(f"❌ Stage 4 failed: {e}")
            raise
    
    def _run_stage_5(self, test_case, diff_report, method):
        """Stage 5: Analysis and refinement"""
        try:
            analyzer = OracleAnalyzer(test_case, diff_report, method)
            verdict = analyzer.analyze()
            
            self.results['stage_5'] = verdict
            
            # Status icon
            status_icons = {
                OracleStatus.VERIFIED: "",
                OracleStatus.SUSPICIOUS: "⚠️",
                OracleStatus.NEEDS_REFINEMENT: "🔧",
                OracleStatus.REJECTED: "❌"
            }
            icon = status_icons.get(verdict.status, "❓")
            
            print(f"{icon} Status: {verdict.status.value.upper()}")
            print(f"  • Trust Score: {verdict.trust_score:.1%}")
            
            if verdict.weaknesses:
                print(f"  • Weaknesses: {len(verdict.weaknesses)}")
            
            # Generate refinements if needed
            if verdict.status in [OracleStatus.SUSPICIOUS, OracleStatus.NEEDS_REFINEMENT]:
                engine = RefinementEngine(verdict, test_case, diff_report)
                refinements = engine.generate_refinements()
                if refinements:
                    print(f"  • Refinement suggestions: {len(refinements)}")
            
            return verdict
            
        except Exception as e:
            print(f"❌ Stage 5 failed: {e}")
            raise


def print_final_report(verdicts):
    """Print comprehensive final report"""
    print("\n" + "="*70)
    print("FINAL REPORT")
    print("="*70 + "\n")
    
    for item in verdicts:
        verdict = item['verdict']
        method = item['method']
        test_case = item['test_case']
        
        status_icons = {
            OracleStatus.VERIFIED: "",
            OracleStatus.SUSPICIOUS: "⚠️",
            OracleStatus.NEEDS_REFINEMENT: "🔧",
            OracleStatus.REJECTED: "❌"
        }
        icon = status_icons.get(verdict.status, "❓")
        
        print(f"{icon} {method.name} / {test_case.test_name}")
        print(f"   Status: {verdict.status.value}")
        print(f"   Trust Score: {verdict.trust_score:.1%}")
        print(f"   Assertions: {len(test_case.assertions)}")
        print()
    
    # Summary statistics
    verified = sum(1 for v in verdicts if v['verdict'].status == OracleStatus.VERIFIED)
    total = len(verdicts)
    
    print(f"Summary: {verified}/{total} test oracles verified")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="OracleGuard: Automated Test Oracle Generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze with mock LLM (no API needed)
  python oracleguard.py example.py
  
  # Analyze specific method with OpenAI
  python oracleguard.py example.py --method calculate_sum --llm openai
  
  # Full analysis with Anthropic Claude
  python oracleguard.py example.py --llm anthropic --mutants 20
  
  # Generate and save test file
  python oracleguard.py example.py --output test_example.py
        """
    )
    
    parser.add_argument("file", help="Source code file to analyze (.py or .java)")
    parser.add_argument("--method", help="Specific method name to analyze")
    
    # LLM options
    parser.add_argument("--llm", choices=['openai', 'anthropic', 'mock'], 
                       default='mock', help="LLM provider (default: mock)")
    parser.add_argument("--model", help="Specific LLM model to use")
    
    # Pipeline options
    parser.add_argument("--mutants", type=int, default=10, 
                       help="Number of mutants for differential testing")
    parser.add_argument("--tests", type=int, default=2, 
                       help="Number of test cases to generate per method")
    parser.add_argument("--min-complexity", type=int, default=2,
                       help="Minimum method complexity to analyze")
    parser.add_argument("--max-complexity", type=int, default=20,
                       help="Maximum method complexity to analyze")
    
    # Output options
    parser.add_argument("--output", help="Output file for generated tests")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    # Build configuration
    config = {
        'llm_provider': args.llm,
        'llm_model': args.model,
        'num_mutants': args.mutants,
        'test_count': args.tests,
        'min_complexity': args.min_complexity,
        'max_complexity': args.max_complexity,
        'verbose': args.verbose
    }
    
    try:
        # Initialize OracleGuard
        guard = OracleGuard(config)
        
        # Run pipeline
        verdicts = guard.run_full_pipeline(args.file, args.method)
        
        if not verdicts:
            sys.exit(1)
        
        # Print final report
        print_final_report(verdicts)
        
        # Save tests if requested
        if args.output:
            with open(args.output, 'w') as f:
                f.write("# Generated by OracleGuard\n")
                f.write("# Automated Test Oracle Generation\n\n")
                
                for item in verdicts:
                    if item['verdict'].status == OracleStatus.VERIFIED:
                        f.write(item['test_case'].full_test_code)
                        f.write("\n\n")
            
            print(f"✓ Verified tests written to {args.output}\n")
        
        # JSON output if requested
        if args.json:
            output = []
            for item in verdicts:
                output.append({
                    'method': item['method'].name,
                    'test': item['test_case'].test_name,
                    'status': item['verdict'].status.value,
                    'trust_score': item['verdict'].trust_score,
                    'weaknesses': item['verdict'].weaknesses,
                    'recommendations': item['verdict'].recommendations
                })
            print(json.dumps(output, indent=2))
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Pipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()