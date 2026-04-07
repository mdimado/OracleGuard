"""OracleGuard — Trust-Scored LLM-Based Test Oracle Generation."""

from oracleguard.static_analysis import StaticAnalyzer, MUTMetadata, Parameter
from oracleguard.prefix_generation import (
    PrefixGenerator, BoundaryPrefixGenerator,
    EquivalencePrefixGenerator, AdvancedPrefixGenerator, TestPrefix,
)
from oracleguard.assertion_generation import (
    LLMProvider, OpenAIProvider, MockLLMProvider,
    AssertionGenerator, CandidateAssertion, TestCase,
)
from oracleguard.differential_testing import (
    DifferentialTester, Mutator, DifferentialReport,
    MutationResult, ExecutionTrace, MUTATION_OPERATORS,
)
from oracleguard.analysis import (
    OracleAnalyzer, RefinementEngine, OracleVerdict,
    OracleStatus, TrustMetrics, RefinementSuggestion,
)
from oracleguard.pipeline import OracleGuard, PipelineConfig, PipelineResult

__all__ = [
    'OracleGuard', 'PipelineConfig', 'PipelineResult',
    'StaticAnalyzer', 'MUTMetadata', 'Parameter',
    'PrefixGenerator', 'BoundaryPrefixGenerator',
    'EquivalencePrefixGenerator', 'AdvancedPrefixGenerator', 'TestPrefix',
    'LLMProvider', 'OpenAIProvider', 'MockLLMProvider',
    'AssertionGenerator', 'CandidateAssertion', 'TestCase',
    'DifferentialTester', 'Mutator', 'DifferentialReport',
    'MutationResult', 'ExecutionTrace', 'MUTATION_OPERATORS',
    'OracleAnalyzer', 'RefinementEngine', 'OracleVerdict',
    'OracleStatus', 'TrustMetrics', 'RefinementSuggestion',
]
