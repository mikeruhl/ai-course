# Module 1: LLM as a Compute Primitive

**Week 1 · Phase 1 — Foundations**

---

## Learning Objectives

By the end of this module you will:

- Understand what an LLM actually *is* at the API level (not marketing)
- Know what tokens are, why they matter, and how to count them precisely
- Understand why every LLM call is stateless and what that means for your design
- Have made raw REST calls to an LLM API — no SDK, no abstraction
- Have built intuition for latency, variance, and temperature effects

---

## Prerequisites

- [Course setup](../../setup/README.md) complete (uv installed)
- **Ollama** installed locally (`ollama pull llama3.1`) — free, no account needed
- *Optional*: Azure subscription (for comparing with Azure OpenAI later)

No prior ML knowledge needed. Strong REST API familiarity assumed.

---

## Concepts

### The Core Mental Model

An LLM is a pure function:

```
f(tokens_in) -> tokens_out
```

It has **no memory. No state. No identity.** Every API call is independent.
"Memory", "personality", and "context" are illusions created by what you
put in the prompt. This is the most important thing to internalize before
building agentic systems.

When an agent "remembers" something from 5 turns ago, that's because your
application code retrieved it and included it in the current prompt.
The model doesn't remember — you do.

### Tokens: The Unit of Everything

Tokens are the atomic unit of LLM I/O. They determine:
- **Cost** — you pay per input token and per output token (output costs more)
- **Speed** — time-to-first-token and tokens/second are your latency metrics
- **Capacity** — the context window is measured in tokens

Rules of thumb:
- 1 token ≈ 0.75 English words
- 1 token ≈ 3–4 characters
- "hello world" = 2 tokens; a 1,000-word document ≈ 1,333 tokens
- Code is denser — a 100-line Python file might be 800–1,500 tokens

Tokenization is **model-specific**. GPT-4o and GPT-4o-mini use the same
tokenizer (cl100k_base via tiktoken). Claude uses a different one.
Always use the correct tokenizer when budgeting context.

Why staff engineers care about this:
- A naively-built agent that passes full conversation history on every turn
  can easily burn 50k tokens per interaction at scale
- Token budgets are the difference between $10/day and $10,000/day

### Context Window

The maximum tokens the model processes in a single call (input + output combined):

| Model | Context Window |
|---|---|
| gpt-4o | 128k tokens |
| gpt-4o-mini | 128k tokens |
| claude-sonnet-4-5 | 200k tokens |
| gemini-1.5-pro | 1M tokens |

**Larger window ≠ better recall.** Research shows models lose coherence
with content in the middle of very long contexts ("lost in the middle"
problem). Practical guidance: keep working context under 50–80k tokens
for complex reasoning tasks.

For agents: you will constantly be deciding *what to include* in the context
window. This is one of the core engineering challenges.

### Temperature and Sampling

Temperature controls how "random" the model's token selection is:

| Temperature | Behavior | Use case |
|---|---|---|
| 0 | Near-deterministic | Tool selection, structured output, routing |
| 0.3–0.5 | Slightly varied | Classification, extraction, factual Q&A |
| 0.7–1.0 | Creative, varied | Drafting, brainstorming, summarization |
| > 1.0 | Chaotic | Rarely useful |

**For agent tool calls, always use temperature 0.** You want deterministic
decisions. A temperature-1.0 tool selection loop will make inconsistent
choices and is much harder to debug.

`top_p` (nucleus sampling): leave at 1.0 unless you have a specific reason
to change it. Don't set both temperature and top_p to non-default values.

### The Conversation Array IS the Program

```json
[
  {"role": "system",    "content": "You are a code review assistant..."},
  {"role": "user",      "content": "Review this diff: ..."},
  {"role": "assistant", "content": "I found 3 issues..."},
  {"role": "user",      "content": "Can you elaborate on issue #2?"}
]
```

- **System message** — your application's config, behavior contract, output format
- **User messages** — runtime input
- **Assistant messages** — prior model responses you want it to build on

This array is reconstructed from scratch on every API call. Your application
is responsible for maintaining it, truncating it when it gets too long,
and deciding what context to include.

### The Response Object

