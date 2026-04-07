"""
Stage 4: Differential Testing
Validates test oracles by running them against mutated versions of the code.
Implements all six mutation operator classes with AST-level transformations.
"""

import ast
import sys
import copy
import random
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import tempfile

from oracleguard.assertion_generation import TestCase


@dataclass
class ExecutionTrace:
    """Execution trace for a single test run."""
    trace_id: str
    return_value: Any
    exception: Optional[str]
    covered_lines: List[int] = field(default_factory=list)


@dataclass
class MutationResult:
    """Result of running a test against a single mutant."""
    mutant_id: str
    mutation_type: str
    location: Tuple[int, int]
    original_code: str
    mutated_code: str
    test_passed: bool
    killed: bool              # any failure (crash or assertion) = killed
    trace: Optional[ExecutionTrace] = None
    oracle_killed: bool = False  # only assertion failures count


@dataclass
class DifferentialReport:
    """Report from differential testing."""
    test_name: str
    original_trace: ExecutionTrace
    mutation_results: List[MutationResult]
    mutants_killed: int
    mutants_survived: int
    mutation_score: float       # any failure = killed
    oracle_kill_rate: float     # only assertion failures count
    discrepancy_signals: List[str]


# ---------------------------------------------------------------------------
# Mutation Operators
# ---------------------------------------------------------------------------

class MutationOperator(ast.NodeTransformer):
    """Base class for all mutation operators."""

    def __init__(self):
        self.mutations_applied: List[Dict[str, Any]] = []
        self._candidates: List[Any] = []
        self._target_index: Optional[int] = None
        self._current: int = 0

    def collect_candidates(self, tree: ast.AST) -> list:
        self._candidates = []
        self._collect(tree)
        return self._candidates

    def _collect(self, tree: ast.AST):
        raise NotImplementedError

    def apply(self, tree: ast.AST, target_index: int) -> bool:
        self._target_index = target_index
        self._current = 0
        self.mutations_applied = []
        self.visit(tree)
        ast.fix_missing_locations(tree)
        return len(self.mutations_applied) > 0


class ArithmeticOperatorMutator(MutationOperator):
    """Swap arithmetic operators: + <-> -, * <-> /, % -> +."""

    SWAPS = {
        ast.Add: ast.Sub, ast.Sub: ast.Add,
        ast.Mult: ast.Div, ast.Div: ast.Mult,
        ast.Mod: ast.Add,
    }

    def _collect(self, tree: ast.AST):
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and type(node.op) in self.SWAPS:
                self._candidates.append(node)

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if type(node.op) in self.SWAPS:
            if self._current == self._target_index:
                original = ast.unparse(node)
                node.op = self.SWAPS[type(node.op)]()
                self.mutations_applied.append({
                    'original': original,
                    'mutated': ast.unparse(node),
                    'location': (getattr(node, 'lineno', 0), getattr(node, 'col_offset', 0)),
                })
            self._current += 1
        return node


class RelationalOperatorMutator(MutationOperator):
    """Swap relational operators."""

    SWAPS = {
        ast.Gt: ast.Lt, ast.Lt: ast.Gt,
        ast.GtE: ast.LtE, ast.LtE: ast.GtE,
        ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    }

    def _collect(self, tree: ast.AST):
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                if any(type(op) in self.SWAPS for op in node.ops):
                    self._candidates.append(node)

    def visit_Compare(self, node):
        self.generic_visit(node)
        if any(type(op) in self.SWAPS for op in node.ops):
            if self._current == self._target_index:
                original = ast.unparse(node)
                node.ops = [self.SWAPS.get(type(op), type(op))() for op in node.ops]
                self.mutations_applied.append({
                    'original': original,
                    'mutated': ast.unparse(node),
                    'location': (getattr(node, 'lineno', 0), getattr(node, 'col_offset', 0)),
                })
            self._current += 1
        return node


class LogicalOperatorMutator(MutationOperator):
    """Swap logical operators: and <-> or."""

    def _collect(self, tree: ast.AST):
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp):
                self._candidates.append(node)

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if self._current == self._target_index:
            original = ast.unparse(node)
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            self.mutations_applied.append({
                'original': original,
                'mutated': ast.unparse(node),
                'location': (getattr(node, 'lineno', 0), getattr(node, 'col_offset', 0)),
            })
        self._current += 1
        return node


class ConstantReplacementMutator(MutationOperator):
    """Mutate constants: int +-1, float +-0.1, str append, bool negate."""

    def _collect(self, tree: ast.AST):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
                self._candidates.append(node)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float, str, bool)):
            if self._current == self._target_index:
                original = repr(node.value)
                if isinstance(node.value, bool):
                    node.value = not node.value
                elif isinstance(node.value, int):
                    node.value = node.value + 1 if node.value != 0 else 1
                elif isinstance(node.value, float):
                    node.value = node.value + 0.1
                elif isinstance(node.value, str):
                    node.value = node.value + "x"
                self.mutations_applied.append({
                    'original': original,
                    'mutated': repr(node.value),
                    'location': (getattr(node, 'lineno', 0), getattr(node, 'col_offset', 0)),
                })
            self._current += 1
        return node


