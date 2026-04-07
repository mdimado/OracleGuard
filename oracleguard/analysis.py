"""
Stage 5: Analysis & Refinement
Computes oracle trust scores and generates targeted refinement suggestions.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from oracleguard.static_analysis import MUTMetadata
from oracleguard.assertion_generation import TestCase
from oracleguard.differential_testing import DifferentialReport, MutationResult


class OracleStatus(Enum):
    """Trust verdict status."""
    VERIFIED = "verified"
    SUSPICIOUS = "suspicious"
    NEEDS_REFINEMENT = "needs_refinement"
    REJECTED = "rejected"


@dataclass
class TrustMetrics:
    """Individual trust score components."""
    mutation_score: float
    llm_confidence: float
    consistency_score: float
    coverage_score: float
    complexity_penalty: float

    WEIGHTS = {
        'mutation': 0.35,
        'llm': 0.20,
        'consistency': 0.25,
        'coverage': 0.15,
        'complexity': 0.05,
    }

    def compute_overall(self) -> float:
        """Weighted composite trust score T in [0, 1]."""
        score = (
            self.WEIGHTS['mutation'] * self.mutation_score
            + self.WEIGHTS['llm'] * self.llm_confidence
            + self.WEIGHTS['consistency'] * self.consistency_score
            + self.WEIGHTS['coverage'] * self.coverage_score
            - self.WEIGHTS['complexity'] * self.complexity_penalty
        )
        return max(0.0, min(1.0, score))


@dataclass
class RefinementSuggestion:
    """Targeted suggestion to improve a test oracle."""
    suggestion_type: str  # 'add_assertion', 'modify_assertion', 'remove_assertion'
    target_assertion: Optional[str]
    proposed_code: str
    rationale: str
    confidence: float


@dataclass
class OracleVerdict:
    """Final verdict on test oracle quality."""
    status: OracleStatus
    trust_score: float
    trust_metrics: TrustMetrics
    provenance: List[str]
    weaknesses: List[str]
    recommendations: List[str]
    refinements: List[RefinementSuggestion] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class OracleAnalyzer:
    """Analyzes test oracle quality and produces a trust-scored verdict."""

    VERIFIED_THRESHOLD = 0.80
    SUSPICIOUS_THRESHOLD = 0.60
    NEEDS_REFINEMENT_THRESHOLD = 0.40

    def __init__(self, test_case: TestCase, diff_report: DifferentialReport,
                 metadata: MUTMetadata):
        self.test_case = test_case
        self.diff_report = diff_report
        self.metadata = metadata

    def analyze(self) -> OracleVerdict:
        metrics = self._compute_trust_metrics()
        trust_score = metrics.compute_overall()
        status = self._determine_status(trust_score)
        weaknesses = self._identify_weaknesses()
        recommendations = self._generate_recommendations(status, weaknesses)
        provenance = self._build_provenance(metrics)

        refinements = []
        if status != OracleStatus.VERIFIED:
            refinements = RefinementEngine(
                self.test_case, self.diff_report
            ).generate_refinements()

        return OracleVerdict(
            status=status,
            trust_score=trust_score,
            trust_metrics=metrics,
            provenance=provenance,
            weaknesses=weaknesses,
            recommendations=recommendations,
            refinements=refinements,
            metadata={
                'method_name': self.metadata.name,
                'test_name': self.test_case.test_name,
                'num_assertions': len(self.test_case.assertions),
                'mutants_tested': len(self.diff_report.mutation_results),
            },
        )

    def _compute_trust_metrics(self) -> TrustMetrics:
        # Use oracle_kill_rate (assertion-only kills) as the mutation signal.
        # This measures what the oracle itself catches, not what crashes.
        mutation_score = self.diff_report.oracle_kill_rate

        confidences = [a.confidence for a in self.test_case.assertions]
        llm_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Consistency: proportion of oracle kills that are stable (not crashes)
        oracle_kills = sum(1 for r in self.diff_report.mutation_results if r.oracle_killed)
        total = len(self.diff_report.mutation_results)
        consistency_score = oracle_kills / total if total > 0 else 0.0

        assertion_types = {a.oracle_type for a in self.test_case.assertions}
        possible_types = {'value', 'state', 'exception', 'property'}
        coverage_score = len(assertion_types & possible_types) / len(possible_types)

        complexity_penalty = min(self.metadata.complexity_score / 20.0, 1.0)

        return TrustMetrics(
            mutation_score=mutation_score,
            llm_confidence=llm_confidence,
            consistency_score=consistency_score,
            coverage_score=coverage_score,
            complexity_penalty=complexity_penalty,
        )

    def _determine_status(self, trust_score: float) -> OracleStatus:
        if trust_score >= self.VERIFIED_THRESHOLD:
            return OracleStatus.VERIFIED
        if trust_score >= self.SUSPICIOUS_THRESHOLD:
            return OracleStatus.SUSPICIOUS
        if trust_score >= self.NEEDS_REFINEMENT_THRESHOLD:
            return OracleStatus.NEEDS_REFINEMENT
        return OracleStatus.REJECTED

    def _identify_weaknesses(self) -> List[str]:
        weaknesses: List[str] = []
        total = len(self.diff_report.mutation_results)

        if total > 0:
            rate = self.diff_report.mutants_survived / total
            if rate > 0.3:
                weaknesses.append(
                    f"High mutant survival rate ({rate:.0%}) — assertions may not be comprehensive"
                )

        survived_by_type: Dict[str, int] = {}
        for r in self.diff_report.mutation_results:
            if not r.killed:
                survived_by_type[r.mutation_type] = survived_by_type.get(r.mutation_type, 0) + 1

        labels = {
            'arithmetic_operator': 'arithmetic',
            'relational_operator': 'relational/boundary',
            'logical_operator': 'logical condition',
            'constant_replacement': 'value precision',
            'statement_deletion': 'code path coverage',
            'return_value_mutation': 'return value',
        }
        for mtype, count in survived_by_type.items():
            label = labels.get(mtype, mtype)
            weaknesses.append(f"{count} {label} mutant(s) survived — weak {label} assertions")

        low_conf = [a for a in self.test_case.assertions if a.confidence < 0.6]
        if low_conf:
            weaknesses.append(f"{len(low_conf)} assertion(s) have low LLM confidence (<0.6)")

        types = {a.oracle_type for a in self.test_case.assertions}
        if 'exception' not in types and self.metadata.complexity_score > 5:
            weaknesses.append("No exception assertions for a complex method")

        for signal in self.diff_report.discrepancy_signals:
            weaknesses.append(f"Differential signal: {signal}")

        return weaknesses

    def _generate_recommendations(self, status: OracleStatus,
                                  weaknesses: List[str]) -> List[str]:
        recs: List[str] = []
        if status == OracleStatus.VERIFIED:
            recs.append("Oracle appears reliable — ready for adoption")
        elif status == OracleStatus.SUSPICIOUS:
            recs.append("Review assertions for boundary completeness")
            recs.append("Run additional mutation rounds for confidence")
        elif status == OracleStatus.NEEDS_REFINEMENT:
            recs.append("Refine assertions to catch surviving mutants")
            for w in weaknesses:
                if 'relational' in w:
                    recs.append("Add boundary comparison assertions")
                elif 'return value' in w:
                    recs.append("Add direct return-value equality assertions")
                elif 'code path' in w:
                    recs.append("Add assertions covering removed code paths")
                elif 'exception' in w.lower():
                    recs.append("Add exception-handling assertions")
        else:
            recs.append("Consider regenerating with a different LLM or strategy")
            recs.append("Manual oracle writing may be more appropriate")
        return recs

    def _build_provenance(self, metrics: TrustMetrics) -> List[str]:
        return [
            f"Static analysis: {self.metadata.name} (complexity {self.metadata.complexity_score})",
            f"LLM generation: {len(self.test_case.assertions)} assertions",
            f"Differential testing: {self.diff_report.mutants_killed}/"
            f"{len(self.diff_report.mutation_results)} mutants killed",
            f"Trust score: {metrics.compute_overall():.2f}",
        ]


class RefinementEngine:
    """Generates targeted refinement suggestions from surviving mutant patterns."""

    TEMPLATES = {
        'arithmetic_operator': (
            "assert result == <expected_value>",
            "Add exact value assertion to catch arithmetic operator swaps",
        ),
        'relational_operator': (
            "assert result <op> <boundary_value>",
            "Add boundary comparison assertion to catch relational swaps",
        ),
        'logical_operator': (
            "assert <condition_check>",
            "Add condition-specific assertion to catch and/or swaps",
        ),
        'constant_replacement': (
            "assert result == <exact_constant>",
            "Tighten value equality to catch constant perturbations",
        ),
        'statement_deletion': (
            "assert <side_effect_check>",
            "Add assertion covering the effect of the deleted statement",
        ),
        'return_value_mutation': (
            "assert result == <expected> and isinstance(result, <type>)",
            "Add type + value assertion to catch return-value replacement",
        ),
    }

    def __init__(self, test_case: TestCase, diff_report: DifferentialReport):
        self.test_case = test_case
        self.diff_report = diff_report

    def generate_refinements(self) -> List[RefinementSuggestion]:
        suggestions: List[RefinementSuggestion] = []
        for r in self.diff_report.mutation_results:
            if not r.killed:
                s = self._suggest_for_mutant(r)
                if s:
                    suggestions.append(s)
        for a in self.test_case.assertions:
            if a.confidence < 0.4:
                suggestions.append(RefinementSuggestion(
                    suggestion_type='remove_assertion',
                    target_assertion=a.assertion_code,
                    proposed_code="# Remove — too low confidence",
                    rationale=f"LLM confidence is only {a.confidence:.0%}",
                    confidence=0.7,
                ))
        return suggestions

    def _suggest_for_mutant(self, mutant: MutationResult) -> Optional[RefinementSuggestion]:
        template = self.TEMPLATES.get(mutant.mutation_type)
        if not template:
            return None
        code, rationale_prefix = template
        return RefinementSuggestion(
            suggestion_type='add_assertion',
            target_assertion=None,
            proposed_code=code,
            rationale=f"{rationale_prefix} (line {mutant.location[0]}: "
                      f"{mutant.original_code} -> {mutant.mutated_code})",
            confidence=0.75,
        )
