"""
Stage 2: Test Prefix Generation
Generates the setup/fixture code needed before calling the Method Under Test (MUT).
Handles dependency instantiation, parameter generation, and mock setup.
"""

import ast
import random
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path
import importlib.util
import sys


@dataclass
class TestPrefix:
    """Generated test prefix/setup code"""
    setup_code: str
    variable_bindings: Dict[str, Any]  # Variable name -> value mapping
    imports: List[str]
    fixture_objects: List[str]  # Names of instantiated objects


class PrefixGenerator:
    """Generates test prefixes for Python methods"""
    
    def __init__(self, metadata, source_path: str):
        """
        Args:
            metadata: MUTMetadata from Stage 1
            source_path: Original source file path (for imports)
        """
        self.metadata = metadata
        self.source_path = Path(source_path)
        self.module = None
        
    def generate(self) -> TestPrefix:
        """Generate complete test prefix"""
        imports = self._generate_imports()
        setup_code_lines = []
        variable_bindings = {}
        fixture_objects = []
        
        # 1. Import the module under test
        setup_code_lines.extend(imports)
        setup_code_lines.append("")
        
        # 2. Instantiate any class if this is a method (not standalone function)
        class_instance = self._generate_class_instance()
        if class_instance:
            setup_code_lines.append(class_instance['code'])
            fixture_objects.append(class_instance['name'])
            variable_bindings[class_instance['name']] = None  # Placeholder
        
        # 3. Generate parameter values
        param_setup = self._generate_parameter_values()
        setup_code_lines.extend(param_setup['code'])
        variable_bindings.update(param_setup['bindings'])
        
        # 4. Mock external dependencies if needed
        mock_setup = self._generate_mocks()
        if mock_setup:
            setup_code_lines.extend(mock_setup)
        
        setup_code = "\n".join(setup_code_lines)
        
        return TestPrefix(
            setup_code=setup_code,
            variable_bindings=variable_bindings,
            imports=imports,
            fixture_objects=fixture_objects
        )
    
    def _generate_imports(self) -> List[str]:
        """Generate necessary import statements"""
        imports = []
        
        # Import the module containing the MUT
        module_name = self.source_path.stem
        imports.append(f"from {module_name} import *")
        
        # Import common testing utilities
        imports.append("import unittest")
        imports.append("from unittest.mock import Mock, patch")
        
        # Import type hints if used
        if any(p.param_type for p in self.metadata.parameters):
            imports.append("from typing import *")
        
        return imports
    
    def _generate_class_instance(self) -> Optional[Dict[str, Any]]:
        """Generate code to instantiate class if MUT is a method"""
        # Check if this is a class method by looking at dependencies or context
        # For now, we'll use heuristics
        
        # If 'self' is first parameter, it's an instance method
        if self.metadata.parameters and self.metadata.parameters[0].name == 'self':
            class_name = "TestClass"  # Default name
            instance_name = "obj"
            
            code = f"{instance_name} = {class_name}()"
            
            return {
                'name': instance_name,
                'code': code
            }
        
        return None
    
    def _generate_parameter_values(self) -> Dict[str, Any]:
        """Generate realistic parameter values based on types"""
        code_lines = []
        bindings = {}
        
        for param in self.metadata.parameters:
            if param.name == 'self':
                continue  # Skip self parameter
            
            var_name = f"arg_{param.name}"
            value, value_code = self._generate_value_for_type(param.param_type, param.name)
            
            code_lines.append(f"{var_name} = {value_code}")
            bindings[var_name] = value
        
        return {
            'code': code_lines,
            'bindings': bindings
        }
    
    def _generate_value_for_type(self, param_type: Optional[str], param_name: str) -> tuple:
        """Generate a value based on parameter type annotation"""
        
        # Type-based generation
        if param_type:
            type_lower = param_type.lower()
            
            if 'int' in type_lower:
                value = random.randint(1, 100)
                return value, str(value)
            
            elif 'float' in type_lower:
                value = round(random.uniform(0.0, 100.0), 2)
                return value, str(value)
            
            elif 'str' in type_lower:
                value = f"test_{param_name}"
                return value, f'"{value}"'
            
            elif 'bool' in type_lower:
                value = random.choice([True, False])
                return value, str(value)
            
            elif 'list' in type_lower:
                value = [1, 2, 3]
                return value, str(value)
            
            elif 'dict' in type_lower:
                value = {'key': 'value'}
                return value, str(value)
            
            elif 'none' in type_lower:
                return None, "None"
        
        # Name-based heuristics (if no type annotation)
        param_lower = param_name.lower()
        
        if 'count' in param_lower or 'num' in param_lower or 'id' in param_lower:
            value = random.randint(1, 100)
            return value, str(value)
        
        elif 'name' in param_lower or 'text' in param_lower or 'msg' in param_lower:
            value = f"test_{param_name}"
            return value, f'"{value}"'
        
        elif 'flag' in param_lower or 'enabled' in param_lower:
            value = True
            return value, str(value)
        
        # Default: None
        return None, "None"
    
    def _generate_mocks(self) -> List[str]:
        """Generate mock objects for external dependencies"""
        mock_lines = []
        
        # Identify dependencies that need mocking
        for dep in self.metadata.dependencies:
            # Skip built-in functions
            if dep in ['print', 'len', 'str', 'int', 'float', 'list', 'dict']:
                continue
            
            # Check if it looks like an external call
            if '.' in dep or dep[0].isupper():
                mock_name = f"mock_{dep.replace('.', '_')}"
                mock_lines.append(f"{mock_name} = Mock()")
        
        return mock_lines


