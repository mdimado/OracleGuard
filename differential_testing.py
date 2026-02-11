"""
Stage 4: Differential Testing
Validates test oracles by running them against mutated versions of the code.
Uses execution tracing and mutation testing to detect discrepancies.
"""

import ast
import sys
import copy
import random
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
import json


@dataclass
class ExecutionTrace:
    """Execution trace for a single test run"""
    trace_id: str
    steps: List[Dict[str, Any]]  # Line-by-line execution steps
    return_value: Any
    exception: Optional[str]
    coverage: Dict[str, List[int]]  # File -> line numbers covered


@dataclass
class MutationResult:
    """Result of running test against a mutant"""
    mutant_id: str
    mutation_type: str
    location: Tuple[int, int]  # (line, column)
    original_code: str
    mutated_code: str
    test_passed: bool
    trace: Optional[ExecutionTrace]
    killed: bool  # Whether test killed the mutant


@dataclass
class DifferentialReport:
    """Report from differential testing"""
    test_name: str
    original_trace: ExecutionTrace
    mutation_results: List[MutationResult]
    mutants_killed: int
    mutants_survived: int
    consistency_score: float  # 0.0 to 1.0
    discrepancy_signals: List[str]


class ExecutionTracer:
    """Traces Python code execution"""
    
    def __init__(self):
        self.trace = []
        self.coverage = {}
        
    def trace_calls(self, frame, event, arg):
        """Trace function for sys.settrace"""
        if event == 'line':
            filename = frame.f_code.co_filename
            lineno = frame.f_lineno
            
            if filename not in self.coverage:
                self.coverage[filename] = []
            
            if lineno not in self.coverage[filename]:
                self.coverage[filename].append(lineno)
            
            # Record execution step
            step = {
                'line': lineno,
                'file': filename,
                'function': frame.f_code.co_name,
                'locals': dict(frame.f_locals)
            }
            self.trace.append(step)
        
        return self.trace_calls
    
    def start_trace(self):
        """Begin tracing"""
        self.trace = []
        self.coverage = {}
        sys.settrace(self.trace_calls)
    
    def stop_trace(self):
        """End tracing"""
        sys.settrace(None)
    
    def get_execution_trace(self, trace_id: str, return_value: Any = None, 
                          exception: Optional[str] = None) -> ExecutionTrace:
        """Build execution trace object"""
        return ExecutionTrace(
            trace_id=trace_id,
            steps=self.trace,
            return_value=return_value,
            exception=exception,
            coverage=self.coverage
        )


class Mutator:
    """Generates code mutations"""
    
    MUTATION_OPERATORS = [
        'arithmetic_operator',
        'relational_operator', 
        'logical_operator',
        'constant_replacement',
        'statement_deletion',
        'return_value_mutation'
    ]
    
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.tree = ast.parse(source_code)
        
    def generate_mutants(self, count: int = 10) -> List[Dict[str, Any]]:
        """Generate multiple mutants"""
        mutants = []
        
        for i in range(count):
            mutant = self._create_mutant(i)
            if mutant:
                mutants.append(mutant)
        
        return mutants
    
    def _create_mutant(self, mutant_id: int) -> Optional[Dict[str, Any]]:
        """Create a single mutant"""
        mutation_type = random.choice(self.MUTATION_OPERATORS)
        
        # Create a mutable copy of the AST
        mutant_tree = copy.deepcopy(self.tree)
        
        # Apply mutation
        mutator_visitor = MutationVisitor(mutation_type)
        mutator_visitor.visit(mutant_tree)
        
        if not mutator_visitor.mutation_applied:
            return None
        
        # Convert back to source code
        try:
            mutated_code = ast.unparse(mutant_tree)
        except:
            return None
        
        return {
            'id': f"mutant_{mutant_id}",
            'type': mutation_type,
            'location': mutator_visitor.mutation_location,
            'original': mutator_visitor.original_code,
            'mutated': mutator_visitor.mutated_code,
            'source_code': mutated_code
        }


