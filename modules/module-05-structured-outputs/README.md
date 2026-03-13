# Module 5: Structured Outputs at Depth

**Week 2 · Phase 1 — Foundations**

---

## Learning Objectives

By the end of this module you will:

- Use Azure OpenAI's strict JSON schema mode (not just `json_object` mode)
- Use Pydantic v2 as the single source of truth for your schemas
- Flatten `$defs` / `$ref` from Pydantic-generated schemas so Azure OpenAI accepts them
- Handle every failure mode: schema violations, refusals, length truncation
- Build a typed extraction pipeline where every output is a validated Python object
- Know the limits: which schema features are unsupported, what the model struggles with

---

## Prerequisites

- [Module 1](../module-01-llm-primitive/README.md) and [Module 2](../module-02-prompt-engineering/README.md) complete
- Azure OpenAI resources from Module 1 still running

---

## Concepts

### 1. Two Modes: json_object vs. json_schema

Azure OpenAI gives you two `response_format` options for structured output:

**json_object mode:**
```json
"response_format": {"type": "json_object"}
```
The model is constrained to output valid JSON, but the shape is up to the model.
You must still validate the output against your expected schema yourself.
You must also mention "JSON" in your prompt — the API requires it.

```python
# What you get: valid JSON, unpredictable structure
{
  "answer": "Paris",
  "confidence": 0.99,
  "extra_key_you_didnt_ask_for": "sometimes this appears"
}
```

**json_schema mode:**
```json
"response_format": {
  "type": "json_schema",
  "json_schema": {
    "name": "my_schema",
    "strict": true,
    "schema": { ...your JSON Schema object... }
  }
}
```
With `strict: true`, the model uses constrained decoding. It is mechanically
incapable of generating tokens that would violate the schema. You are
guaranteed to receive JSON that matches your schema — or a refusal.

**In production, always use `json_schema` with `strict: true`.**

The guarantees it provides are worth the extra setup.

### 2. Pydantic v2 as Schema Source of Truth

Do not write JSON Schemas by hand. Use Pydantic v2 models:

```python
from pydantic import BaseModel, Field

class BugReport(BaseModel):
    title: str = Field(description="Short one-line summary of the bug")
    severity: Literal["critical", "high", "medium", "low"]
    affected_component: str
    reproduction_steps: list[str]
    expected_behavior: str
    actual_behavior: str
```

Get the JSON Schema:
```python
schema = BugReport.model_json_schema()
```

This gives you a Python dict you can pass directly to the API.

**Why Pydantic is the right source of truth:**
- Single definition: the same model validates API responses AND defines the schema
- IDE support: typed attributes, autocomplete, type checking
- Validation: `BugReport.model_validate(response_json)` validates and parses in one call
- Documentation: Field descriptions become the model's guidance

### 3. The $defs Problem

When you have nested Pydantic models, `model_json_schema()` generates a schema
with `$defs` and `$ref`:

```python
class Address(BaseModel):
    street: str
    city: str

class Person(BaseModel):
    name: str
    address: Address
```

The generated schema:
```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "address": {"$ref": "#/$defs/Address"}
  },
  "$defs": {
    "Address": {
      "type": "object",
      "properties": {
        "street": {"type": "string"},
        "city": {"type": "string"}
      }
    }
  }
}
```

**Azure OpenAI's strict mode does not support `$ref`.** If you send this
schema, you will get a 400 error.

You must inline all `$defs`. The `flatten_schema()` function in the starter
file handles this. Here is the core logic:

```python
def flatten_schema(schema: dict) -> dict:
    """
    Inline all $ref references into the schema, removing $defs.
    Azure OpenAI strict mode does not support $ref.
    """
    defs = schema.pop("$defs", {})
    if not defs:
        return schema
    return _inline_refs(schema, defs)

def _inline_refs(node: Any, defs: dict) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            ref_name = node["$ref"].split("/")[-1]  # "#/$defs/Address" -> "Address"
            return _inline_refs(defs[ref_name], defs)
        return {k: _inline_refs(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node
```

