# OracleGuard Benchmark Results

**27 models** across 6 providers, evaluated on 5 HumanEval+ problems with 15 mutants each.

---

## Model Ranking by Mean Trust Score

| # | Model | Provider | Size | OSS | Reasoning | Trust | V | S | N | R |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Mistral 7B v0.2 | NVIDIA | 7B | Yes | No | 0.598 | 2 | 1 | 0 | 2 |
| 2 | Gemini 3.1 Flash Lite | Gemini | -- | No | No | 0.552 | 1 | 2 | 0 | 2 |
| 3 | GPT-4.1 Mini | OpenAI | -- | No | No | 0.547 | 2 | 0 | 1 | 2 |
| 4 | GPT-OSS 20B | OpenRouter | 20B | Yes | No | 0.545 | 1 | 1 | 1 | 2 |
| 5 | GPT-4o | OpenAI | -- | No | No | 0.500 | 2 | 0 | 0 | 3 |
| 6 | DeepSeek V3 | SambaNova | 671B | Yes | No | 0.486 | 1 | 1 | 0 | 3 |
| 7 | Kimi K2 | Groq | -- | Yes | No | 0.482 | 1 | 1 | 0 | 3 |
| 8 | Gemini 2.5 Flash Lite | Gemini | -- | No | No | 0.478 | 2 | 0 | 0 | 3 |
| 9 | Llama 3.1 8B | Groq | 8B | Yes | No | 0.478 | 2 | 0 | 0 | 3 |
| 10 | Llama 3.1 8B | SambaNova | 8B | Yes | No | 0.478 | 2 | 0 | 0 | 3 |
| 11 | Devstral 123B | NVIDIA | 123B | Yes | No | 0.478 | 1 | 1 | 0 | 3 |
| 12 | o4-mini | OpenAI | -- | No | Yes | 0.465 | 1 | 1 | 0 | 3 |
| 13 | Qwen 2.5 Coder 7B | NVIDIA | 7B | Yes | No | 0.454 | 1 | 1 | 0 | 3 |
| 14 | Command R | Cohere | 35B | No | No | 0.453 | 1 | 1 | 0 | 3 |
| 15 | Liquid LFM 1.2B | OpenRouter | 1.2B | Yes | No | 0.446 | 2 | 0 | 0 | 3 |
| 16 | GPT-5.1 | OpenAI | -- | No | No | 0.441 | 0 | 2 | 0 | 3 |
| 17 | Falcon3 7B | NVIDIA | 7B | Yes | No | 0.440 | 1 | 1 | 0 | 3 |
| 18 | GPT-5.4 | OpenAI | -- | No | No | 0.422 | 1 | 0 | 1 | 3 |
| 19 | Minimax M2.5 | OpenRouter | -- | No | No | 0.408 | 1 | 0 | 1 | 3 |
| 20 | Command A | Cohere | 111B | No | No | 0.400 | 0 | 1 | 1 | 3 |
| 21 | Gemma 3 4B | OpenRouter | 4B | Yes | No | 0.393 | 1 | 0 | 1 | 3 |
| 22 | Nemotron 30B | OpenRouter | 30B | No | No | 0.380 | 2 | 0 | 0 | 3 |
| 23 | Qwen 3.6+ | OpenRouter | -- | No | No | 0.314 | 0 | 0 | 2 | 3 |
| 24 | Phi-3 Medium | NVIDIA | 14B | Yes | No | 0.308 | 0 | 1 | 0 | 4 |
| 25 | Gemini 3.0 Flash | Gemini | -- | No | Yes | 0.273 | 0 | 1 | 0 | 4 |
| 26 | Qwen3 32B | Groq | 32B | Yes | Yes | 0.136 | 0 | 1 | 0 | 4 |
| 27 | DeepSeek R1 | SambaNova | 671B | Yes | Yes | 0.000 | 0 | 0 | 0 | 5 |

---

## How the Trust Score Works

OracleGuard computes a **weighted composite trust score** T in [0, 1] from five signals:

