# OracleGuard Architecture

## Problem Statement

Automated test input generation has matured -- fuzzers, symbolic engines, and search-based tools produce inputs at scale. But the other half of testing remains unsolved: **how do you know the output is correct?**

This is the **oracle problem**. A test oracle is a predicate that decides whether a program's output is right for a given input. Writing oracles requires knowing what the program *should* do, and that knowledge lives in the developer's head, not in the source code.

Large Language Models can read code and generate plausible-looking assertions. But "plausible-looking" and "correct" are not synonyms. LLMs hallucinate, miss boundary conditions, and produce assertions that sound confident but check the wrong thing. Trusting them blindly introduces the very class of silent bugs that testing exists to prevent.

**OracleGuard treats every generated assertion as a hypothesis, not a fact.** Before any oracle gets accepted, it must prove its ability to detect faults -- measured empirically through mutation testing, scored quantitatively, and refined based on specific weaknesses.

---

## Architecture Overview

OracleGuard is a five-stage pipeline. Each stage produces a typed artifact that feeds the next. Stages are independent -- any can be run, replaced, or studied in isolation.

```text
Source Code (.py)
       |
       v
 +------------------+
 | Stage 1           |
 | Static Analysis   |---> MUTMetadata (name, signature, params, complexity, source)
 +------------------+
       |
       v
 +------------------+
 | Stage 2           |
 | Prefix Generation |---> TestPrefix (imports, setup code, variable bindings)
 +------------------+
       |
       v
 +------------------+
 | Stage 3           |
 | LLM Assertion Gen |---> TestCase (test function with candidate assertions)
 +------------------+
       |
       v
 +------------------+
 | Stage 4           |
 | Differential      |
 | Testing           |---> DifferentialReport (per-mutant kill/survive, mutation score)
 +------------------+
       |
       v
 +------------------+
 | Stage 5           |
 | Analysis &        |
 | Refinement        |---> OracleVerdict (trust score, status, weaknesses, suggestions)
 +------------------+
```

---

## Project Structure

```text
oracleguard/
  __init__.py                 # Public API exports
  static_analysis.py          # Stage 1: AST-based Python analysis
  prefix_generation.py        # Stage 2: Test setup/fixture generation
  assertion_generation.py     # Stage 3: LLM provider + assertion synthesis
  differential_testing.py     # Stage 4: Mutation operators + subprocess execution
  analysis.py                 # Stage 5: Trust scoring + refinement engine
  pipeline.py                 # Orchestrator: runs all 5 stages end-to-end

benchmarks/
  humaneval_loader.py         # Loads HumanEval+ problems for evaluation
  run_benchmark.py            # Runs OracleGuard on HumanEval+ with any LLM
  validate_method.py          # Proves trust score predicts fault detection
  compare_models.py           # Side-by-side model comparison
  analyze_results.py          # Aggregates saved results into comparison tables

main.py                       # Unified CLI entry point
example.py                    # Sample Python functions for testing
pyproject.toml                # Project config (uv/pip)
models.json                   # Registry of all benchmarked LLM models
results.md                    # Benchmark results and analysis
```

---

## Stage-by-Stage Flow

### Stage 1: Static Analysis (`static_analysis.py`)

**Input:** Python source file path.

**What it does:** Parses the source with Python's `ast` module. Walks the AST to find all function definitions. For each function, extracts:

- Function signature with type annotations
- Parameter names and types
- Return type
- Docstring
- Called dependencies (function calls, attribute access)
- Cyclomatic complexity (McCabe: base 1, +1 for `if`/`while`/`for`/`except`, +n-1 for `BoolOp`)

Functions outside the complexity range (default 2--20) are filtered out. Too simple = nothing to learn from. Too complex = unreliable at unit level.

**Output:** List of `MUTMetadata` objects.

**Key class:** `PythonAnalyzer` -- uses `ast.walk()`, `ast.get_docstring()`, `ast.unparse()`.

---

### Stage 2: Prefix Generation (`prefix_generation.py`)

**Input:** `MUTMetadata` from Stage 1.

**What it does:** Generates the setup code needed before a function can be called in a test. This includes:

