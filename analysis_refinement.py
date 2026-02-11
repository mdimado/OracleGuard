"""
Stage 5: Analysis & Refinement
Analyzes differential testing results and computes oracle trust scores.
Refines assertions based on discrepancy signals and validation feedback.
"""

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class OracleStatus(Enum):
    """Status of test oracle"""
    VERIFIED = "verified"
    SUSPICIOUS = "suspicious"
    REJECTED = "rejected"
    NEEDS_REFINEMENT = "needs_refinement"


@dataclass
class TrustMetrics:
    """Trust score components"""
    mutation_score: float        # How many mutants were killed
    llm_confidence: float         # Average LLM confidence
    consistency_score: float      # Cross-version consistency
    coverage_score: float         # Code coverage achieved
    complexity_penalty: float     # Penalty for high complexity
    
    def compute_overall(self) -> float:
        """Compute weighted overall trust score"""
        weights = {
            'mutation': 0.35,
            'llm': 0.20,
            'consistency': 0.25,
            'coverage': 0.15,
            'complexity': 0.05
        }
        
        score = (
            weights['mutation'] * self.mutation_score +
            weights['llm'] * self.llm_confidence +
            weights['consistency'] * self.consistency_score +
            weights['coverage'] * self.coverage_score -
            weights['complexity'] * self.complexity_penalty
        )
        
        return max(0.0, min(1.0, score))


@dataclass
class OracleVerdict:
    """Final verdict on test oracle quality"""
    status: OracleStatus
    trust_score: float
    trust_metrics: TrustMetrics
    provenance: List[str]
    weaknesses: List[str]
    recommendations: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RefinementSuggestion:
    """Suggested improvement to test oracle"""
    suggestion_type: str  # 'add_assertion', 'modify_assertion', 'remove_assertion'
    target_assertion: Optional[str]
    proposed_code: str
    rationale: str
    confidence: float