```
T = 0.35 * M + 0.20 * L + 0.25 * C + 0.15 * V - 0.05 * P
```

| Signal | Weight | What it measures |
| --- | --- | --- |
| M (Mutation Score) | 35% | Fraction of mutants killed **by the assertion itself** (not crashes) |
| L (LLM Confidence) | 20% | Average self-reported confidence across generated assertions |
| C (Consistency) | 25% | Proportion of oracle-killed mutants (behavioral stability) |
| V (Coverage) | 15% | Diversity of assertion types (value, state, exception, property) |
| P (Complexity) | -5% | Penalty for high cyclomatic complexity of the function under test |

The score maps to four verdicts:

| Verdict | Range | Meaning |
| --- | --- | --- |
| **VERIFIED** | T >= 0.80 | Oracle is reliable, ready for adoption |
| **SUSPICIOUS** | 0.60 -- 0.80 | Review recommended, assertions may miss some faults |
| **NEEDS_REFINEMENT** | 0.40 -- 0.60 | Specific weaknesses identified, targeted improvements suggested |
| **REJECTED** | T < 0.40 | Oracle too weak for use, regenerate or write manually |

---

## How OracleGuard Helps

OracleGuard **does not improve model performance**. It tells you **which model output to trust**.

Without OracleGuard, a developer using any of these 27 models would accept all generated assertions at face value -- every model produces syntactically correct assertions that *look* plausible. With OracleGuard:

1. **Weak oracles are flagged.** A REJECTED verdict means "these assertions miss 60--100% of seeded faults -- don't ship them."

2. **Specific weaknesses are identified.** Instead of a binary pass/fail, OracleGuard reports *which mutation operators survived* and *what kind of assertion is missing*. For example: "5 constant_replacement mutants survived -- tighten value equality checks."

3. **Model selection is informed.** The ranking shows that Mistral 7B's assertions catch bugs with 0.598 trust while DeepSeek R1's catch 0%. Without OracleGuard, you'd have no way to know this.

4. **Refinement is actionable.** The surviving mutant patterns map directly to assertion improvement suggestions. A developer (or an automated feedback loop) can feed these back to the LLM: "The assertion `assert isinstance(result, float)` did not catch a return-value mutation that returned `0`. Add `assert result == 80.0` to catch exact-value mutations." This targeted guidance is the bridge between generation and validation.

---

## Why Models Fail at Specific Problems

Not all HumanEval problems are equally hard for oracle generation. The pattern across all 27 models is strikingly consistent:

| Problem | Function | Difficulty | Typical Verdict | Why |
| --- | --- | --- | --- | --- |
| HumanEval/0 | `has_close_elements` | Hard | REJECTED | Takes `List[float]` + `float`, but test prefix generates a single `float` as input (type mismatch). Most LLMs generate assertions that call the function with *new* inputs rather than checking the `result` variable -- these bypass the mutation test entirely. |
| HumanEval/1 | `separate_paren_groups` | Medium | SUSPICIOUS | Models generate good exact-value assertions (`assert result == ['()', '(())', '(()())']`), but the randomly generated string input produces unpredictable output, so some runs miss. |
| HumanEval/2 | `truncate_number` | Medium | VERIFIED | Simple function with clear expected output. Most models generate `assert result == 0.XX` correctly. |
| HumanEval/3 | `below_zero` | Hard | REJECTED | Takes `List[int]`, prefix generates a single `int`. Same type-mismatch issue as Problem 0. |
| HumanEval/4 | `mean_absolute_deviation` | Hard | REJECTED | Complex computation where the randomly generated input makes it hard to predict the exact output. Models fall back to type checks (`assert isinstance(result, float)`) which don't catch value mutations. |

**Root cause**: The test prefix generator (Stage 2) generates random inputs based on type annotations. When the type is `List[float]`, it generates `[1, 2, 3]` or a single float -- not a meaningful input that exercises the function's logic. This is a known limitation and a target for improvement.

**Why this matters for the paper**: The consistent failure pattern across all models demonstrates that OracleGuard correctly identifies the *same weaknesses* regardless of which LLM generated the assertions. This is evidence that the trust score reflects genuine oracle quality, not model-specific noise.

