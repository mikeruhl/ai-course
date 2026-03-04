# Module 24: Cost & Performance

## Overview

A single LLM call is cheap. An agent that makes 50 calls per task, running
1000 tasks per day, at GPT-4o prices, costs $750/day in tokens alone. Agents
amplify costs because they loop — every retry, every tool call, every
reflection step multiplies token spend.

This module covers token economics, caching strategies, prompt optimization,
rate limit management, and latency profiling. The goal: build agents that are
fast, cheap, and observable.

---

## Concepts

### 1. Token Economics

LLM pricing is based on tokens (roughly 4 characters per token in English).
Input tokens and output tokens are priced differently.

```
Pricing per 1M tokens (as of early 2025):

Model                      Input     Output
─────────────────────────────────────────────
GPT-4o                     $2.50     $10.00
GPT-4o-mini                $0.15     $0.60
GPT-4 Turbo                $10.00    $30.00
text-embedding-3-small     $0.02     —
text-embedding-3-large     $0.13     —
```

Output tokens are 2-4x more expensive than input tokens because generation
is computationally harder (autoregressive decoding).

**Agent cost formula**:
```
cost = Σ (input_tokens × input_price + output_tokens × output_price)
       for each LLM call in the agent's execution
```

A ReAct agent that takes 8 steps with an average of 1000 input tokens and
200 output tokens per step at GPT-4o-mini prices:
```
8 × (1000 × $0.15/1M + 200 × $0.60/1M) = $0.002 per task
At 1000 tasks/day: $2/day = $60/month
```

Same agent at GPT-4o prices:
```
8 × (1000 × $2.50/1M + 200 × $10.00/1M) = $0.036 per task
At 1000 tasks/day: $36/day = $1,080/month
```

Model selection is the single highest-leverage cost decision.

### 2. Model Selection Strategy

Not every agent step needs the most capable model.

```
Step                    Model Choice         Rationale
──────────────────────────────────────────────────────────
Query classification    GPT-4o-mini          Simple routing decision
Tool argument gen       GPT-4o-mini          Structured output, low complexity
Complex reasoning       GPT-4o               Multi-step logic
Code generation         GPT-4o               Correctness matters
Summarization           GPT-4o-mini          Compression, not creation
Embeddings              text-embedding-3-sm  Cost-effective for most use cases
```

**Model routing**: use a cheap model to classify the query difficulty, then
route to the appropriate model. This is essentially a cost-quality tradeoff.

### 3. Caching Strategies

Three caching approaches for LLM calls:

**Exact-match cache**: hash the full prompt, return cached response if seen
before. Hit rate depends on query diversity — works well for FAQ-style
workloads, poorly for open-ended conversations.

**Semantic cache**: embed the query, find the most similar cached query by
cosine similarity, return its response if similarity exceeds a threshold
(typically 0.90-0.95). Catches paraphrases that exact-match misses.

```
"What is the capital of France?" → cached
"Tell me France's capital"       → semantic match (similarity 0.94) → cache hit
"What is the capital of Germany?" → no match → cache miss
```

**Prompt cache** (Azure OpenAI feature): Azure OpenAI caches the prompt
prefix server-side. If your next request has the same prefix (system prompt
+ first N messages), the cached portion is processed at 50% discount.
This benefits agents with long, stable system prompts.

### 4. Prompt Optimization

Shorter prompts = fewer input tokens = lower cost. But prompt length
competes with quality.

Optimization techniques:
- **Remove boilerplate**: cut unnecessary politeness, headers, examples
- **Compress few-shot examples**: use 2 instead of 5 examples; make each
  example shorter
- **Dynamic context**: only include relevant context, not everything
- **Reference documents by ID**: instead of stuffing full documents into
  the prompt, retrieve and inject only relevant chunks (RAG)
- **System prompt caching**: keep the system prompt stable across calls
  to benefit from prompt cache discounts

### 5. Batching and Request Coalescing

**Embedding batching**: Azure OpenAI embedding API accepts up to 16 texts
per request. Batching 16 texts into one call vs 16 individual calls reduces
HTTP overhead by 15x.