class OracleAnalyzer:
    """Analyzes test oracle quality"""
    
    # Thresholds for status determination
    VERIFIED_THRESHOLD = 0.75
    SUSPICIOUS_THRESHOLD = 0.50
    
    def __init__(self, test_case, differential_report, metadata):
        """
        Args:
            test_case: TestCase from Stage 3
            differential_report: DifferentialReport from Stage 4
            metadata: MUTMetadata from Stage 1
        """
        self.test_case = test_case
        self.diff_report = differential_report
        self.metadata = metadata
    
    def analyze(self) -> OracleVerdict:
        """Perform complete analysis"""
        
        # Compute trust metrics
        trust_metrics = self._compute_trust_metrics()
        overall_trust = trust_metrics.compute_overall()
        
        # Determine status
        status = self._determine_status(overall_trust)
        
        # Identify weaknesses
        weaknesses = self._identify_weaknesses()
        
        # Generate recommendations
        recommendations = self._generate_recommendations(status, weaknesses)
        
        # Build provenance trail
        provenance = self._build_provenance()
        
        return OracleVerdict(
            status=status,
            trust_score=overall_trust,
            trust_metrics=trust_metrics,
            provenance=provenance,
            weaknesses=weaknesses,
            recommendations=recommendations,
            metadata={
                'method_name': self.metadata.name,
                'test_name': self.test_case.test_name,
                'num_assertions': len(self.test_case.assertions),
                'mutants_tested': len(self.diff_report.mutation_results)
            }
        )
    
    def _compute_trust_metrics(self) -> TrustMetrics:
        """Compute individual trust metrics"""
        
        # Mutation score (higher is better)
        mutation_score = self.diff_report.consistency_score
        
        # LLM confidence (average across assertions)
        llm_confidence = sum(a.confidence for a in self.test_case.assertions) / \
                        len(self.test_case.assertions) if self.test_case.assertions else 0.0
        
        # Consistency score (from differential testing)
        consistency_score = self.diff_report.consistency_score
        
        # Coverage score (placeholder - would need actual coverage data)
        coverage_score = 0.8  # Assume decent coverage for now
        
        # Complexity penalty (higher complexity = lower trust)
        complexity_penalty = min(self.metadata.complexity_score / 20.0, 1.0)
        
        return TrustMetrics(
            mutation_score=mutation_score,
            llm_confidence=llm_confidence,
            consistency_score=consistency_score,
            coverage_score=coverage_score,
            complexity_penalty=complexity_penalty
        )
    
    def _determine_status(self, trust_score: float) -> OracleStatus:
        """Determine oracle status based on trust score"""
        
        if trust_score >= self.VERIFIED_THRESHOLD:
            return OracleStatus.VERIFIED
        elif trust_score >= self.SUSPICIOUS_THRESHOLD:
            return OracleStatus.SUSPICIOUS
        else:
            # Check if refinement might help
            if self.diff_report.mutants_survived > self.diff_report.mutants_killed:
                return OracleStatus.NEEDS_REFINEMENT
            else:
                return OracleStatus.REJECTED
    
    def _identify_weaknesses(self) -> List[str]:
        """Identify specific weaknesses in the oracle"""
        weaknesses = []
        
        # Check mutation survival
        if self.diff_report.mutants_survived > 0:
            survival_rate = self.diff_report.mutants_survived / \
                          len(self.diff_report.mutation_results)
            if survival_rate > 0.3:
                weaknesses.append(
                    f"High mutant survival rate ({survival_rate:.1%}) suggests "
                    f"assertions may not be comprehensive"
                )
        
        # Check LLM confidence
        low_conf_assertions = [a for a in self.test_case.assertions if a.confidence < 0.6]
        if low_conf_assertions:
            weaknesses.append(
                f"{len(low_conf_assertions)} assertion(s) have low LLM confidence"
            )
        
        # Check for missing assertion types
        assertion_types = set(a.oracle_type for a in self.test_case.assertions)
        if 'exception' not in assertion_types and self.metadata.complexity_score > 5:
            weaknesses.append("No exception handling assertions for complex method")
        
        # Check discrepancy signals
        for signal in self.diff_report.discrepancy_signals:
            weaknesses.append(f"Differential testing: {signal}")
        
        return weaknesses
    
    def _generate_recommendations(self, status: OracleStatus, 
                                 weaknesses: List[str]) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []
        
        if status == OracleStatus.VERIFIED:
            recommendations.append("Oracle appears reliable - ready for deployment")
            recommendations.append("Consider adding edge case tests for completeness")
        
        elif status == OracleStatus.SUSPICIOUS:
            recommendations.append("Review assertions for completeness")
            recommendations.append("Run additional mutation tests")
            recommendations.append("Consider manual code review")
        
        elif status == OracleStatus.NEEDS_REFINEMENT:
            recommendations.append("Refine assertions to catch more mutants")
            
            # Specific recommendations based on weaknesses
            for weakness in weaknesses:
                if "survival rate" in weakness:
                    recommendations.append(
                        "Add assertions for boundary conditions and edge cases"
                    )
                elif "exception" in weakness:
                    recommendations.append(
                        "Add exception handling and error condition tests"
                    )
                elif "low LLM confidence" in weakness:
                    recommendations.append(
                        "Review low-confidence assertions with domain expert"
                    )
        
        else:  # REJECTED
            recommendations.append("Consider regenerating test with different approach")
            recommendations.append("Manual test writing may be more appropriate")
        
        return recommendations
    
    def _build_provenance(self) -> List[str]:
        """Build audit trail of how this oracle was generated"""
        provenance = []
        
        provenance.append(f"Static analysis: {self.metadata.name}")
        provenance.append(f"LLM generation: {len(self.test_case.assertions)} assertions")
        provenance.append(
            f"Differential testing: {self.diff_report.mutants_killed}/"
            f"{len(self.diff_report.mutation_results)} mutants killed"
        )
        provenance.append(f"Trust analysis: Score {self._compute_trust_metrics().compute_overall():.2f}")
        
        return provenance


class RefinementEngine:
    """Suggests improvements to test oracles"""
    
    def __init__(self, verdict: OracleVerdict, test_case, diff_report):
        self.verdict = verdict
        self.test_case = test_case
        self.diff_report = diff_report
    
    def generate_refinements(self) -> List[RefinementSuggestion]:
        """Generate refinement suggestions"""
        suggestions = []
        
        # Analyze survived mutants to suggest new assertions
        survived_mutants = [
            r for r in self.diff_report.mutation_results if not r.killed
        ]
        
        for mutant in survived_mutants:
            suggestion = self._suggest_assertion_for_mutant(mutant)
            if suggestion:
                suggestions.append(suggestion)
        
        # Suggest removing low-confidence assertions
        for assertion in self.test_case.assertions:
            if assertion.confidence < 0.5:
                suggestions.append(RefinementSuggestion(
                    suggestion_type='remove_assertion',
                    target_assertion=assertion.assertion_code,
                    proposed_code="# Remove low-confidence assertion",
                    rationale=f"LLM confidence too low ({assertion.confidence:.2f})",
                    confidence=0.7
                ))
        
        return suggestions
    
    def _suggest_assertion_for_mutant(self, mutant) -> Optional[RefinementSuggestion]:
        """Suggest assertion that would catch a specific mutant"""
        
        if mutant.mutation_type == 'arithmetic_operator':
            return RefinementSuggestion(
                suggestion_type='add_assertion',
                target_assertion=None,
                proposed_code=f"assert result != <alternative_value>  # Catch arithmetic mutations",
                rationale=f"Would detect {mutant.mutation_type} at {mutant.location}",
                confidence=0.75
            )
        
        elif mutant.mutation_type == 'relational_operator':
            return RefinementSuggestion(
                suggestion_type='add_assertion',
                target_assertion=None,
                proposed_code=f"assert <boundary_check>  # Catch relational mutations",
                rationale=f"Would detect {mutant.mutation_type} at {mutant.location}",
                confidence=0.70
            )
        
        return None