Understanding the full response before any SDK abstracts it:

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1709123456,
  "model": "gpt-4o-mini-2024-07-18",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The capital of France is Paris."
      },
      "finish_reason": "stop",
      "logprobs": null
    }
  ],
  "usage": {
    "prompt_tokens": 18,
    "completion_tokens": 9,
    "total_tokens": 27
  }
}
```

Key fields to always log:
- `usage` — your cost and token budget tracking
- `finish_reason` — `stop` (normal), `length` (hit max_tokens), `tool_calls` (agent mode), `content_filter` (blocked)
- `model` — verify you're calling the model you think you are

---

## Setup

### Option A: Ollama (Recommended for getting started — free, local)

1. Install Ollama: https://ollama.com
2. Pull a model:
   ```bash
   ollama pull llama3.1
   ```
3. Ollama runs at `http://localhost:11434` by default — no API key needed.

### Option B: Azure OpenAI (Used in later modules)

If you want to use Azure OpenAI for this module, provision resources with
terraform (see `terraform/` directory), then set `LLM_PROVIDER=azure` in
your `.env` file.

---

## Lab Setup

```bash
cd modules/module-01-llm-primitive/lab
cp .env.example .env    # defaults to Ollama — no changes needed
uv sync                 # installs dependencies
```

> **Note**: Module 01 uses `tiktoken` for token counting. Tiktoken is the
> tokenizer for GPT-4o/GPT-4o-mini. Ollama models use different tokenizers,
> so exact token counts may differ from API-reported usage. The concepts
> (tokens, cost, context windows) still apply.

---

## Lab Tasks

### Task 1: Raw curl call

Before writing any Python, make a raw HTTP call to understand the wire format:

```bash
# Ollama (default)
curl -X POST "http://localhost:11434/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.1",
    "messages": [{"role": "user", "content": "What is 2 + 2?"}],
    "max_tokens": 50
  }'
```

Study the full response. Find `usage`, `finish_reason`, `model`.

### Task 2: Python replication

Replicate the curl call in `src/explore.py` using `httpx`.
Do NOT use the `openai` SDK yet — raw httpx only.

Log the full response object with `json.dumps(response, indent=2)`.

### Task 3: Token counting

Using `tiktoken`, count the tokens in:
1. A short sentence
2. A 500-word document
3. A 100-line Python file

Compare your counts to the `usage.prompt_tokens` in the API response.
They should match exactly.

### Task 4: Temperature experiment

Run the same creative prompt 10 times at `temperature=1.0`.
Run it 10 more times at `temperature=0`.

Prompt suggestion: *"Name a color that doesn't exist."*

Log all 20 responses. What do you observe?

### Task 5: Latency profiling

Make 20 sequential calls to the API. Record:
- Time to first token (use streaming — covered in the starter code)
- Total request time

Calculate p50 and p95 latency. What's the variance?

> Hint: Use `time.perf_counter()` around each call.

### Task 6: "Lost in the middle" demo

Construct a prompt where the answer is buried in the middle of a long
context (pad with lorem ipsum text before and after).

Test at:
- 1k tokens of padding
- 10k tokens of padding
- 50k tokens of padding

Does the model's accuracy degrade? At what point?

---

## Conceptual Checkpoints

Answer these in your own words before moving to Module 2:

1. Why does every LLM call need to include the full conversation history?
2. What does `finish_reason: "length"` tell you about your request?
3. If you're building an agent that processes 10,000 requests/day,
   why does the difference between 500 and 5,000 prompt tokens matter?
4. Why should you use temperature 0 for tool selection?
5. What's the difference between the context window limit and the
   practical useful context limit?

---

## Teardown

If using Ollama, no teardown needed — it runs locally.

If using Azure OpenAI and you won't use it for a while:

```bash
cd terraform
terraform destroy
```

---

## Resources

- [Azure OpenAI REST API reference](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference)
- [tiktoken on GitHub](https://github.com/openai/tiktoken)
- ["Lost in the Middle" paper (arXiv)](https://arxiv.org/abs/2307.03172)
- [Azure OpenAI pricing](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/)

---

**Next:** [Module 2 — Prompt Engineering at Staff Level](../module-02-prompt-engineering/README.md)
