"""
Stage 1: Static Analysis
Extracts methods, signatures, dependencies, and types from source code.
Supports Python (.py) and Java (.java) files.
"""

import ast
import inspect
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import sys
from pathlib import Path


@dataclass
class Parameter:
    """Represents a method parameter"""
    name: str
    param_type: Optional[str] = None
    default_value: Optional[str] = None


@dataclass
class MUTMetadata:
    """Metadata for Method Under Test (MUT)"""
    name: str
    signature: str
    parameters: List[Parameter]
    dependencies: List[str]
    return_type: Optional[str]
    docstring: Optional[str]
    source_code: str
    line_number: int
    complexity_score: int = 0


class PythonAnalyzer:
    """AST-based analyzer for Python source code"""
    
    def __init__(self, source_path: str):
        self.source_path = Path(source_path)
        self.source_code = self.source_path.read_text()
        self.tree = ast.parse(self.source_code)
        
    def extract_methods(self) -> List[MUTMetadata]:
        """Extract all function/method definitions from the source"""
        methods = []
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                metadata = self._analyze_function(node)
                methods.append(metadata)
                
        return methods
    
    def _analyze_function(self, node: ast.FunctionDef) -> MUTMetadata:
        """Deep analysis of a single function node"""
        
        # Extract parameters
        parameters = []
        for arg in node.args.args:
            param_type = None
            if arg.annotation:
                param_type = ast.unparse(arg.annotation)
            parameters.append(Parameter(
                name=arg.arg,
                param_type=param_type
            ))
        
        # Extract return type
        return_type = None
        if node.returns:
            return_type = ast.unparse(node.returns)
        
        # Extract docstring
        docstring = ast.get_docstring(node)
        
        # Extract dependencies (imported modules, external calls)
        dependencies = self._extract_dependencies(node)
        
        # Get source code for this function
        source_lines = self.source_code.split('\n')
        func_source = '\n'.join(source_lines[node.lineno-1:node.end_lineno])
        
        # Calculate complexity (simple McCabe cyclomatic complexity)
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
            complexity_score=complexity
        )
    
    def _build_signature(self, node: ast.FunctionDef) -> str:
        """Reconstruct function signature as string"""
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            args.append(arg_str)
        
        sig = f"def {node.name}({', '.join(args)})"
        if node.returns:
            sig += f" -> {ast.unparse(node.returns)}"
        sig += ":"
        return sig
    
    def _extract_dependencies(self, node: ast.FunctionDef) -> List[str]:
        """Extract external dependencies (imported modules, called functions)"""
        dependencies = set()
        
        for child in ast.walk(node):
            # Function calls
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    dependencies.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    dependencies.add(ast.unparse(child.func))
            
            # Attribute access (e.g., obj.method)
            elif isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name):
                    dependencies.add(child.value.id)
        
        return sorted(list(dependencies))
    
    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """Calculate McCabe cyclomatic complexity"""
        complexity = 1  # Base complexity
        
        for child in ast.walk(node):
            # Decision points increase complexity
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        
        return complexity


class JavaAnalyzer:
    """Analyzer for Java source code (placeholder for javalang integration)"""
    
    def __init__(self, source_path: str):
        self.source_path = Path(source_path)
        self.source_code = self.source_path.read_text()
        
    def extract_methods(self) -> List[MUTMetadata]:
        """Extract methods from Java source"""
        # TODO: Integrate javalang library
        # import javalang
        # tree = javalang.parse.parse(self.source_code)
        
        print("[!] Java analysis not yet implemented. Use javalang library.")
        return []


class StaticAnalyzer:
    """Main interface for Stage 1"""
    
    @staticmethod
    def analyze(source_path: str) -> List[MUTMetadata]:
        """Factory method to analyze source file based on extension"""
        path = Path(source_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        
        if path.suffix == '.py':
            analyzer = PythonAnalyzer(source_path)
        elif path.suffix == '.java':
            analyzer = JavaAnalyzer(source_path)
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")
        
        return analyzer.extract_methods()
    
    @staticmethod
    def filter_methods(methods: List[MUTMetadata], 
                      min_complexity: int = 2,
                      max_complexity: int = 20) -> List[MUTMetadata]:
        """Filter methods based on complexity (avoid trivial and overly complex)"""
        return [
            m for m in methods 
            if min_complexity <= m.complexity_score <= max_complexity
        ]


# --- CLI for testing Stage 1 ---
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Stage 1: Static Analysis")
    parser.add_argument("file", help="Source file to analyze (.py or .java)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--min-complexity", type=int, default=2)
    
    args = parser.parse_args()
    
    try:
        methods = StaticAnalyzer.analyze(args.file)
        methods = StaticAnalyzer.filter_methods(methods, min_complexity=args.min_complexity)
        
        if args.json:
            import json
            output = [asdict(m) for m in methods]
            # Convert Parameter objects to dicts
            for method in output:
                method['parameters'] = [
                    {'name': p.name, 'param_type': p.param_type, 'default_value': p.default_value}
                    if isinstance(p, Parameter) else p
                    for p in method['parameters']
                ]
            print(json.dumps(output, indent=2))
        else:
            print(f"\n[*] Found {len(methods)} methods in {args.file}\n")
            for method in methods:
                print(f"Method: {method.name}")
                print(f"  Signature: {method.signature}")
                print(f"  Parameters: {[p.name for p in method.parameters]}")
                print(f"  Return Type: {method.return_type}")
                print(f"  Complexity: {method.complexity_score}")
                print(f"  Dependencies: {method.dependencies}")
                print(f"  Docstring: {method.docstring[:50] + '...' if method.docstring else 'None'}")
                print()
                
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()