class MutationVisitor(ast.NodeTransformer):
    """AST visitor that applies mutations"""
    
    def __init__(self, mutation_type: str):
        self.mutation_type = mutation_type
        self.mutation_applied = False
        self.mutation_location = (0, 0)
        self.original_code = ""
        self.mutated_code = ""
        self.nodes_visited = 0
        self.target_node = random.randint(0, 10)  # Randomly select which node to mutate
    
    def visit_BinOp(self, node):
        """Mutate binary operators"""
        if self.mutation_type == 'arithmetic_operator' and not self.mutation_applied:
            self.nodes_visited += 1
            if self.nodes_visited == self.target_node:
                self.mutation_applied = True
                self.mutation_location = (getattr(node, 'lineno', 0), 
                                         getattr(node, 'col_offset', 0))
                
                # Arithmetic operator mutations
                mutations = {
                    ast.Add: ast.Sub,
                    ast.Sub: ast.Add,
                    ast.Mult: ast.Div,
                    ast.Div: ast.Mult,
                    ast.Mod: ast.Add
                }
                
                old_op = type(node.op)
                if old_op in mutations:
                    self.original_code = ast.unparse(node)
                    node.op = mutations[old_op]()
                    self.mutated_code = ast.unparse(node)
        
        return self.generic_visit(node)
    
    def visit_Compare(self, node):
        """Mutate comparison operators"""
        if self.mutation_type == 'relational_operator' and not self.mutation_applied:
            self.nodes_visited += 1
            if self.nodes_visited == self.target_node:
                self.mutation_applied = True
                self.mutation_location = (getattr(node, 'lineno', 0), 
                                         getattr(node, 'col_offset', 0))
                
                # Relational operator mutations
                mutations = {
                    ast.Gt: ast.Lt,
                    ast.Lt: ast.Gt,
                    ast.GtE: ast.LtE,
                    ast.LtE: ast.GtE,
                    ast.Eq: ast.NotEq,
                    ast.NotEq: ast.Eq
                }
                
                if node.ops:
                    old_op = type(node.ops[0])
                    if old_op in mutations:
                        self.original_code = ast.unparse(node)
                        node.ops[0] = mutations[old_op]()
                        self.mutated_code = ast.unparse(node)
        
        return self.generic_visit(node)
    
    def visit_Constant(self, node):
        """Mutate constants"""
        if self.mutation_type == 'constant_replacement' and not self.mutation_applied:
            self.nodes_visited += 1
            if self.nodes_visited == self.target_node:
                self.mutation_applied = True
                self.mutation_location = (getattr(node, 'lineno', 0), 
                                         getattr(node, 'col_offset', 0))
                
                self.original_code = str(node.value)
                
                # Mutate based on type
                if isinstance(node.value, int):
                    node.value = node.value + 1 if node.value != 0 else 1
                elif isinstance(node.value, float):
                    node.value = node.value + 0.1
                elif isinstance(node.value, str):
                    node.value = node.value + "x"
                elif isinstance(node.value, bool):
                    node.value = not node.value
                
                self.mutated_code = str(node.value)
        
        return node