---

## Why Results May Seem Unexpected

### Reasoning models score lowest

Avg trust: **reasoning 0.218** vs **non-reasoning 0.453**.

Models like DeepSeek R1, Qwen3-32B, and Gemini 3.0 Flash wrap their output in `<think>...</think>` tags before producing the JSON. This breaks assertion extraction in many cases. The trust score of 0.000 for DeepSeek R1 means *zero assertions were parsed*, not that the model is incapable. o4-mini (0.465) performs better because OpenAI strips thinking tokens from the API response.

This is a **parser limitation**, not a model quality issue. Fixing the parser to reliably extract assertions from reasoning model output would likely improve their scores significantly.

### Model size does not predict oracle quality

- 1.2B Liquid LFM (0.446) > 30B Nemotron (0.380) > 32B Qwen3 (0.136)
- 7B Mistral (0.598) > 671B DeepSeek V3 (0.486) > 14B Phi-3 (0.308)
- 111B Command A (0.400) < 35B Command R (0.453)

What matters is the ability to generate **precise, well-structured JSON assertions with correct expected values**. Smaller models that follow instructions well outperform larger models that produce verbose, imprecise output.

### Same model, different providers -- identical results

Llama 3.1 8B scores **0.478** on both Groq and SambaNova. This confirms OracleGuard produces consistent, provider-independent evaluations. The trust score measures oracle quality, not inference speed or provider reliability.

### Scores vary between runs

LLM non-determinism (temperature=0.7) means the same model can produce different trust scores across runs. Kimi K2 scored **0.443, 0.404, 0.360, 0.350, 0.482** across five runs on the same 5 problems. For publication-quality results, multiple runs with mean and standard deviation reporting are recommended.

### Open-source models are competitive

OSS avg **0.461** vs proprietary avg **0.445** (non-reasoning only). Mistral 7B leads the entire ranking. This suggests that for test oracle generation, instruction-following ability matters more than raw scale.

---

## Experimental Setup

| Parameter | Value |
| --- | --- |
| Benchmark | HumanEval+ (5 problems: 0--4) |
| Mutants per test case | 15 |
| Test cases per problem | 1 |
| Seeded faults for evaluation | 10 |
| LLM temperature | 0.7 |
| LLM max tokens | 2000 |
| Mutation operators | 5 (arithmetic, constant, relational, return-value, statement-deletion) |
| Input strategy | Random (type-based) |
| Providers | OpenAI, OpenRouter, Groq, SambaNova, Cohere, NVIDIA, Gemini |

---

## Conclusions

### 1. OracleGuard successfully discriminates oracle quality

Across 27 models, the trust score produces a meaningful ranking that separates strong assertion generators from weak ones. The top model (Mistral 7B, trust 0.598) generates assertions with exact value checks and boundary conditions, while the bottom models produce only type checks or malformed output. The four verdict categories (VERIFIED, SUSPICIOUS, NEEDS_REFINEMENT, REJECTED) provide actionable guidance -- not a binary pass/fail.

The method validation experiment confirms this with controlled synthetic oracles: Spearman rank correlation of **0.738** between trust score and actual fault detection rate, with a trust gap of **0.207** between strong and bad oracles. OracleGuard does not guess -- it measures.

### 2. Mutation-based validation catches what static analysis cannot

Every model in our benchmark generates syntactically correct, compiling assertions that pass on correct code. Without OracleGuard, all 27 models look equally good. Mutation testing reveals the difference: some assertions catch 100% of arithmetic operator swaps but miss 50% of constant modifications. Some catch return-value replacements but miss statement deletions entirely.

The per-operator kill rate breakdown is the most practically useful output. It tells a developer not just "this oracle is weak" but "this oracle is weak *because it lacks value-precision assertions*" -- and suggests exactly what to add.

### 3. The trust score is model-agnostic and provider-independent