class AdvancedPrefixGenerator(PrefixGenerator):
    """Extended prefix generator with more sophisticated strategies"""
    
    def __init__(self, metadata, source_path: str, strategy: str = "random"):
        """
        Args:
            strategy: 'random', 'boundary', 'equivalence', 'symbolic'
        """
        super().__init__(metadata, source_path)
        self.strategy = strategy
    
    def generate_multiple(self, count: int = 3) -> List[TestPrefix]:
        """Generate multiple test prefixes with different input strategies"""
        prefixes = []
        
        for i in range(count):
            # Vary the generation strategy
            if self.strategy == 'boundary':
                prefix = self._generate_boundary_values()
            elif self.strategy == 'equivalence':
                prefix = self._generate_equivalence_partition()
            else:
                prefix = self.generate()
            
            prefixes.append(prefix)
        
        return prefixes
    
    def _generate_boundary_values(self) -> TestPrefix:
        """Generate boundary value test cases"""
        # Override value generation to use boundary values
        # e.g., 0, -1, MAX_INT, empty string, None, etc.
        
        original_method = self._generate_value_for_type
        
        def boundary_value_generator(param_type: Optional[str], param_name: str):
            if param_type and 'int' in param_type.lower():
                value = random.choice([0, -1, 1, sys.maxsize])
                return value, str(value)
            elif param_type and 'str' in param_type.lower():
                value = random.choice(['', 'a', 'A' * 1000])
                return value, f'"{value}"'
            elif param_type and 'list' in param_type.lower():
                value = random.choice([[], [1], list(range(100))])
                return value, str(value)
            else:
                return original_method(param_type, param_name)
        
        self._generate_value_for_type = boundary_value_generator
        result = self.generate()
        self._generate_value_for_type = original_method
        
        return result
    
    def _generate_equivalence_partition(self) -> TestPrefix:
        """Generate test cases based on equivalence partitioning"""
        # Similar to boundary but focuses on representative values
        # from different equivalence classes
        return self.generate()


# --- CLI for testing Stage 2 ---
def main():
    import argparse
    import json
    from stage_1_static_analysis import StaticAnalyzer
    
    parser = argparse.ArgumentParser(description="Stage 2: Test Prefix Generation")
    parser.add_argument("file", help="Source file to analyze")
    parser.add_argument("--method", help="Specific method name to generate prefix for")
    parser.add_argument("--count", type=int, default=1, help="Number of prefixes to generate")
    parser.add_argument("--strategy", choices=['random', 'boundary', 'equivalence'], 
                       default='random', help="Generation strategy")
    
    args = parser.parse_args()
    
    try:
        # Run Stage 1 to get method metadata
        methods = StaticAnalyzer.analyze(args.file)
        
        if args.method:
            methods = [m for m in methods if m.name == args.method]
            if not methods:
                print(f"Method '{args.method}' not found!")
                sys.exit(1)
        
        for method in methods:
            print(f"\n{'='*60}")
            print(f"Method: {method.name}")
            print(f"{'='*60}\n")
            
            if args.strategy == 'random':
                generator = PrefixGenerator(method, args.file)
            else:
                generator = AdvancedPrefixGenerator(method, args.file, strategy=args.strategy)
            
            if args.count > 1 and hasattr(generator, 'generate_multiple'):
                prefixes = generator.generate_multiple(args.count)
            else:
                prefixes = [generator.generate() for _ in range(args.count)]
            
            for i, prefix in enumerate(prefixes, 1):
                print(f"--- Test Prefix {i} ---")
                print(prefix.setup_code)
                print(f"\nVariable Bindings: {prefix.variable_bindings}")
                print(f"Fixture Objects: {prefix.fixture_objects}")
                print()
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()