class DifferentialTester:
    """Main differential testing engine"""
    
    def __init__(self, source_path: str, test_case):
        """
        Args:
            source_path: Path to source code
            test_case: TestCase from Stage 3
        """
        self.source_path = Path(source_path)
        self.test_case = test_case
        self.source_code = self.source_path.read_text()
        
    def run_differential_test(self, num_mutants: int = 10) -> DifferentialReport:
        """Run differential testing with mutants"""
        
        print(f"[*] Running original code...")
        original_trace = self._run_test_with_trace(self.source_code, "original")
        
        print(f"[*] Generating {num_mutants} mutants...")
        mutator = Mutator(self.source_code)
        mutants = mutator.generate_mutants(count=num_mutants)
        
        print(f"[*] Generated {len(mutants)} mutants")
        
        mutation_results = []
        killed_count = 0
        
        for mutant in mutants:
            print(f"  - Testing {mutant['id']}...")
            result = self._test_mutant(mutant, original_trace)
            mutation_results.append(result)
            
            if result.killed:
                killed_count += 1
        
        survived_count = len(mutants) - killed_count
        
        # Calculate consistency score
        consistency_score = killed_count / len(mutants) if mutants else 0.0
        
        # Identify discrepancies
        discrepancies = self._identify_discrepancies(original_trace, mutation_results)
        
        return DifferentialReport(
            test_name=self.test_case.test_name,
            original_trace=original_trace,
            mutation_results=mutation_results,
            mutants_killed=killed_count,
            mutants_survived=survived_count,
            consistency_score=consistency_score,
            discrepancy_signals=discrepancies
        )
    
    def _run_test_with_trace(self, source_code: str, trace_id: str) -> ExecutionTrace:
        """Execute test and capture trace"""
        
        # Create temporary file with test code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(source_code)
            f.write("\n\n")
            f.write(self.test_case.full_test_code)
            f.write(f"\n\n{self.test_case.test_name}()")
            temp_file = f.name
        
        try:
            # Execute in subprocess to isolate
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            exception = None
            if result.returncode != 0:
                exception = result.stderr
            
            # For now, return a simplified trace
            return ExecutionTrace(
                trace_id=trace_id,
                steps=[],
                return_value=None,
                exception=exception,
                coverage={}
            )
            
        except subprocess.TimeoutExpired:
            return ExecutionTrace(
                trace_id=trace_id,
                steps=[],
                return_value=None,
                exception="Timeout",
                coverage={}
            )
        finally:
            Path(temp_file).unlink()
    
    def _test_mutant(self, mutant: Dict, original_trace: ExecutionTrace) -> MutationResult:
        """Test a single mutant"""
        
        mutant_trace = self._run_test_with_trace(mutant['source_code'], mutant['id'])
        
        # Check if test killed the mutant (assertions failed)
        test_passed = mutant_trace.exception is None
        
        # Mutant is killed if test failed (assertions caught the bug)
        killed = not test_passed
        
        return MutationResult(
            mutant_id=mutant['id'],
            mutation_type=mutant['type'],
            location=mutant['location'],
            original_code=mutant['original'],
            mutated_code=mutant['mutated'],
            test_passed=test_passed,
            trace=mutant_trace,
            killed=killed
        )
    
    def _identify_discrepancies(self, original: ExecutionTrace, 
                               results: List[MutationResult]) -> List[str]:
        """Identify concerning patterns"""
        discrepancies = []
        
        # Check for high survival rate
        survived = sum(1 for r in results if not r.killed)
        if survived > len(results) * 0.5:
            discrepancies.append(f"High mutant survival rate: {survived}/{len(results)}")
        
        # Check for specific mutation types that survived
        survived_by_type = {}
        for result in results:
            if not result.killed:
                survived_by_type[result.mutation_type] = \
                    survived_by_type.get(result.mutation_type, 0) + 1
        
        for mut_type, count in survived_by_type.items():
            if count >= 2:
                discrepancies.append(f"Multiple {mut_type} mutants survived ({count})")
        
        return discrepancies


# --- CLI for testing Stage 4 ---
def main():
    import argparse
    from stage_1_static_analysis import StaticAnalyzer
    from stage_2_prefix_generation import PrefixGenerator
    from stage_3_llm_assertion_gen import MockLLMProvider, AssertionGenerator
    
    parser = argparse.ArgumentParser(description="Stage 4: Differential Testing")
    parser.add_argument("file", help="Source file")
    parser.add_argument("--method", help="Method name")
    parser.add_argument("--mutants", type=int, default=5, help="Number of mutants")
    
    args = parser.parse_args()
    
    try:
        # Run previous stages
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
        
        print("\n[Stage 4] Running Differential Testing...")
        print("="*60)
        
        tester = DifferentialTester(args.file, test_case)
        report = tester.run_differential_test(num_mutants=args.mutants)
        
        # Display results
        print(f"\n{'='*60}")
        print("DIFFERENTIAL TESTING REPORT")
        print(f"{'='*60}")
        print(f"Test: {report.test_name}")
        print(f"Mutants Killed: {report.mutants_killed}")
        print(f"Mutants Survived: {report.mutants_survived}")
        print(f"Consistency Score: {report.consistency_score:.2%}")
        print(f"\nDiscrepancy Signals:")
        for signal in report.discrepancy_signals:
            print(f"  - {signal}")
        
        print(f"\n{'='*60}")
        print("Mutation Results:")
        print(f"{'='*60}")
        for result in report.mutation_results:
            status = "KILLED" if result.killed else "SURVIVED"
            print(f"\n{result.mutant_id} [{status}]")
            print(f"  Type: {result.mutation_type}")
            print(f"  Location: Line {result.location[0]}")
            print(f"  Change: {result.original_code} -> {result.mutated_code}")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()