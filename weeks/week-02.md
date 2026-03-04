# Week 2: Async Agents + Structured Outputs

**Phase 1 — Foundations**

---

## Goal

Go deeper on two capabilities that are non-negotiable for production agents:
throughput and type safety.

By end of week: you can run multiple agent tasks concurrently, stream tokens
to users in real time, and guarantee that every LLM output is a validated
Python object — not a string you hope parses correctly.

---

## Module 4: Async Agent Loops + Streaming

**Path:** [`modules/module-04-async-streaming/`](../modules/module-04-async-streaming/README.md)

The synchronous agent loop from Module 3 is correct but slow. One network
request blocks everything else. In production, agents serve many users and
execute many tool calls — async is a requirement, not an optimisation.

**What you will build:**
- A fully async agent using `httpx.AsyncClient` and `asyncio`
- Parallel tool call execution with `asyncio.gather`
- SSE streaming to print tokens as they arrive
- A benchmark showing concrete wall-clock speedup (typically 3–4x on 5 tasks)

**Key concepts:**
- `asyncio.gather` for I/O-bound concurrency
- The SSE streaming protocol: `data: {json}\n\n` + `data: [DONE]`
- Delta accumulation for both text tokens and tool call argument fragments
- When streaming improves UX vs. when batching improves throughput

---

## Module 5: Structured Outputs at Depth

**Path:** [`modules/module-05-structured-outputs/`](../modules/module-05-structured-outputs/README.md)

Returning raw JSON strings from an LLM and crossing your fingers is not
a production strategy. Azure OpenAI's strict JSON schema mode combined with
Pydantic gives you constrained decoding — the model is mechanically prevented
from generating output that violates your schema.

**What you will build:**
- Three Pydantic v2 extraction models (job posting, bug report, code review)
- A `flatten_schema()` utility that inlines `$defs`/`$ref` (required for the API)
- An async extraction pipeline that processes a directory of files concurrently
- A comparison harness: `json_object` vs. `json_schema` mode across 10 calls

**Key concepts:**
- `response_format: json_schema` with `strict: true` and `additionalProperties: false`
- Pydantic `model_json_schema()` as the single source of truth
- The `$defs` problem and how to flatten it programmatically
- Failure modes: `finish_reason` values, refusal field, truncation handling

---

## Week 2 Checklist

### Environment
- [ ] Azure OpenAI from Module 1 still running
- [ ] `uv sync` in both module labs

### Lab Completions
- [ ] Module 4 Task 1: async agent loop with asyncio.gather
- [ ] Module 4 Task 2: streaming text, tokens print live
- [ ] Module 4 Task 3: streaming handles tool call deltas
- [ ] Module 4 Task 4: benchmark — sequential vs concurrent with speedup number recorded
- [ ] Module 4 Task 5: rich progress display
- [ ] Module 5 Task 1: three extraction models, validated Pydantic objects returned
- [ ] Module 5 Task 2: edge case experiments documented
- [ ] Module 5 Task 3: pipeline processes a directory, results in a table
- [ ] Module 5 Task 4: flatten_schema() implemented and verified
- [ ] Module 5 Task 5: comparison table showing compliance rates

### Conceptual Checkpoints
- [ ] Can explain why asyncio.gather does not help CPU-bound tools
- [ ] Can explain the delta accumulation pattern for streaming tool calls
- [ ] Can draw the SSE protocol: what each line looks like, what [DONE] means
- [ ] Can explain why $ref is unsupported in strict mode and how flattening fixes it
- [ ] Can list all finish_reason values and the correct handling for each
- [ ] Can explain the difference between structural validity and semantic validity

---

## What's Next: Week 3

Week 3 begins Phase 2 — Agentic Patterns:

- **Module 6:** ReAct (Reasoning + Acting) — the thinking-before-acting pattern
  that dramatically improves multi-step agent accuracy
- **Module 7:** Planning patterns — task decomposition, parallel subtask execution,
  plan-then-execute vs. interleaved planning
- **Module 8:** Memory systems — conversation buffers, summarisation, vector
  retrieval, episodic vs. semantic memory

Week 3 starts assuming you have the raw loop, async execution, and structured
outputs down cold. Those three capabilities are the foundation for everything
in Phases 2–7.

---

## Resources

- [Azure OpenAI streaming guide](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/streaming)
- [Azure OpenAI structured outputs guide](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/structured-outputs)
- [httpx async client](https://www.python-httpx.org/async/)
- [Pydantic v2 JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [asyncio.gather docs](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather)

---

**Previous:** [Week 1](./week-01.md) | **Next:** Week 3 (coming soon)