After flattening, the schema above becomes:
```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "address": {
      "type": "object",
      "properties": {
        "street": {"type": "string"},
        "city": {"type": "string"}
      }
    }
  }
}
```

**Additional requirement: `additionalProperties: false`**

For `strict: true` to work, every object in the schema (including nested
objects) must have `"additionalProperties": false`. You can add this
automatically in the flattening pass.

### 4. Constrained Decoding — What It Means and What It Limits

When `strict: true` is set, the model does not generate tokens freely and
then check them against your schema. Instead, the allowed vocabulary at each
step is filtered to only tokens that would not violate the schema.

This is powerful but has costs:

**What constrained decoding guarantees:**
- The output will always be valid JSON
- Every required field will be present
- All values will match their declared types
- Enum values will be exactly the allowed strings

**What it cannot do:**
- It cannot guarantee semantic correctness (the model can still hallucinate values)
- It cannot guarantee the values are factually accurate
- It cannot handle `oneOf` at the top level of the schema
- It cannot handle recursive schemas (a type that references itself)
- It cannot handle `$ref` (hence the flattening requirement)
- Very deeply nested or very large schemas degrade model quality

**Practical limit:** schemas above roughly 100 properties tend to cause the
model to produce correct structure but semantically poor values. Break large
schemas into smaller extraction passes.

### 5. Failure Modes and finish_reason

**Always check `finish_reason` before parsing the response.**

| finish_reason | Meaning | What to do |
|---|---|---|
| `"stop"` | Normal completion | Parse and validate |
| `"length"` | Hit max_tokens | Truncated — JSON is likely invalid, discard or retry with higher max_tokens |
| `"content_filter"` | Azure content policy triggered | Log and handle gracefully, do not parse |
| `"tool_calls"` | Model wants a tool | Not applicable to structured output requests |

**The refusal field (new in gpt-4o):**
When the model determines it should not comply with a request, the response
may include a `refusal` field instead of `content`:

```json
{
  "message": {
    "role": "assistant",
    "content": null,
    "refusal": "I'm not able to extract personal information from this document."
  }
}
```

Always check:
```python
message = response["choices"][0]["message"]
if message.get("refusal"):
    raise ValueError(f"Model refused: {message['refusal']}")
content = message.get("content")
if content is None:
    raise ValueError("No content in response")
```

**Validation after parsing:**
Even with strict mode, always run Pydantic validation:
```python
data = json.loads(content)
result = MyModel.model_validate(data)  # raises ValidationError if schema mismatch
```

This catches edge cases where the API schema enforcement and your Pydantic
model diverge slightly (e.g., integer vs. float, None vs. missing field).

### 6. Extraction Pipeline Pattern

A common production pattern is chunked extraction:

```
[Large Document]
      |
      v
[Split into chunks (overlap by ~10%)]
      |
      v
[Extract structured data from each chunk in parallel]
      |
      v
[Merge/deduplicate results]
      |
      v
[Validated structured output]
```

Key design decisions:
- **Chunk size:** balance between context and API cost. 2000–4000 tokens per
  chunk is a common starting point.
- **Overlap:** repeat 10–20% of content across chunk boundaries to avoid
  losing context-dependent information.
- **Merge strategy:** for list fields, concatenate and deduplicate.
  For scalar fields (title, summary), use the first chunk's extraction
  or a second LLM pass that synthesises all chunk outputs.

### 7. Comparing json_object vs. json_schema in Practice

| Metric | json_object | json_schema strict |
|---|---|---|
| Schema compliance | ~70–85% (model may omit fields) | ~99%+ (constrained decoding) |
| Parse error rate | ~5–15% (model may produce invalid JSON in edge cases) | ~0% (guaranteed valid JSON) |
| Latency | Marginally faster | Slightly slower (schema processing overhead) |
| Setup complexity | Minimal | Requires schema prep + $defs flattening |
| Recommended for production | No | Yes |

The compliance gap widens on complex schemas and with models that are not
specifically fine-tuned for structured output.

---

## Azure Setup

No new Terraform needed. Uses the same Azure OpenAI resources from Module 1.