class StatementDeletionMutator(MutationOperator):
    """Delete a statement from a function body (replace with pass)."""

    def _collect(self, tree: ast.AST):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for i, stmt in enumerate(node.body):
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                        continue  # skip docstrings
                    self._candidates.append((node, i))

    def apply(self, tree: ast.AST, target_index: int) -> bool:
        self._candidates = []
        self._collect(tree)
        if target_index >= len(self._candidates):
            return False
        func_node, stmt_index = self._candidates[target_index]
        original_stmt = func_node.body[stmt_index]
        original_code = ast.unparse(original_stmt)
        pass_node = ast.Pass()
        ast.copy_location(pass_node, original_stmt)
        func_node.body[stmt_index] = pass_node
        ast.fix_missing_locations(tree)
        self.mutations_applied = [{
            'original': original_code,
            'mutated': 'pass',
            'location': (getattr(original_stmt, 'lineno', 0),
                         getattr(original_stmt, 'col_offset', 0)),
        }]
        return True


class ReturnValueMutator(MutationOperator):
    """Replace return value with a constant (0, None, or empty string)."""

    def _collect(self, tree: ast.AST):
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and node.value is not None:
                self._candidates.append(node)

    def visit_Return(self, node):
        self.generic_visit(node)
        if node.value is not None:
            if self._current == self._target_index:
                original = ast.unparse(node)
                replacement = random.choice([
                    ast.Constant(value=0),
                    ast.Constant(value=None),
                    ast.Constant(value=""),
                ])
                ast.copy_location(replacement, node.value)
                node.value = replacement
                self.mutations_applied.append({
                    'original': original,
                    'mutated': ast.unparse(node),
                    'location': (getattr(node, 'lineno', 0), getattr(node, 'col_offset', 0)),
                })
            self._current += 1
        return node


# Registry of all operators
MUTATION_OPERATORS: Dict[str, type] = {
    'arithmetic_operator': ArithmeticOperatorMutator,
    'relational_operator': RelationalOperatorMutator,
    'logical_operator': LogicalOperatorMutator,
    'constant_replacement': ConstantReplacementMutator,
    'statement_deletion': StatementDeletionMutator,
    'return_value_mutation': ReturnValueMutator,
}


# ---------------------------------------------------------------------------
# Mutant Generator
# ---------------------------------------------------------------------------

class Mutator:
    """Generates code mutants using registered mutation operators."""

    def __init__(self, source_code: str):
        self.source_code = source_code
        self.tree = ast.parse(source_code)

    def generate_mutants(self, count: int = 10) -> List[Dict[str, Any]]:
        mutants: List[Dict[str, Any]] = []
        attempts = 0
        max_attempts = count * 3
        while len(mutants) < count and attempts < max_attempts:
            attempts += 1
            m = self._create_mutant(len(mutants))
            if m:
                mutants.append(m)
        return mutants

    def _create_mutant(self, mutant_id: int) -> Optional[Dict[str, Any]]:
        op_name = random.choice(list(MUTATION_OPERATORS))
        op = MUTATION_OPERATORS[op_name]()

        probe_tree = copy.deepcopy(self.tree)
        candidates = op.collect_candidates(probe_tree)
        if not candidates:
            return None

        target = random.randint(0, len(candidates) - 1)
        tree_copy = copy.deepcopy(self.tree)
        op2 = MUTATION_OPERATORS[op_name]()
        op2.collect_candidates(tree_copy)
        if not op2.apply(tree_copy, target):
            return None

        try:
            mutated_code = ast.unparse(tree_copy)
        except Exception:
            return None

        info = op2.mutations_applied[0]
        return {
            'id': f"mutant_{mutant_id}",
            'type': op_name,
            'location': info['location'],
            'original': info['original'],
            'mutated': info['mutated'],
            'source_code': mutated_code,
        }


# ---------------------------------------------------------------------------
# Differential Tester
# ---------------------------------------------------------------------------

