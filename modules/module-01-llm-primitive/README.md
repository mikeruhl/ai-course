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

**Goal:** Replicate the curl call from Task 1 in Python using raw `httpx` —
no SDK, no abstraction layer. You need to see the HTTP request/response cycle
without anything hiding it from you.

**What to do:**

1. Open `src/explore.py` — the starter code and `chat()` helper are already
   written for you.
2. Look at the `task2_raw_response()` function (line ~59). It calls
   `chat()` with the same `"What is 2 + 2?"` prompt from Task 1.
3. Run it:
   ```bash
   uv run python src/explore.py
   ```
   (By default all tasks run. You can comment out later tasks in the
   `if __name__ == "__main__"` block at the bottom of the file.)

**Expected result:**

The full JSON response object printed to your terminal, including:
- `choices[0].message.content` — the model's answer
- `choices[0].finish_reason` — should be `"stop"` (meaning the model
  finished naturally, not because it ran out of tokens)
- `usage` — shows `prompt_tokens`, `completion_tokens`, `total_tokens`
- `model` — the actual model that responded

**Why this matters:**

Every SDK (OpenAI, LangChain, Semantic Kernel) wraps this exact HTTP call.
When something goes wrong in production — a 429 rate limit, an unexpected
`finish_reason: "length"`, a model routing error — you need to understand
what's happening at the wire level. Debugging through SDK abstractions is
painful if you've never seen the raw response.

---

### Task 3: Token counting

**Goal:** Build intuition for how text maps to tokens and verify that
client-side counting matches what the API reports.

**What to do:**

1. Look at the `task3_token_counting()` function in `src/explore.py`
   (line ~78).
2. It uses `tiktoken` to count tokens for three sample texts: a short
   sentence, a medium paragraph, and a Python code snippet.
3. Run it:
   ```bash
   uv run python src/explore.py
   ```
4. **After reviewing the output**, add a few lines to make an API call
   with one of the sample texts and compare your `tiktoken` count to
   `response["usage"]["prompt_tokens"]`. The starter code has a `TODO`
   comment marking where to add this.

**Expected result:**

Output like:
```
short_sentence:
  chars: 44
  tokens (tiktoken): 10
  ratio: 4.4 chars/token

medium_text:
  chars: 1,200
  tokens (tiktoken): 236
  ratio: 5.1 chars/token
```

The chars-per-token ratio varies by content type. English prose is typically
3–4 chars/token. Code tends to be denser (more tokens per character) because
of syntax characters and shorter identifiers.

> **Note:** If you're using Ollama, the `tiktoken` count won't match the
> API's `usage.prompt_tokens` exactly because Ollama models use a different
> tokenizer. The counts will be close but not identical. With Azure OpenAI
> (GPT-4o/GPT-4o-mini), they should match exactly.

**Why this matters:**

Tokens are the unit of cost and capacity. A naively built agent that dumps
full conversation history into every call can easily hit 50k tokens per
request. At GPT-4o pricing (~$2.50/M input tokens), that's $0.125 per
call — which at 10,000 requests/day is **$1,250/day**. Knowing how to
count tokens client-side lets you budget context before sending the request,
implement truncation strategies, and avoid surprise bills.

---

### Task 4: Temperature experiment

**Goal:** See firsthand how temperature affects output determinism — and
understand why this matters for agent tool selection.

**What to do:**

1. Look at `task4_temperature_experiment()` in `src/explore.py` (line ~116).
2. It sends the same creative prompt 10 times at `temperature=0` and
   10 times at `temperature=1.0`.
3. Run it:
   ```bash
   uv run python src/explore.py
   ```

**Expected result:**

- **Temperature 0:** All 10 responses should be identical (or nearly
  identical — some APIs have minor non-determinism even at temp 0).
  You'll see `Unique responses: 1/10` or `2/10`.
- **Temperature 1.0:** Responses will vary significantly. You'll see
  `Unique responses: 7/10` or more — different fantasy color names
  each time.