---

## Lab Setup

```bash
cd modules/module-05-structured-outputs/lab
cp .env.example .env
# edit .env with your values
uv sync
```

---

## Lab Tasks

### Task 1: Three Extraction Models

**Goal:** Build three Pydantic models that serve as both the JSON Schema for the API and the validation layer for responses, demonstrating the single-source-of-truth pattern.

**What to do:**

1. Open `lab/src/extractor.py` and find the Pydantic model stubs: `JobPosting` (line ~150), `BugReport` (line ~170), `ReviewIssue` (line ~187), and `CodeReview` (line ~195)
2. Complete each model's field definitions with types and `Field(description="...")` annotations. For example, add `required_skills: list[str] = Field(description="...")` to `JobPosting`. Fill in all TODO fields in each model.
3. Find the `extract_structured()` function (line ~229) and implement the final parsing: `json.loads(content)` followed by `model_class.model_validate(parsed)`. Also add the refusal and `finish_reason` checks noted in the TODOs.
4. Find `run_task1()` (line ~368) and wire up the three extraction calls using the sample inputs `JOB_POSTING_SAMPLE`, `BUG_REPORT_SAMPLE`, and `CODE_DIFF_SAMPLE` already defined in the file.
5. Run the command:
   ```bash
   uv run python src/extractor.py --task1
   ```

**Expected result:**
- Output similar to:
  ```
  1a. Job Posting Extraction
  JobPosting(job_title='Senior Python Backend Engineer',
             company_name='Contoso Cloud',
             location='Seattle, WA (hybrid, 2 days in office)',
             employment_type='full-time',
             required_skills=['Python', 'distributed systems', 'PostgreSQL', 'Redis', 'Docker', 'Kubernetes'],
             preferred_skills=['Azure', 'AWS', 'MLOps'],
             salary_range_usd='$160,000 – $200,000',
             role_summary='Design and implement high-throughput data pipelines...',
             years_experience_required=5)

  1b. Bug Report Extraction
  BugReport(title='Login fails silently when Azure AD token expires mid-session',
            severity='high', affected_component='frontend/auth', ...)

  1c. Code Review Extraction
  CodeReview(issues=[ReviewIssue(severity='critical', category='security', ...)], ...)
  ```
- Each result is a fully typed Python object — attribute access like `result.severity` works with IDE autocomplete

**Why this matters:**
In production extraction pipelines, unvalidated LLM output causes downstream crashes and data corruption. Pydantic as the single schema source means one definition drives API constraints, response validation, and application types — eliminating the class of bugs where these diverge.

---

### Task 2: Try to Break Strict Mode

**Goal:** Probe the boundaries of constrained decoding by testing prompt injection, ambiguous inputs, and missing source data to understand what strict mode guarantees and what it does not.

**What to do:**

1. Open `lab/src/extractor.py` and find `run_task2()` (line ~396)
2. Implement experiment 2a: call `extract_structured()` with the `injected_document` (already defined at line ~404) and `JobPosting`. Print whether the injection text (`"HACKED"`, `"ATTACKER"`) appears in the output.
3. Implement experiment 2b: call `extract_structured()` with `ambiguous_bug` (line ~422) and `BugReport` five times. Record the `severity` field from each run and print whether the model is consistent.
4. Implement experiment 2c: call `extract_structured()` with `incomplete_posting` (line ~435) and `JobPosting`. Print what the model fills in for fields like `required_skills` that have no source data.
5. Run the command:
   ```bash
   uv run python src/extractor.py --task2
   ```

**Expected result:**
- 2a: The model ignores the injection and extracts `job_title='Software Engineer'`, `company_name='Acme Corp'`. The schema constraint prevents freeform output.
- 2b: Severity classification varies between runs (e.g., 3x `"medium"`, 2x `"low"`). At `temperature=0` it should be consistent; at higher temperatures it may not be.
- 2c: The model fabricates plausible values for missing fields (e.g., `required_skills=["software development"]`). The output is schema-valid but semantically invented.
  ```
  2a. Prompt injection in source document
  job_title='Software Engineer'  company_name='Acme Corp'  (injection failed)

  2b. Ambiguous severity classification
  Run 1: medium | Run 2: medium | Run 3: medium | Run 4: medium | Run 5: medium

  2c. Required field absent from source document
  JobPosting(job_title='Developer', required_skills=['general development'], ...)
  ```