# --- CLI for testing Stage 5 ---
def main():
    import argparse
    import sys
    from stage_1_static_analysis import StaticAnalyzer
    from stage_2_prefix_generation import PrefixGenerator
    from stage_3_llm_assertion_gen import MockLLMProvider, AssertionGenerator
    from stage_4_differential_testing import DifferentialTester
    
    parser = argparse.ArgumentParser(description="Stage 5: Analysis & Refinement")
    parser.add_argument("file", help="Source file")
    parser.add_argument("--method", help="Method name")
    parser.add_argument("--mutants", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    args = parser.parse_args()
    
    try:
        # Run all previous stages
        print("[Stage 1] Analyzing...")
        methods = StaticAnalyzer.analyze(args.file)
        if args.method:
            methods = [m for m in methods if m.name == args.method]
        method = methods[0]
        
        print("[Stage 2] Generating prefix...")
        prefix_gen = PrefixGenerator(method, args.file)
        prefix = prefix_gen.generate()
        
        print("[Stage 3] Generating assertions...")
        provider = MockLLMProvider()
        assertion_gen = AssertionGenerator(provider, method, prefix)
        test_cases = assertion_gen.generate_test_cases(count=1)
        test_case = test_cases[0]
        
        print("[Stage 4] Differential testing...")
        tester = DifferentialTester(args.file, test_case)
        diff_report = tester.run_differential_test(num_mutants=args.mutants)
        
        print("\n[Stage 5] Analysis & Refinement...")
        print("="*60)
        
        # Analyze
        analyzer = OracleAnalyzer(test_case, diff_report, method)
        verdict = analyzer.analyze()
        
        # Generate refinements if needed
        refinements = []
        if verdict.status in [OracleStatus.SUSPICIOUS, OracleStatus.NEEDS_REFINEMENT]:
            engine = RefinementEngine(verdict, test_case, diff_report)
            refinements = engine.generate_refinements()
        
        # Output results
        if args.json:
            output = {
                'status': verdict.status.value,
                'trust_score': verdict.trust_score,
                'metrics': {
                    'mutation_score': verdict.trust_metrics.mutation_score,
                    'llm_confidence': verdict.trust_metrics.llm_confidence,
                    'consistency_score': verdict.trust_metrics.consistency_score,
                    'coverage_score': verdict.trust_metrics.coverage_score,
                    'complexity_penalty': verdict.trust_metrics.complexity_penalty
                },
                'weaknesses': verdict.weaknesses,
                'recommendations': verdict.recommendations,
                'provenance': verdict.provenance,
                'refinements': [
                    {
                        'type': r.suggestion_type,
                        'code': r.proposed_code,
                        'rationale': r.rationale,
                        'confidence': r.confidence
                    }
                    for r in refinements
                ]
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"\n{'='*60}")
            print("ORACLE VERDICT")
            print(f"{'='*60}")
            print(f"Status: {verdict.status.value.upper()}")
            print(f"Trust Score: {verdict.trust_score:.2%}")
            
            print(f"\nTrust Metrics:")
            print(f"  Mutation Score: {verdict.trust_metrics.mutation_score:.2%}")
            print(f"  LLM Confidence: {verdict.trust_metrics.llm_confidence:.2%}")
            print(f"  Consistency: {verdict.trust_metrics.consistency_score:.2%}")
            print(f"  Coverage: {verdict.trust_metrics.coverage_score:.2%}")
            print(f"  Complexity Penalty: {verdict.trust_metrics.complexity_penalty:.2%}")
            
            print(f"\nProvenance Trail:")
            for p in verdict.provenance:
                print(f"  - {p}")
            
            if verdict.weaknesses:
                print(f"\nIdentified Weaknesses:")
                for w in verdict.weaknesses:
                    print(f"  - {w}")
            
            print(f"\nRecommendations:")
            for r in verdict.recommendations:
                print(f"  - {r}")
            
            if refinements:
                print(f"\nRefinement Suggestions ({len(refinements)}):")
                for i, ref in enumerate(refinements, 1):
                    print(f"\n  [{i}] {ref.suggestion_type}")
                    print(f"      {ref.proposed_code}")
                    print(f"      Rationale: {ref.rationale}")
                    print(f"      Confidence: {ref.confidence:.2%}")
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()