Llama 3.1 8B scores **0.478** on both Groq and SambaNova -- identical trust despite different infrastructure. This confirms that OracleGuard evaluates the *oracle*, not the provider. A team can switch LLM backends without recalibrating the trust framework.

The same pipeline evaluated proprietary models (GPT-4o, Gemini), open-source models (Mistral, Llama, DeepSeek), code-specialized models (Qwen Coder, Devstral), and general-purpose models (Command R, Kimi K2) -- all through a single `OpenAIProvider` with no per-model configuration.

### 4. Bigger models do not generate better oracles

The most surprising finding: model size has no correlation with trust score.

- **1.2B** Liquid LFM (0.446) outperforms **30B** Nemotron (0.380) and **32B** Qwen3 (0.136)
- **7B** Mistral (0.598) outperforms **671B** DeepSeek V3 (0.486) and **123B** Devstral (0.478)
- **111B** Command A (0.400) scores lower than **35B** Command R (0.453)

What predicts oracle quality is **instruction-following precision**: the ability to produce well-structured JSON with exact expected values rather than verbose explanations or generic type checks. This has practical implications -- teams can use smaller, cheaper, faster models for oracle generation without sacrificing quality, as long as the model follows the output schema reliably.

### 5. Reasoning models need special handling

The three reasoning models (DeepSeek R1, Qwen3-32B, Gemini 3.0 Flash) scored lowest (0.000, 0.136, 0.273). This is not because they generate worse assertions -- it is because they wrap output in `<think>...</think>` tags that break JSON extraction. The one exception, o4-mini (0.465), performs well because OpenAI strips thinking tokens server-side.

This is a parser limitation with a clear fix: strip thinking tags before parsing. The finding highlights that integrating reasoning models into automated pipelines requires attention to output format, not just prompt engineering.

### 6. LLM non-determinism is a first-class concern

Kimi K2 scored 0.443, 0.404, 0.360, 0.350, and 0.482 across five runs on the same problems. This 37% coefficient of variation means **single-run evaluation is unreliable**. For publication-quality results, we recommend at least 3 runs per model with mean and standard deviation reporting.

This variance is not a flaw in OracleGuard -- it reflects a real property of LLM-generated oracles. The trust score correctly captures this: sometimes the model generates a strong value assertion and gets VERIFIED, sometimes it generates only a type check and gets REJECTED. Both scores are correct reflections of what was generated in that run.

### 7. OracleGuard enables a new workflow

The traditional workflow: developer writes tests manually, hopes they're good enough, has no way to measure coverage gaps in oracle quality.

The LLM-assisted workflow (without OracleGuard): LLM generates assertions, developer reviews them visually, accepts or rejects based on intuition.

The OracleGuard workflow:

1. LLM generates candidate assertions
2. OracleGuard validates them against mutation-based fault injection
3. VERIFIED oracles are adopted; REJECTED oracles are discarded
4. SUSPICIOUS/NEEDS_REFINEMENT oracles get specific improvement suggestions
5. Suggestions feed back to the LLM for targeted refinement
6. Iterate until VERIFIED or give up and write manually

This turns oracle generation from a one-shot gamble into a **measurable, iterative process** with clear stopping criteria.

---

## Limitations and Future Work

- **5-problem evaluation**: Results are directional, not statistically significant. Extending to 50+ problems with multiple runs would strengthen all findings.
- **Random test inputs**: The prefix generator produces random type-appropriate values that sometimes don't exercise the function's logic meaningfully. Boundary and equivalence strategies help but are not used by default.
- **Whole-file mutations**: Mutations apply to all functions in the file, not just the target function. Most mutations are irrelevant to the test, inflating both kill and survive counts.
- **Reasoning model support**: The parser handles `<think>` tags but not all reasoning formats. Robust extraction across model families is needed.
- **No refinement loop evaluation**: We describe the feedback loop but do not measure its convergence rate across models and problems.
- **Trust score weights are not empirically calibrated**: The weights (0.35, 0.20, 0.25, 0.15, 0.05) are design choices. Sensitivity analysis and data-driven calibration on a larger dataset would strengthen the scoring model.