- Import statements (`from module import *`)
- Class instantiation (if the function is an instance method with `self`)
- Concrete parameter values based on type annotations
- Mock objects for external dependencies

Three input strategies are available:

| Strategy | Class | What it generates |
| --- | --- | --- |
| Random | `PrefixGenerator` | Type-appropriate random values (int: 1-100, float: 0-100, etc.) |
| Boundary | `BoundaryPrefixGenerator` | Edge cases: 0, -1, MAX_INT, empty string, None |
| Equivalence | `EquivalencePrefixGenerator` | One representative per partition: negative, zero, small, large |

**Output:** `TestPrefix` with `setup_code`, `variable_bindings`, `imports`, `fixture_objects`.

---

### Stage 3: LLM Assertion Generation (`assertion_generation.py`)

**Input:** `MUTMetadata` + `TestPrefix` from Stages 1-2.

**What it does:** Constructs a structured prompt containing the function signature, source code, docstring, test setup, and invocation. Sends it to an LLM and parses the JSON response into candidate assertions.

The prompt asks for 2-4 assertions covering: return value correctness, type validation, boundary conditions, side effects, and exception handling.

**LLM Provider:** Single `OpenAIProvider` class with built-in rate limiting. Works with any OpenAI-compatible API:

```python
# OpenAI direct
provider = OpenAIProvider(model="gpt-4.1-mini")

# OpenRouter (free models)
provider = OpenAIProvider(model="qwen/qwen3.6-plus:free",
                          base_url="https://openrouter.ai/api/v1")

# Groq
provider = OpenAIProvider(model="llama-3.1-8b-instant",
                          base_url="https://api.groq.com/openai/v1")

# SambaNova, Cohere, NVIDIA, Gemini -- same pattern
```

Rate limiting: configurable `call_interval` (min seconds between calls) + exponential backoff on 429 errors.

**Response parsing:** Strips markdown fences, `<think>` tags (reasoning models), and attempts JSON repair on truncated responses by extracting complete assertion objects via regex.

**Output:** `TestCase` with `test_name`, `assertions[]`, `full_test_code`.

---

### Stage 4: Differential Testing (`differential_testing.py`)

**Input:** Source file + `TestCase` from Stage 3.

**What it does:** This is where assertions earn their place. For each test case:

1. **Generate N mutants** by applying AST-level transformations to the source code
2. **Run the test against each mutant** in an isolated subprocess with a 5-second timeout
3. **Record kill/survive** -- a mutant is "killed" if the test fails, "survived" if it passes

Two kill measurements are tracked:

- **Total kill rate:** Any test failure (crash or assertion error) counts as a kill. Standard mutation testing metric.
- **Oracle kill rate:** Only assertion failures count. Crashes are swallowed by a try/except guard. This isolates the oracle's contribution from incidental crashes.

**Six mutation operator classes:**

| Operator | Class | What it does |
| --- | --- | --- |
| Arithmetic | `ArithmeticOperatorMutator` | `+` <-> `-`, `*` <-> `/`, `%` -> `+` |
| Relational | `RelationalOperatorMutator` | `>` <-> `<`, `>=` <-> `<=`, `==` <-> `!=` |
| Logical | `LogicalOperatorMutator` | `and` <-> `or` |
| Constant | `ConstantReplacementMutator` | int +/-1, float +/-0.1, str append, bool negate |
| Statement | `StatementDeletionMutator` | Replace a statement with `pass` |
| Return | `ReturnValueMutator` | Replace return value with `0`, `None`, or `""` |

Each operator is a subclass of `MutationOperator(ast.NodeTransformer)`. The `Mutator` class collects candidate nodes on a first pass, then applies the mutation to a randomly selected target on a fresh AST copy. This avoids the fragile `random.randint(0, 10)` targeting pattern.

**Subprocess isolation:** Each mutant test runs in a separate Python process via `subprocess.run()`. This prevents infinite loops, memory exhaustion, or crashes from derailing the pipeline.

**Output:** `DifferentialReport` with `mutation_results[]`, `mutants_killed`, `mutants_survived`, `mutation_score`, `oracle_kill_rate`, `discrepancy_signals`.