Example output:
```
Temperature 0.0 (10 runs):
  Run  1: Emberwynn
  Run  2: Emberwynn
  ...
  Unique responses: 1/10

Temperature 1.0 (10 runs):
  Run  1: Glimshade
  Run  2: Verdanthra
  ...
  Unique responses: 9/10
```

**Why this matters:**

In agentic systems, the model makes decisions: which tool to call, what
parameters to pass, whether to continue or stop. These decisions must be
**deterministic and reproducible**. If your agent calls a "search" tool at
temperature 1.0, it might pick "search" in one run and "browse" in
another — making the system impossible to debug and test. **Always use
temperature 0 for tool selection and routing decisions.** Reserve higher
temperatures for creative generation tasks (drafting emails, brainstorming).

---

### Task 5: Latency profiling

**Goal:** Measure real LLM call latency and understand its variance —
this directly affects how you design user-facing features.

**What to do:**

1. Look at `task5_latency_profiling()` in `src/explore.py` (line ~153).
2. It makes 20 sequential calls with a trivial prompt and times each one
   using `time.perf_counter()`.
3. Run it:
   ```bash
   uv run python src/explore.py
   ```

**Expected result:**

With Ollama running locally, you'll see something like:
```
Call  1: 245ms  (3 tokens out)
Call  2: 189ms  (3 tokens out)
...
Results:
  p50: 200ms
  p95: 380ms
  min: 170ms
  max: 420ms
  std: 55ms
```

With a cloud API (Azure OpenAI), latencies will be higher and more
variable (200–800ms typical, with occasional spikes over 1s).

Key things to notice:
- **First call** is often slower (cold start / connection setup)
- **p95 is often 2–3x p50** — tail latency is real
- Even a trivial prompt has non-trivial latency

**Why this matters:**

An agent that makes 5 sequential LLM calls to answer one question will
have its latencies *added together*. If p50 is 300ms, 5 sequential calls
= 1.5s best case. But at p95, those same 5 calls = 4.5s — a noticeable
delay for a user. This is why agent architectures try to parallelize
independent LLM calls and minimize the number of sequential round-trips.
Understanding your latency distribution is essential for setting realistic
user expectations and designing timeout/retry strategies.

---

### Task 6: "Lost in the middle" demo

**Goal:** Demonstrate that LLMs don't process all parts of their context
window equally well — a critical insight for RAG and agent memory design.

**What to do:**

1. Look at `task6_lost_in_middle()` in `src/explore.py` (line ~188).
2. It buries a "needle" (`The secret code word is: ZEPHYR-7`) in the
   middle of increasing amounts of filler text, then asks the model to
   recall it.
3. Run it:
   ```bash
   uv run python src/explore.py
   ```

**Expected result:**

```
Testing recall at different context depths:
  Padding ~500 tokens: recalled=True   answer='ZEPHYR-7'
  Padding ~2,500 tokens: recalled=True   answer='ZEPHYR-7'
  Padding ~10,000 tokens: recalled=True   answer='The secret code word is ZEPHYR-7'
  Padding ~30,000 tokens: recalled=False  answer='I could not find a code word...'
```

The exact failure point depends on the model. Smaller models (llama3.1 8B)
may start failing around 10k tokens. Larger models hold out longer but
still degrade. The key pattern: **information at the beginning and end of
the context is recalled better than information in the middle.**

> **Note:** If you're using Ollama with an 8B model and the largest padding
> sizes, the call may be slow or fail with a timeout. Reduce the multiplier
> range in the code if needed.

**Why this matters:**

This is the "lost in the middle" problem documented in
[research](https://arxiv.org/abs/2307.03172). It has direct implications
for two agent patterns you'll build later:
1. **RAG retrieval** — if you retrieve 20 chunks and stuff them all into
   the prompt, the model may ignore the ones in the middle. Fewer,
   better-ranked chunks outperform bulk retrieval.
2. **Agent memory** — if your agent accumulates a long conversation
   history, important context from 10 turns ago (now in the middle of the
   prompt) may effectively be invisible. This is why agents need explicit
   memory management — summarization, selective retrieval, or sliding
   window strategies.

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