**Request coalescing**: if multiple users ask similar questions within a
short window, serve them from a single LLM call + cache.

### 6. Rate Limit Management

Azure OpenAI enforces two rate limits:
- **RPM** (Requests Per Minute): max concurrent requests
- **TPM** (Tokens Per Minute): max token throughput

When either is exceeded, the API returns HTTP 429.

Management strategies:
- **Token estimation**: before sending, estimate token count to predict
  whether you'll exceed TPM. Defer or batch if close to the limit.
- **Request queuing**: buffer requests and release at a controlled rate.
- **Global deployments**: Azure global deployments route across regions,
  providing higher default limits.
- **PTU (Provisioned Throughput Units)**: guaranteed capacity at a fixed
  hourly rate. Cost-effective at sustained high volumes.

### 7. Latency Optimization

Agent latency is dominated by LLM calls (200-2000ms each). For an 8-step
agent, that's 1.5-16 seconds of LLM time alone.

Optimization techniques:
- **Streaming**: start processing the response as tokens arrive instead
  of waiting for the full response
- **Parallel tool calls**: when multiple tools are independent, call them
  concurrently (Azure OpenAI supports parallel function calling)
- **Speculative execution**: start the next likely step before the current
  one finishes; discard if the prediction was wrong
- **Model routing**: use faster models for simple steps
- **Prompt length**: shorter prompts have lower time-to-first-token

### 8. Cost Monitoring

Track costs at multiple granularities:

```
Per-call:   token usage from API response headers
Per-task:   sum of all calls in one agent execution
Per-user:   aggregate across all tasks for a user
Per-day:    daily budget monitoring with alerts
Per-month:  Azure Cost Management reports
```

Set **budget alerts** at 50%, 80%, and 100% of your monthly budget. A
runaway agent (infinite loop, prompt injection causing verbose outputs)
can burn through a month's budget in hours.

### 9. Performance Profiling

Profile where time goes in your agent pipeline:

```
Typical latency breakdown:
  Embedding query:        50ms   (5%)
  Retrieval (AI Search):  200ms  (15%)
  LLM generation:         800ms  (65%)
  Tool execution:         100ms  (10%)
  Output validation:      10ms   (1%)
  Network overhead:       50ms   (4%)
```

Instrument each step with timing and visualize as a waterfall chart.
The bottleneck is almost always LLM generation — optimize there first.

---

## Lab

### Setup
```bash
cp lab/.env.example lab/.env
# Fill in your Azure OpenAI credentials
cd lab && uv sync
```

### Tasks

| Task | Command | What you'll build |
|---|---|---|
| A | `uv run costperf --task A` | Token counter and cost calculator across models |
| B | `uv run costperf --task B` | Semantic cache with embedding similarity |
| C | `uv run costperf --task C` | Pipeline profiler with waterfall visualization |

### Task A: Token Counter

Estimate token counts for various prompts, calculate costs at different model
price points, make a real API call to see actual usage, and project monthly
costs at scale.

### Task B: Semantic Cache

Implement an embedding-based cache. Send several queries, observe cache hits
for paraphrases and misses for different topics. Compare latency of cached
vs uncached responses.

### Task C: Pipeline Profiler

Instrument a multi-step agent pipeline (embed → retrieve → prompt → generate
→ validate) with timing. Display a waterfall chart showing where latency goes.

---

## Key Takeaways

1. Model selection is the highest-leverage cost decision — GPT-4o-mini is
   10-20x cheaper than GPT-4o for tasks where it performs adequately.
2. Semantic caching catches paraphrases that exact-match caching misses,
   typically yielding 20-40% hit rates on real workloads.
3. Always set per-task token budgets and monthly cost alerts — a single
   runaway agent can burn through your entire budget.
4. LLM generation dominates latency (60-80%). Optimize there first:
   shorter prompts, faster models, streaming, parallel tool calls.
5. Batch embedding requests (16 per call) to reduce HTTP overhead by 15x.

---

## Further Reading

- Azure OpenAI pricing page
- Azure OpenAI rate limits and quotas
- Azure Cost Management documentation