class DifferentialTester:
    """Runs generated tests against original and mutated code."""

    def __init__(self, source_path: str, test_case: TestCase):
        self.source_path = Path(source_path)
        self.test_case = test_case
        self.source_code = self.source_path.read_text()

    def run_differential_test(self, num_mutants: int = 10) -> DifferentialReport:
        original_trace = self._run_test(self.source_code, "original")
        mutants = Mutator(self.source_code).generate_mutants(count=num_mutants)

        results: List[MutationResult] = []
        killed = 0
        oracle_killed = 0
        for mutant in mutants:
            r = self._test_mutant(mutant)
            results.append(r)
            if r.killed:
                killed += 1
            if r.oracle_killed:
                oracle_killed += 1

        total = len(mutants) if mutants else 1
        survived = len(mutants) - killed

        return DifferentialReport(
            test_name=self.test_case.test_name,
            original_trace=original_trace,
            mutation_results=results,
            mutants_killed=killed,
            mutants_survived=survived,
            mutation_score=killed / total,
            oracle_kill_rate=oracle_killed / total,
            discrepancy_signals=self._identify_discrepancies(results),
        )

    def _prepare_test_code(self) -> str:
        """Prepare test code for execution against mutated source.

        1. Strip imports of the module-under-test (functions are in same file).
        2. Wrap the function call in try/except so that mutations which crash
           the function (TypeError, NameError, etc.) are distinguished from
           mutations that produce wrong output caught by assertions.
        """
        module_name = self.source_path.stem
        lines = []
        for line in self.test_case.full_test_code.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"from {module_name} import"):
                continue
            if stripped.startswith(f"import {module_name}"):
                continue
            lines.append(line)
        return "\n".join(lines)

    def _run_test(self, source_code: str, trace_id: str,
                  catch_crashes: bool = False) -> ExecutionTrace:
        """Execute test in an isolated subprocess.

        Args:
            catch_crashes: If True, wrap the function call so that runtime
                crashes (not assertion errors) are silently caught. The test
                then passes — meaning the oracle did NOT detect the fault.
                Used when scoring oracle quality. When False (default),
                any failure counts as a kill (standard mutation testing).
        """
        clean_test = self._prepare_test_code()

        if catch_crashes:
            # Rewrite the test function to wrap the call in try/except.
            # AssertionErrors still propagate (oracle caught the fault),
            # but other exceptions are swallowed (oracle missed it).
            wrapped_lines = []
            in_body = False
            for line in clean_test.splitlines():
                if line.strip().startswith("def "):
                    wrapped_lines.append(line)
                    in_body = True
                    continue
                if in_body and line.strip() and not line.startswith(" "):
                    in_body = False  # left the function
                if in_body:
                    # Indent body inside try, re-raise AssertionError
                    wrapped_lines.append(line)
                else:
                    wrapped_lines.append(line)

            # Simpler approach: add a wrapper that calls the test and
            # distinguishes assertion errors from other exceptions.
            clean_test_with_wrapper = clean_test + f"""

def _run_with_crash_guard():
    try:
        {self.test_case.test_name}()
    except AssertionError:
        raise  # Oracle caught the fault — test fails
    except Exception:
        pass  # Function crashed — oracle did NOT catch it
"""
            call_line = "_run_with_crash_guard()"
        else:
            clean_test_with_wrapper = clean_test
            call_line = f"{self.test_case.test_name}()"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(source_code)
            f.write("\n\n")
            f.write(clean_test_with_wrapper)
            f.write(f"\n\n{call_line}\n")
            temp_path = Path(f.name)
        try:
            result = subprocess.run(
                [sys.executable, str(temp_path)],
                capture_output=True, text=True, timeout=5,
            )
            exception = result.stderr if result.returncode != 0 else None
            return ExecutionTrace(trace_id=trace_id, return_value=None, exception=exception)
        except subprocess.TimeoutExpired:
            return ExecutionTrace(trace_id=trace_id, return_value=None, exception="Timeout")
        finally:
            temp_path.unlink(missing_ok=True)

    def _test_mutant(self, mutant: Dict[str, Any]) -> MutationResult:
        """Test a mutant twice:
        1. Standard mode — any failure = killed (for mutation score).
        2. Crash-guarded mode — only assertion failures = killed (for oracle quality).

        We use standard mode for the kill decision, but record both.
        """
        # Standard: any failure counts as killed
        trace = self._run_test(mutant['source_code'], mutant['id'])
        std_killed = trace.exception is not None

        # Oracle-only: only assertion failures count
        trace_guarded = self._run_test(
            mutant['source_code'], mutant['id'] + "_guarded",
            catch_crashes=True,
        )
        oracle_killed = trace_guarded.exception is not None

        return MutationResult(
            mutant_id=mutant['id'],
            mutation_type=mutant['type'],
            location=mutant['location'],
            original_code=mutant['original'],
            mutated_code=mutant['mutated'],
            test_passed=not std_killed,
            killed=std_killed,
            trace=trace,
            oracle_killed=oracle_killed,
        )

    @staticmethod
    def _identify_discrepancies(results: List[MutationResult]) -> List[str]:
        if not results:
            return []
        discrepancies: List[str] = []
        survived = [r for r in results if not r.killed]
        if len(survived) > len(results) * 0.5:
            discrepancies.append(f"High mutant survival rate: {len(survived)}/{len(results)}")
        by_type: Dict[str, int] = {}
        for r in survived:
            by_type[r.mutation_type] = by_type.get(r.mutation_type, 0) + 1
        for mtype, count in by_type.items():
            if count >= 2:
                discrepancies.append(f"Multiple {mtype} mutants survived ({count})")
        return discrepancies
