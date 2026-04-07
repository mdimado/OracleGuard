"""
Stage 2: Test Prefix Generation
Generates the setup/fixture code needed before calling the Method Under Test.
"""

import random
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

from oracleguard.static_analysis import MUTMetadata


@dataclass
class TestPrefix:
    """Generated test prefix/setup code."""
    setup_code: str
    variable_bindings: Dict[str, Any]
    imports: List[str]
    fixture_objects: List[str]


class PrefixGenerator:
    """Generates test prefixes for Python methods using random values."""

    def __init__(self, metadata: MUTMetadata, source_path: str):
        self.metadata = metadata
        self.source_path = Path(source_path)

    def generate(self) -> TestPrefix:
        """Generate a complete test prefix."""
        imports = self._generate_imports()
        setup_lines = list(imports) + [""]
        variable_bindings: Dict[str, Any] = {}
        fixture_objects: List[str] = []

        inst = self._generate_class_instance()
        if inst:
            setup_lines.append(inst['code'])
            fixture_objects.append(inst['name'])
            variable_bindings[inst['name']] = None

        param_setup = self._generate_parameter_values()
        setup_lines.extend(param_setup['code'])
        variable_bindings.update(param_setup['bindings'])

        mock_setup = self._generate_mocks()
        if mock_setup:
            setup_lines.extend(mock_setup)

        return TestPrefix(
            setup_code="\n".join(setup_lines),
            variable_bindings=variable_bindings,
            imports=imports,
            fixture_objects=fixture_objects,
        )

    def _generate_imports(self) -> List[str]:
        module_name = self.source_path.stem
        imports = [
            f"from {module_name} import *",
            "import unittest",
            "from unittest.mock import Mock, patch",
        ]
        if any(p.param_type for p in self.metadata.parameters):
            imports.append("from typing import *")
        return imports

    def _generate_class_instance(self) -> Optional[Dict[str, Any]]:
        if self.metadata.parameters and self.metadata.parameters[0].name == 'self':
            return {'name': 'obj', 'code': 'obj = TestClass()'}
        return None

    def _generate_parameter_values(self) -> Dict[str, Any]:
        code_lines: List[str] = []
        bindings: Dict[str, Any] = {}
        for param in self.metadata.parameters:
            if param.name == 'self':
                continue
            var_name = f"arg_{param.name}"
            value, value_code = self._generate_value_for_type(param.param_type, param.name)
            code_lines.append(f"{var_name} = {value_code}")
            bindings[var_name] = value
        return {'code': code_lines, 'bindings': bindings}

    def _generate_value_for_type(self, param_type: Optional[str], param_name: str) -> tuple:
        """Generate a value based on parameter type annotation or name heuristics."""
        if param_type:
            t = param_type.lower()
            if 'int' in t:
                v = random.randint(1, 100)
                return v, str(v)
            if 'float' in t:
                v = round(random.uniform(0.0, 100.0), 2)
                return v, str(v)
            if 'str' in t:
                v = f"test_{param_name}"
                return v, f'"{v}"'
            if 'bool' in t:
                v = random.choice([True, False])
                return v, str(v)
            if 'list' in t:
                return [1, 2, 3], "[1, 2, 3]"
            if 'dict' in t:
                return {'key': 'value'}, "{'key': 'value'}"
            if 'none' in t:
                return None, "None"

        name = param_name.lower()
        if any(k in name for k in ('count', 'num', 'id', 'index', 'size')):
            v = random.randint(1, 100)
            return v, str(v)
        if any(k in name for k in ('name', 'text', 'msg', 'label', 'title')):
            v = f"test_{param_name}"
            return v, f'"{v}"'
        if any(k in name for k in ('flag', 'enabled', 'is_', 'has_')):
            return True, "True"

        return None, "None"

    def _generate_mocks(self) -> List[str]:
        builtins = {'print', 'len', 'str', 'int', 'float', 'list', 'dict',
                     'range', 'enumerate', 'zip', 'map', 'filter', 'sorted',
                     'min', 'max', 'sum', 'abs', 'round', 'isinstance', 'type'}
        lines = []
        for dep in self.metadata.dependencies:
            if dep in builtins:
                continue
            if '.' in dep or dep[0].isupper():
                lines.append(f"mock_{dep.replace('.', '_')} = Mock()")
        return lines


class BoundaryPrefixGenerator(PrefixGenerator):
    """Generates test prefixes using boundary/edge-case values."""

    def _generate_value_for_type(self, param_type: Optional[str], param_name: str) -> tuple:
        if param_type:
            t = param_type.lower()
            if 'int' in t:
                v = random.choice([0, -1, 1, 2**31 - 1, -(2**31)])
                return v, str(v)
            if 'float' in t:
                v = random.choice([0.0, -0.1, float('inf'), -float('inf'), 1e-10])
                return v, str(v)
            if 'str' in t:
                v = random.choice(['', ' ', 'a', 'A' * 256])
                return v, f'"{v}"'
            if 'bool' in t:
                return False, "False"
            if 'list' in t:
                v = random.choice([[], [0], list(range(100))])
                return v, str(v)
        return super()._generate_value_for_type(param_type, param_name)


class EquivalencePrefixGenerator(PrefixGenerator):
    """Generates test prefixes using equivalence partitioning."""

    def _generate_value_for_type(self, param_type: Optional[str], param_name: str) -> tuple:
        if param_type:
            t = param_type.lower()
            if 'int' in t:
                v = random.choice([-10, 0, 5, 1000])
                return v, str(v)
            if 'float' in t:
                v = random.choice([-1.5, 0.0, 0.5, 50.0, 99.99])
                return v, str(v)
            if 'str' in t:
                v = random.choice(['', 'a', 'hello world', 'UPPER', '123'])
                return v, f'"{v}"'
            if 'list' in t:
                v = random.choice([[], [42], [1, 2, 3], list(range(10))])
                return v, str(v)
        return super()._generate_value_for_type(param_type, param_name)


class AdvancedPrefixGenerator:
    """Factory for generating prefixes across multiple strategies."""

    STRATEGIES = {
        'random': PrefixGenerator,
        'boundary': BoundaryPrefixGenerator,
        'equivalence': EquivalencePrefixGenerator,
    }

    def __init__(self, metadata: MUTMetadata, source_path: str,
                 strategy: str = "random"):
        if strategy not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy}")
        self.metadata = metadata
        self.source_path = source_path
        self.strategy = strategy

    def generate(self) -> TestPrefix:
        cls = self.STRATEGIES[self.strategy]
        return cls(self.metadata, self.source_path).generate()

    def generate_multiple(self, count: int = 3) -> List[TestPrefix]:
        cls = self.STRATEGIES[self.strategy]
        return [cls(self.metadata, self.source_path).generate() for _ in range(count)]

    def generate_all_strategies(self) -> List[TestPrefix]:
        return [cls(self.metadata, self.source_path).generate()
                for cls in self.STRATEGIES.values()]
