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

In `src/extractor.py`, three Pydantic models are already scaffolded:
`JobPosting`, `BugReport`, and `CodeReview`.

Your job:

1. Complete the field definitions — add appropriate types and `Field(description=...)`
   annotations that will guide the model
2. Call `model_json_schema()` on each, inspect the output — note any `$defs`
3. Call `flatten_schema()` on each schema
4. Make an Azure OpenAI call with `response_format` set to `json_schema` + `strict: true`
5. Parse the response with `json.loads()` and validate with `Model.model_validate()`

Run the provided test inputs (at the bottom of the file) and verify you get
valid, typed Python objects back.

```bash
uv run python src/extractor.py --task1
```

### Task 2: Try to Break Strict Mode

Experiment with inputs that should push the model's limits:

1. **Refusal trigger:** Submit a prompt asking the model to extract PII from
   a document that contains instructions to "ignore previous instructions".
   Does it refuse? Does the schema enforcement hold?

2. **Near-limit ambiguity:** Submit a document that is genuinely ambiguous
   for your schema — e.g., a bug report that could be severity `"high"` or
   `"critical"`. What does the model choose? Does it always choose consistently?

3. **Missing information:** Submit a document where a required field simply
   does not exist in the source material. What does the model fill in?
   Is the output still schema-valid?

4. **Schema violation attempt:** In a separate prompt (not using strict mode),
   ask the model to produce a JSON response that violates a specific constraint
   (e.g., put a string in an integer field). Then turn strict mode back on —
   does the constraint hold?

Log your observations for each experiment.

```bash
uv run python src/extractor.py --task2
```

### Task 3: Extraction Pipeline

Implement `run_extraction_pipeline()` in `src/extractor.py`.

The function should:

1. Accept a directory path as input
2. Find all `.md` files in the directory
3. For each file, extract a `DocumentMetadata` object (title, summary,
   key_topics, estimated_reading_time_minutes) using Azure OpenAI
4. Process all files concurrently (use `asyncio.gather`)
5. Print a formatted table of results using `rich.table`

Test it on the course `modules/` directory:

```bash
uv run python src/extractor.py --pipeline ../../../../modules
```

You should see a table with one row per README.md found.

**Think about:** what happens when a README has fewer than 200 words?
Is "estimated_reading_time_minutes" meaningful? What does the model do?

### Task 4: Flatten $defs

Implement the `flatten_schema()` function completely. The stub is provided.

Steps:

1. Create a Pydantic model that references another model (e.g., `JobPosting`
   with a nested `Salary` model). Call `model_json_schema()` — observe the `$defs`.
2. Implement `flatten_schema()` to recursively inline all `$ref` references
3. Add `"additionalProperties": false` to every `"type": "object"` node
4. Verify the flattened schema works by sending it to the API with `strict: true`
5. Send the **unflattened** schema to the API — observe the error you get

The test:
```bash
uv run python src/extractor.py --task4
```

### Task 5: json_object vs. json_schema Comparison

Implement `run_comparison()` in `src/extractor.py`.

Run 10 calls with `json_object` mode and 10 calls with `json_schema + strict`
mode using the same prompt and schema. Measure and print:

1. **Schema compliance rate:** what percentage of `json_object` responses
   have all required fields? (Check against your Pydantic model)
2. **Parse error rate:** what percentage of responses fail `json.loads()`?
3. **Latency:** average response time for each mode

```bash
uv run python src/extractor.py --compare
```

Expected results: `json_schema` mode should show near-100% compliance.
`json_object` mode compliance depends heavily on prompt quality and schema
complexity — document what you observe.

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