---

### Stage 5: Analysis and Refinement (`analysis.py`)

**Input:** `TestCase` + `DifferentialReport` + `MUTMetadata`.

**What it does:** Computes the trust score from five signals and issues a verdict.

**Trust score computation:**

```text
T = 0.35 * M + 0.20 * L + 0.25 * C + 0.15 * V - 0.05 * P

M = oracle_kill_rate (assertion-only kills, not crashes)
L = mean LLM confidence across assertions
C = consistency (proportion of oracle-killed mutants)
V = coverage (assertion type diversity: value/state/exception/property)
P = complexity penalty (cyclomatic_complexity / 20, capped at 1.0)
```

**Verdict thresholds:**

- VERIFIED: T >= 0.80
- SUSPICIOUS: 0.60 <= T < 0.80
- NEEDS_REFINEMENT: 0.40 <= T < 0.60
- REJECTED: T < 0.40

**Weakness identification:** Groups survived mutants by operator type. Each surviving operator maps to a specific weakness:

| Surviving operator | Weakness | Recommendation |
| --- | --- | --- |
| arithmetic | Weak value assertions | Add exact-value equality checks |
| relational | Weak boundary assertions | Add comparison boundary assertions |
| logical | Weak condition assertions | Add and/or condition checks |
| constant | Weak precision assertions | Tighten value equality |
| statement_deletion | Missing path coverage | Add assertions for removed code paths |
| return_value | Missing value checks | Add type + value return assertions |

**Refinement engine:** `RefinementEngine` generates `RefinementSuggestion` objects for each surviving mutant. Each suggestion includes proposed assertion code, rationale (which mutation it would catch, at which line), and confidence.

**Output:** `OracleVerdict` with `status`, `trust_score`, `trust_metrics`, `weaknesses[]`, `recommendations[]`, `refinements[]`.

---

## How it Runs

### CLI Usage

```bash
# Basic: analyze a Python file with mock LLM (no API needed)
uv run main.py example.py

# With a real LLM via OpenRouter
uv run main.py example.py --llm openai \
  --model "qwen/qwen3.6-plus:free" \
  --base-url "https://openrouter.ai/api/v1"

# Specific method, more mutants, boundary inputs
uv run main.py example.py --method calculate_discount \
  --mutants 30 --strategy boundary

# Save verified tests to file
uv run main.py example.py --output verified_tests.py
```

### Programmatic Usage

```python
from oracleguard import OracleGuard, PipelineConfig

config = PipelineConfig(
    llm_provider='openai',
    llm_model='gpt-4.1-mini',
    num_mutants=20,
    test_count=2,
    prefix_strategy='boundary',
)

guard = OracleGuard(config)
results = guard.run('my_module.py', method_name='calculate_discount')

for r in results:
    print(f"{r.method.name}: {r.verdict.status.value} (trust={r.verdict.trust_score:.2f})")
    for w in r.verdict.weaknesses:
        print(f"  - {w}")
```

### Benchmark Usage

```bash
# Run on HumanEval+ with any LLM
uv run benchmarks/run_benchmark.py --limit 20 --llm openai \
  --model "gpt-4.1-mini" --mutants 15 --output results/openai/gpt-4.1-mini.json

# Compare saved results across models
uv run benchmarks/analyze_results.py results/**/*.json

# Validate that trust score predicts fault detection
uv run benchmarks/validate_method.py --mutants 30 --faults 25
```

---

## Data Flow Example

For `calculate_discount(price=100.0, discount_percent=20.0)`:

**Stage 1** extracts: name=`calculate_discount`, params=`[price: float, discount_percent: float]`, return=`float`, complexity=3.

**Stage 2** generates:
```python
arg_price = 42.31
arg_discount_percent = 73.5
```

**Stage 3** (LLM) produces:
```python
assert result is not None
assert isinstance(result, float)
assert result == 80.0      # if inputs were 100.0, 20.0
assert 0 <= result <= 100.0
```