**Why this matters:**
Strict mode guarantees structural validity but not semantic accuracy. The model will always produce valid JSON matching your schema — but it will hallucinate values for fields missing from the source. Production pipelines must distinguish "model extracted this from the text" from "model invented this to satisfy the schema," typically by making ambiguous fields optional or adding a confidence field.

---

### Task 3: Extraction Pipeline

**Goal:** Build a concurrent extraction pipeline that processes multiple documents in parallel, demonstrating the practical pattern for batch-extracting structured data from a document corpus.

**What to do:**

1. Open `lab/src/extractor.py` and find the `DocumentMetadata` model (line ~212). Define its fields: `title` (str), `summary` (str), `key_topics` (list[str]), `estimated_reading_time_minutes` (int).
2. Find `extract_document_metadata()` (line ~448) and implement the call to `extract_structured()` with the file content and `DocumentMetadata` model.
3. Find `run_extraction_pipeline()` (line ~479) and implement the concurrent extraction: use `asyncio.gather(*[extract_document_metadata(client, f) for f in md_files])` to process all files in parallel.
4. Run the command:
   ```bash
   uv run python src/extractor.py --pipeline ../../../../modules
   ```

**Expected result:**
- A formatted table with one row per `.md` file found:
  ```
  ┌──────────────────────────────────────┬──────────────────────────────┬──────────────────────────────┬───────────┬────────┐
  │ File                                 │ Title                        │ Topics                       │ Read Time │ Status │
  ├──────────────────────────────────────┼──────────────────────────────┼──────────────────────────────┼───────────┼────────┤
  │ module-01-.../README.md              │ LLM Primitive                │ Azure OpenAI, API calls, ... │ 8m        │ OK     │
  │ module-02-.../README.md              │ Prompt Engineering           │ system prompts, few-shot,... │ 10m       │ OK     │
  │ module-03-.../README.md              │ Tool Use                     │ function calling, agent ...  │ 12m       │ OK     │
  │ ...                                  │ ...                          │ ...                          │ ...       │ ...    │
  └──────────────────────────────────────┴──────────────────────────────┴──────────────────────────────┴───────────┴────────┘
  ```
- All files process concurrently — total time is roughly the time of one extraction, not N extractions sequentially

**Why this matters:**
Batch extraction over a document corpus is one of the highest-value LLM applications in enterprise settings (e.g., extracting metadata from thousands of support tickets, contracts, or incident reports). The concurrent pattern here scales linearly until you hit rate limits, and the typed output integrates directly into downstream databases and APIs without manual parsing.

---

### Task 4: Flatten $defs

**Goal:** Implement the `flatten_schema()` function that inlines `$ref`/`$defs` from Pydantic-generated schemas, which is required because Azure OpenAI strict mode rejects schemas containing `$ref`.

**What to do:**

1. Open `lab/src/extractor.py` and find `_inline_refs()` (line ~65) and `flatten_schema()` (line ~89)
2. In `_inline_refs()`: when a node contains `"$ref"`, extract the type name from `"#/$defs/TypeName"`, look it up in `defs`, and recurse. When a node has `"type": "object"`, add `"additionalProperties": false`.
3. In `flatten_schema()`: pop `"$defs"` from the schema dict and pass it to `_inline_refs()`.
4. Run the command:
   ```bash
   uv run python src/extractor.py --task4
   ```

