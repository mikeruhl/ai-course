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

### Option B: Google Vertex AI

Use Vertex AI's OpenAI-compatible endpoint instead of Azure OpenAI for the
LLM calls. Azure-specific services still require Azure.

1. Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
2. Authenticate:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
3. Enable the Vertex AI API:
   ```bash
   gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
   ```
4. Set `LLM_PROVIDER=vertex` in your `.env` file and fill in `GCP_PROJECT_ID`.

### Tasks

| Task | Command | What you'll build |
|---|---|---|
| A | `uv run costperf --task A` | Token counter and cost calculator across models |
| B | `uv run costperf --task B` | Semantic cache with embedding similarity |
| C | `uv run costperf --task C` | Pipeline profiler with waterfall visualization |

### Task A: Token Counter

**Goal:** Show how token counts translate to dollar costs across models and how small differences compound at scale.

**What to do:**
1. Open `lab/src/cost_performance.py` and read `task_a` function (lines 93-173) and the `PRICING` dict (lines 47-53)
2. Trace how `estimate_tokens` (lines 89-90) approximates token count (~4 chars/token), then how costs are computed per model using `(input_tokens * input_price + output_tokens * output_price) / 1_000_000` (line 125)
3. Run:
   ```bash
   cd lab && uv run costperf --task A
   ```

**Expected result:**
- A Token Estimates table showing four prompts (Simple, Medium, Long system prompt, RAG context) with estimated input/output tokens and per-call cost for gpt-4o-mini, gpt-4o, and gpt-4-turbo
- An Actual Token Usage table from a real API call showing prompt tokens, completion tokens, and cost at two price points
- A Monthly Cost projection table at 1000 calls/day for 30 days

```
Token Estimates & Cost per Call
┌──────────────────┬──────────┬──────────┬──────────────┬──────────────┬──────────────┐
│ Prompt           │ Est. In  │ Est. Out │ gpt-4o-mini  │ gpt-4o       │ gpt-4-turbo  │
├──────────────────┼──────────┼──────────┼──────────────┼──────────────┼──────────────┤
│ Simple           │ 4        │ 2        │ $0.000002    │ $0.000030    │ $0.000100    │
│ RAG context      │ 513      │ 256      │ $0.000231    │ $0.003843    │ $0.012810    │
└──────────────────┴──────────┴──────────┴──────────────┴──────────────┴──────────────┘

Monthly Cost @ 1K calls/day
│ gpt-4o-mini  │ $6.30    │
│ gpt-4o       │ $97.50   │
│ gpt-4-turbo  │ $330.00  │
```

**Why this matters:**
Model selection is the single highest-leverage cost decision for agents. A 10-step agent running at GPT-4o prices can cost 15x more than the same agent on GPT-4o-mini. This exercise builds the habit of estimating costs before deploying and makes the tradeoff concrete.

### Task B: Semantic Cache

**Goal:** Demonstrate that embedding-based caching catches paraphrased queries that exact-match caching would miss.

**What to do:**
1. Open `lab/src/cost_performance.py` and read the `SemanticCache` class (lines 188-212) and `task_b` function (lines 215-258)
2. Study how `lookup` (lines 196-209) computes cosine similarity against all cached embeddings and returns a hit when similarity exceeds `0.90` (line 192). Note the seven test queries (lines 221-229) — three are semantic duplicates
3. Run:
   ```bash
   cd lab && uv run costperf --task B
   ```

**Expected result:**
- Seven queries processed in order. The first unique query is a CACHE MISS. Paraphrases ("Tell me the capital city of France", "What's France's capital?", "Can you explain quantum computing simply?") register as CACHE HITs
- Different topics ("capital of Germany", "weather today") are CACHE MISSes
- Cache Stats table showing ~3 hits, ~4 misses, ~43% hit rate

```
  CACHE MISS (820ms): What is the capital of France?
  CACHE HIT  (95ms):  Tell me the capital city of France.
  CACHE HIT  (88ms):  What's France's capital?
  CACHE MISS (790ms): What is the capital of Germany?
  CACHE MISS (830ms): Explain quantum computing in simple terms.
  CACHE HIT  (92ms):  Can you explain quantum computing simply?
  CACHE MISS (810ms): What is the weather like today?

Cache Stats: Entries=4, Hits=3, Misses=4, Hit rate=43%
```

**Why this matters:**
Real user traffic contains many paraphrases of the same question. A semantic cache with a 0.90 similarity threshold typically yields 20-40% hit rates in production, directly cutting LLM costs and latency. The threshold is a precision/recall tradeoff — too low and you return wrong answers for different questions; too high and you miss valid paraphrases.

### Task C: Pipeline Profiler

**Goal:** Instrument each stage of an agent pipeline with timing to identify where latency is spent.

**What to do:**
1. Open `lab/src/cost_performance.py` and read the `PipelineProfiler` class (lines 276-304) and `task_c` function (lines 307-357)
2. Trace the five profiled stages: `embed_query` (lines 316-318), `retrieve_docs` (lines 321-331), `construct_prompt` (lines 334-340), `llm_generation` (lines 343-346), `output_validation` (lines 349-351). Note how `start`/`stop` (lines 283-288) record `TimingEntry` objects and `report` (lines 290-304) renders a waterfall bar chart
3. Run:
   ```bash
   cd lab && uv run costperf --task C
   ```

**Expected result:**
- The agent answers a question about securing AI agents in production using retrieved context
- A Pipeline Profile table with each step's duration in milliseconds, percentage of total, and a visual waterfall bar
- LLM generation dominates at ~60-70% of total time

```
Pipeline Profile (total: 1340ms)
┌──────────────────────┬──────────┬──────────┬──────────────────────────────────┐
│ Step                 │ Duration │ % Total  │ Waterfall                        │
├──────────────────────┼──────────┼──────────┼──────────────────────────────────┤
│ embed_query          │ 95       │ 7.1%     │ ███░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ retrieve_docs        │ 210      │ 15.7%    │ ██████░░░░░░░░░░░░░░░░░░░░░░░░ │
│ construct_prompt     │ 1        │ 0.1%     │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ llm_generation       │ 920      │ 68.7%    │ ██████████████████████████████░ │
│ output_validation    │ 1        │ 0.1%     │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
└──────────────────────┴──────────┴──────────┴──────────────────────────────────┘
```

**Why this matters:**
Without instrumentation, teams often optimize the wrong stage. This profiler confirms that LLM generation is the bottleneck (60-80% of wall time), which means the highest-ROI optimizations are shorter prompts, faster models, and streaming — not faster retrieval or validation logic.

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