**Stage 4** generates 15 mutants. Example:
- `price * (discount_percent / 100)` -> `price + (discount_percent / 100)`: result becomes 120.0, `assert result == 80.0` catches it -> KILLED
- `return round(...)` -> `return None`: `assert result is not None` catches it -> KILLED
- `discount_percent > 100` -> `discount_percent < 100`: validation logic flipped, but test inputs don't trigger it -> SURVIVED

**Stage 5** computes: mutation_score=0.80, llm_confidence=0.92, consistency=0.80, coverage=0.25 (only 'value' type), complexity=3/20=0.15. Trust = 0.35*0.80 + 0.20*0.92 + 0.25*0.80 + 0.15*0.25 - 0.05*0.15 = **0.694** -> SUSPICIOUS.

Weakness: "3 relational mutants survived -- weak boundary assertions." Recommendation: "Add boundary comparison assertions."

---

## Evaluation Strategy

### What We Measure

OracleGuard makes a claim: the trust score predicts how well an oracle detects real faults. We validate this claim at three levels:

1. **Discrimination** -- Can OracleGuard tell strong oracles from weak ones?
2. **Correlation** -- Does a higher trust score mean better fault detection?
3. **Cross-model consistency** -- Does OracleGuard rank models the same way regardless of provider?

### Why HumanEval+

We chose [HumanEval+](https://github.com/evalplus/evalplus) (augmented HumanEval by EvalPlus) as our primary benchmark for several reasons:

**What it is:** 164 self-contained Python programming problems, each with a function signature, docstring, canonical correct solution, and human-written test assertions. EvalPlus augments the original OpenAI HumanEval with 80x more test cases per problem.

**Why it fits OracleGuard:**

| Requirement | HumanEval+ provides |
| --- | --- |
| Self-contained functions | Yes -- no external dependencies, no file I/O, no state |
| Known-correct implementations | Yes -- canonical solutions are verified |
| Ground-truth oracles | Yes -- human-written assertions for comparison |
| Python-native | Yes -- matches our AST-based mutation engine |
| Varying complexity | Yes -- from simple arithmetic to recursive algorithms |
| Community acceptance | Yes -- standard benchmark for LLM code generation |

**What it doesn't provide** (and why that's acceptable for now):

- No real bugs (only seeded mutations) -- but mutation testing is a well-established proxy for fault detection
- No stateful or multi-module code -- OracleGuard targets unit-level functions
- Limited to 164 problems -- sufficient for a validation study, not a production evaluation

### Alternative Benchmarks Considered

| Benchmark | Description | Why we didn't use it |
| --- | --- | --- |
| **Defects4J** | 835 real bugs in Java projects | Java-only; OracleGuard targets Python |
| **BugsInPy** | 493 real bugs in 17 Python projects | Real-world functions have complex dependencies; requires per-project environment setup; ideal for future work |
| **MBPP** | 974 mostly-basic Python problems | Similar to HumanEval but with weaker test cases (only 3 assertions per problem); less useful as ground truth |
| **EvalPlus (full)** | HumanEval + MBPP with 80x more tests | We use HumanEval+ from EvalPlus; the MBPP+ portion is a natural extension |
| **methods2test** | Large-scale Java methods with test cases | Java-only; used by TOGLL for training data |

**For publication**, we recommend extending to BugsInPy (real bugs, not just mutations) and running on 50+ HumanEval problems with multiple runs per model.

### Evaluation Workflow

```text
                    HumanEval+ Problem
                          |
            +-------------+-------------+
            |                           |
    Correct Function             Ground-Truth Tests
            |                           |
    +-------v--------+                  |
    | OracleGuard    |                  |
    | Pipeline       |                  |
    | (Stages 1-5)   |                  |
    +-------+--------+                  |
            |                           |
    OracleGuard's                       |
    Generated Assertions                |
            |                           |
    +-------v--------+         +--------v--------+
    | Seed N fresh   |         | Seed N fresh    |
    | mutants        |         | mutants         |
    +-------+--------+         +--------+--------+
            |                           |
    How many mutants           How many mutants
    did OG assertions          did GT assertions
    catch?                     catch?
            |                           |
            +-------------+-------------+
                          |
                    COMPARE:
              OG fault detection rate
              vs GT fault detection rate
              vs Trust score correlation
```