**Expected result:**
- The raw `CodeReview` schema is printed showing `$defs` and `$ref` entries for `ReviewIssue`
- The flattened schema is printed with `ReviewIssue` inlined and `additionalProperties: false` on every object
- The API call with the raw schema returns HTTP 400 with an error about unsupported `$ref`
- The API call with the flattened schema succeeds and returns a valid `CodeReview` object
  ```
  Raw CodeReview schema (has $defs/$ref):
  { "$defs": { "ReviewIssue": { ... } }, "properties": { "issues": { "$ref": "#/$defs/ReviewIssue" } } }

  Flattened schema (no $defs/$ref):
  { "properties": { "issues": { "items": { "type": "object", "properties": { ... }, "additionalProperties": false } } } }

  Attempt with raw (unflattened) schema:
  Expected error: HTTP 400

  Attempt with flattened schema:
  Success! Extracted CodeReview: CodeReview(issues=[...], overall_summary='...', approved=False)
  ```

**Why this matters:**
Pydantic generates `$ref`/`$defs` for any nested model, which is valid JSON Schema but rejected by Azure OpenAI's strict mode. Every production system that uses Pydantic with structured outputs needs this flattening step. Without it, any schema with nested objects fails at the API level — and most real-world extraction schemas have nested objects.

---

### Task 5: json_object vs. json_schema Comparison

**Goal:** Empirically measure the reliability gap between `json_object` mode (unconstrained structure) and `json_schema` strict mode (constrained decoding) to justify the additional setup cost of strict mode.

**What to do:**

1. Open `lab/src/extractor.py` and find `run_comparison()` (line ~604)
2. Implement the `json_object` loop: make 10 calls with `response_format={"type": "json_object"}`, timing each with `time.perf_counter()`. Check if `json.loads()` succeeds and if all `required_fields` are present in the parsed dict.
3. Implement the `json_schema` loop: make 10 calls using `make_response_format(JobPosting, "job_posting")`, tracking the same metrics.
4. The comparison table is already wired up — it will print after both loops complete.
5. Run the command:
   ```bash
   uv run python src/extractor.py --compare
   ```

**Expected result:**
- A comparison table similar to:
  ```
  ┌──────────────────────┬──────────────┬─────────────────────┬─────────────────┐
  │ Mode                 │ Parse Errors │ Compliance Failures │ Avg Latency (s) │
  ├──────────────────────┼──────────────┼─────────────────────┼─────────────────┤
  │ json_object          │ 0            │ 2                   │ 1.23            │
  │ json_schema (strict) │ 0            │ 0                   │ 1.41            │
  └──────────────────────┴──────────────┴─────────────────────┴─────────────────┘
  Compliance rate — json_object: 80%  |  json_schema: 100%
  ```
- `json_schema` mode shows 100% compliance at the cost of slightly higher latency (~10–15% more)
- `json_object` mode may produce extra fields, missing fields, or differently-named fields

**Why this matters:**
The ~15% latency overhead of strict mode is the cost of constrained decoding. In return, you eliminate an entire class of runtime failures — missing fields, wrong types, extra keys — that would otherwise require retry logic, fallback parsing, and manual validation. For any pipeline where downstream code depends on the schema, strict mode pays for itself on the first failure it prevents.

---

## Conceptual Checkpoints

1. Why does `strict: true` require `additionalProperties: false` on every
   object in the schema? What would happen without it?

2. Constrained decoding guarantees *structural* validity but not *semantic*
   validity. Give an example of a response that is schema-valid but
   semantically wrong for your `BugReport` model.

3. If you have a Pydantic model with an `Optional[str]` field, what JSON
   Schema does Pydantic generate for it? Does Azure OpenAI strict mode
   handle `null` values correctly?

4. Why might you choose a two-pass extraction strategy (extract then
   synthesise) over a single large extraction on a long document?

5. You receive a response with `finish_reason: "length"`. The JSON is
   truncated mid-object. Describe three different recovery strategies and
   the tradeoffs of each.

---

## Resources

- [Azure OpenAI structured outputs guide](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/structured-outputs)
- [Pydantic v2 JSON Schema generation](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [JSON Schema specification](https://json-schema.org/specification)
- [OpenAI structured outputs reference](https://platform.openai.com/docs/guides/structured-outputs)

---

**Next:** [Week 3 — Agentic Patterns: ReAct and Memory](../../weeks/week-03.md)
