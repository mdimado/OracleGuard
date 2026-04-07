"""
Stage 1: Static Analysis
Extracts methods, signatures, dependencies, and types from Python source code.
"""

import ast
from typing import List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Parameter:
    """Represents a method parameter."""
    name: str
    param_type: Optional[str] = None
    default_value: Optional[str] = None


@dataclass
class MUTMetadata:
    """Metadata for Method Under Test (MUT)."""
    name: str
    signature: str
    parameters: List[Parameter]
    dependencies: List[str]
    return_type: Optional[str]
    docstring: Optional[str]
    source_code: str
    line_number: int
    complexity_score: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class PythonAnalyzer:
    """AST-based analyzer for Python source code."""

    def __init__(self, source_path: str):
        self.source_path = Path(source_path)
        self.source_code = self.source_path.read_text()
        self.tree = ast.parse(self.source_code)

    def extract_methods(self) -> List[MUTMetadata]:
        """Extract all function/method definitions from the source."""
        methods = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                methods.append(self._analyze_function(node))
        return methods

    def _analyze_function(self, node: ast.FunctionDef) -> MUTMetadata:
        """Deep analysis of a single function node."""
        parameters = []
        for arg in node.args.args:
            param_type = ast.unparse(arg.annotation) if arg.annotation else None
            parameters.append(Parameter(name=arg.arg, param_type=param_type))

        return_type = ast.unparse(node.returns) if node.returns else None
        docstring = ast.get_docstring(node)
        dependencies = self._extract_dependencies(node)

        source_lines = self.source_code.split('\n')
        func_source = '\n'.join(source_lines[node.lineno - 1:node.end_lineno])
        complexity = self._calculate_complexity(node)

        return MUTMetadata(
            name=node.name,
            signature=self._build_signature(node),
            parameters=parameters,
            dependencies=dependencies,
            return_type=return_type,
            docstring=docstring,
            source_code=func_source,
            line_number=node.lineno,
            complexity_score=complexity,
        )

    def _build_signature(self, node: ast.FunctionDef) -> str:
        """Reconstruct function signature as string."""
        args = []
        for arg in node.args.args:
            s = arg.arg
            if arg.annotation:
                s += f": {ast.unparse(arg.annotation)}"
            args.append(s)
        sig = f"def {node.name}({', '.join(args)})"
        if node.returns:
            sig += f" -> {ast.unparse(node.returns)}"
        return sig + ":"

    def _extract_dependencies(self, node: ast.FunctionDef) -> List[str]:
        """Extract external dependencies (called functions, accessed attributes)."""
        deps = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    deps.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    deps.add(ast.unparse(child.func))
            elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                deps.add(child.value.id)
        return sorted(deps)

    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """Calculate McCabe cyclomatic complexity."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity


class StaticAnalyzer:
    """Main interface for Stage 1."""

    @staticmethod
    def analyze(source_path: str) -> List[MUTMetadata]:
        """Analyze a Python source file and return method metadata."""
        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        if path.suffix != '.py':
            raise ValueError(f"Only Python files are supported, got: {path.suffix}")
        return PythonAnalyzer(source_path).extract_methods()

    @staticmethod
    def filter_methods(methods: List[MUTMetadata],
                       min_complexity: int = 2,
                       max_complexity: int = 20) -> List[MUTMetadata]:
        """Filter methods based on complexity range."""
        return [
            m for m in methods
            if min_complexity <= m.complexity_score <= max_complexity
        ]