For each problem, we:

1. Run OracleGuard's full pipeline to generate assertions and compute trust scores
2. Independently seed fresh mutants (not the same ones used for scoring)
3. Test OracleGuard's assertions against those mutants -- how many faults caught?
4. Test human-written ground-truth assertions against the same mutants -- how many faults caught?
5. Compare: does a higher trust score predict a higher fault detection rate?

### Method Validation Experiment

Beyond the benchmark, we run a controlled experiment (`benchmarks/validate_method.py`) with synthetic oracles at four known quality levels:

| Quality | Example assertions | Expected behavior |
| --- | --- | --- |
| **Strong** | `assert result == 80.0`, `assert isinstance(result, float)` | High trust, high fault detection |
| **Medium** | `assert isinstance(result, float)`, `assert result >= 0` | Medium trust, medium fault detection |
| **Weak** | `assert result is not None` | Low trust, low fault detection |
| **Bad** | `assert True`, `assert result != 'hello'` | Lowest trust, zero fault detection |

Results confirm the trust score works:

- **Spearman rank correlation: 0.738** (strong positive) between trust and fault detection
- **Trust gap: 0.207** between strong (0.334) and bad (0.127) oracles
- Monotonic ordering: strong > medium > weak > bad in both trust AND fault detection

---

## Why the Trust Score Matters for Developers

### The problem without OracleGuard

A developer asks an LLM to generate test assertions. The LLM returns four assertions that look reasonable:

```python
assert result is not None          # looks fine
assert isinstance(result, float)   # looks fine
assert result == 80.0              # looks fine
assert 0 <= result <= 100.0        # looks fine -- but is it?
```

All four compile. All four pass on the correct code. The developer ships them. Six months later, a refactor introduces a bug where the discount is applied twice, returning -20.0. The bounds check `0 <= result <= 100.0` still passes because -20.0 < 100.0. The regression goes undetected.

### What OracleGuard tells the developer

OracleGuard runs those four assertions against 15 mutants and reports:

```text
Status: SUSPICIOUS (trust = 0.69)

Weaknesses:
  - 3 return-value mutants survived -- weak return value assertions
  - 2 constant-replacement mutants survived -- weak value precision

Refinement suggestions:
  [1] Add: assert result <= price
      Rationale: Catches return-value mutation at line 8 (return price*2 -> survives current bounds check)

  [2] Add: assert result == 80.0 for input (100.0, 20.0)
      Rationale: Catches constant modification at line 7 (100 -> 101)
```

The developer now knows:

1. **Don't trust these assertions blindly** -- SUSPICIOUS means "review before shipping"
2. **Exactly what's missing** -- return-value and constant mutations survive
3. **What to add** -- specific assertions with rationale tied to mutation locations
4. **When to stop** -- iterate until the verdict reaches VERIFIED

### Concrete benefits

| Without OracleGuard | With OracleGuard |
| --- | --- |
| "The LLM generated 4 assertions, looks good" | "3 of 4 assertions are strong, 1 misses boundary mutations" |
| All LLM outputs treated equally | Trust score ranks which oracles to keep vs reject |
| No feedback loop | Surviving mutants drive targeted refinement |
| Silent regressions ship to production | Weak oracles are flagged before adoption |
| Model selection is guesswork | Empirical ranking: Mistral 7B > DeepSeek V3 > Qwen 3.6+ |
| "Did we test enough?" is unanswerable | Trust score provides a quantitative answer |

### The refinement loop

OracleGuard's most practical value is not the score itself -- it's the **surviving mutant log**. A score of 0.72 (SUSPICIOUS) is abstract. "Three relational-operator mutants survived; specifically, mutations replacing `>` with `>=` on line 14 all passed" is actionable.

This log can be fed back to the LLM in a second round:

```text
Prompt: "The following mutants survived your assertions:
  1. Line 14: changed > to >= -- assertion did not catch it
  2. Line 8: changed return value to 0 -- assertion did not catch it

Generate additional assertions that would detect these specific faults."
```

Early experiments suggest this converges in 2-3 rounds for most functions, transforming a SUSPICIOUS oracle into a VERIFIED one.
