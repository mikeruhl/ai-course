# Module 21: Observability for Agents

## Why This Module Exists

You cannot `assertEqual` an agent's output. Non-deterministic systems break traditional
test-driven development. When your agent fails in production — and it will — you need to
answer two different questions:

- **What happened?** (debugging) — Traces answer this.
- **How good is it?** (quality) — Evals answer this.

This module builds both: OpenTelemetry instrumentation that feeds into Azure Application
Insights, plus an LLM-as-judge eval pipeline. These are not nice-to-haves. At production
scale, they are the only way to maintain a system you cannot directly observe.

---

## Learning Objectives

- Instrument an agent with OpenTelemetry spans — every LLM call and every tool call is a span
- Export traces to Azure Application Insights via the OTLP exporter
- Write Kusto queries for cost, latency, and error rate dashboards
- Build an eval pipeline using LLM-as-judge scoring over a test dataset
- Understand semantic conventions for LLM spans (OpenTelemetry GenAI spec)
- Set up alerts that fire on anomalous error rates

---

## Concepts

### 1. Why Observability Is Hard for Agents

Traditional observability assumes deterministic systems: given input X, you get output Y.
You can test with assertions. You can diff outputs.

Agents break this model:
- The same user message produces different tool call sequences depending on model sampling
- Quality is subjective — "good" is not a binary
- Failures are often subtle (wrong information stated confidently) not loud (exception raised)
- A single agent run involves dozens of API calls with nested dependencies

The mental model shift:

| Traditional software | AI agents |
|---|---|
| Unit tests with assertEqual | Eval pipelines with LLM-as-judge |
| Stack traces for debugging | Distributed traces with span attributes |
| Error rate = exception rate | Error rate = bad-output rate + exception rate |
| Performance = p99 latency | Performance = latency + quality + cost |

### 2. OpenTelemetry for Agents

OpenTelemetry (OTel) is the CNCF standard for distributed tracing. You already use it
(conceptually) when you look at Azure Application Map — this is the same system, applied
to AI workloads.

The mapping:

```
Agent run           → Root span (trace_id = run_id)
  LLM call          → Child span
    Tool call       → Child span of LLM call
    Tool call       → Child span of LLM call
  LLM call          → Child span
    Tool call       → Child span
```

Every span has attributes — key-value metadata attached at creation time. For LLM spans,
you record model name, token counts, latency, finish reason. This is what lets you write
`SELECT sum(input_tokens) GROUP BY day` in Kusto later.

### 3. Semantic Conventions for LLM Spans (OpenTelemetry GenAI Spec)

The OTel project has standardized attribute names for LLM spans. Using these names makes
your traces compatible with any OTel-aware tooling. Use them:

| Attribute | Type | Description |
|---|---|---|
| `gen_ai.system` | string | `"openai"`, `"azure_openai"`, `"anthropic"` |
| `gen_ai.request.model` | string | `"gpt-4o"`, `"gpt-4o-mini"` |
| `gen_ai.request.temperature` | float | Temperature used |
| `gen_ai.request.max_tokens` | int | Max tokens requested |
| `gen_ai.usage.input_tokens` | int | Tokens in prompt |
| `gen_ai.usage.output_tokens` | int | Tokens in completion |
| `gen_ai.response.finish_reason` | string | `"stop"`, `"tool_calls"`, `"length"` |
| `gen_ai.response.id` | string | Completion ID for deduplication |

For tool calls, add:

| Attribute | Type | Description |
|---|---|---|
| `tool.name` | string | Tool function name |
| `tool.call_id` | string | Tool call ID from the model |
| `tool.success` | bool | Whether the call succeeded |
| `tool.error` | string | Error message if failed |

For cost attribution, add to every span:

| Attribute | Type | Description |
|---|---|---|
| `agent.user_id` | string | Who triggered this run |
| `agent.session_id` | string | Conversation session |
| `agent.feature_name` | string | Which product feature |
| `agent.run_id` | string | Unique ID for this agent execution |

### 4. Azure Application Insights

Application Insights receives OTel traces via OTLP (OpenTelemetry Protocol). The
`azure-monitor-opentelemetry` package handles this — it configures the OTLP exporter
pointed at your App Insights resource.

Once traces are in App Insights, you query them with KQL (Kusto Query Language):

```kusto
// p95 latency of all LLM calls
dependencies
| where name == "llm_call"
| summarize percentile(duration, 95) by bin(timestamp, 1h)
| render timechart

// Total tokens per day
customMetrics
| where name == "gen_ai.usage.input_tokens" or name == "gen_ai.usage.output_tokens"
| summarize sum(value) by bin(timestamp, 1d), name
| render columnchart

// Tool call error rate
dependencies
| where name startswith "tool_"
| summarize
    total = count(),
    errors = countif(success == false)
  by bin(timestamp, 5m)
| extend error_rate = todouble(errors) / todouble(total)
| render timechart
```

KQL is SQL-like but optimized for time-series. The key tables:
- `requests` — incoming requests to your function/service
- `dependencies` — outgoing calls (your LLM calls, tool calls)
- `traces` — log messages (your agent reasoning, structured logs)
- `exceptions` — exceptions thrown
- `customMetrics` — numeric metrics you explicitly emit

### 5. Eval Pipelines: LLM-as-Judge

An eval pipeline is your test suite for non-deterministic outputs. The components:

1. **Test dataset**: curated question/answer pairs (golden set). Start with 20, grow to
   hundreds over time. This is your most valuable asset.

2. **Judge LLM**: a separate LLM that scores your agent's output. It doesn't need to
   be the same model as your agent. Use GPT-4o for judging — its job is narrow and its
   output is structured.

3. **Scoring criteria**: be explicit. "Helpfulness" is vague. Instead: "Does the answer
   directly address the user's question without requiring follow-up? Score 1-5 where
   5=perfect, 1=irrelevant."

4. **Aggregation**: average scores across the dataset. Track trend over time. Regressions
   in eval score are your signal that a model update or prompt change degraded quality.

Judge prompt structure:
```
You are evaluating the quality of an AI assistant's response.

Question: {question}
Reference answer: {reference}
Actual answer: {actual}

Score the actual answer on the following criteria (1-5 scale):
- Accuracy: Does it match the reference answer on factual points?
- Completeness: Does it cover all key points from the reference?
- Conciseness: Is it appropriately brief without missing substance?

Respond with JSON: {"accuracy": N, "completeness": N, "conciseness": N, "reasoning": "..."}
```

**RAGAS** is a specialized eval library for RAG pipelines. It computes:
- Faithfulness: does the answer only use facts from the retrieved context?
- Answer relevancy: is the answer on-topic?
- Context precision: did retrieval surface the right documents?

For non-RAG agents, build custom eval criteria specific to your task.

### 6. Cost Attribution

Every LLM call produces a token usage object:
```json
{"prompt_tokens": 450, "completion_tokens": 120, "total_tokens": 570}
```

Current Azure OpenAI pricing (approximate, check current rates):
- GPT-4o: $2.50/1M input tokens, $10/1M output tokens
- GPT-4o-mini: $0.15/1M input tokens, $0.60/1M output tokens

Cost per call:
```python
def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = {
        "gpt-4o": (0.0000025, 0.00001),
        "gpt-4o-mini": (0.00000015, 0.0000006),
    }
    input_price, output_price = prices.get(model, (0, 0))
    return input_tokens * input_price + output_tokens * output_price
```

Tag every span with `agent.feature_name` and `agent.user_id`. Then in Kusto:

```kusto
customMetrics
| where name == "agent.cost_usd"
| summarize sum(value) by tostring(customDimensions["agent.feature_name"])
```

This tells you which features are expensive and whether cost scales with usage (good)
or with complexity (investigate).

---

## Terraform Setup

Infrastructure: Azure Log Analytics Workspace + Application Insights.

```
modules/module-21-observability/terraform/
├── main.tf
├── variables.tf
├── outputs.tf
└── terraform.tfvars.example
```

Deploy:
```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars with your values
terraform init
terraform apply
```

Copy the `connection_string` output into your `.env` file as
`APPLICATIONINSIGHTS_CONNECTION_STRING`.

---

## Lab

### Setup

```bash
cd lab
cp .env.example .env
# fill in your values
uv sync
```

### Task 1: Instrument the Agent with OTel Spans

Add OpenTelemetry instrumentation to a ReAct-style agent (similar to module-03).
Every LLM call becomes a span with token usage attributes. Every tool call becomes
a child span.

Open `lab/src/task1_instrumented_agent.py`.

Requirements:
- Root span per agent run named `"agent_run"`, with `agent.run_id` attribute
- Child span per LLM call named `"llm_call"`, with all GenAI semantic convention attributes
- Child span per tool call named `"tool_{name}"`, with `tool.name`, `tool.call_id`, `tool.success`
- Use context propagation so tool spans are children of the LLM span that requested them

Verify locally with the console exporter before pointing at App Insights.

### Task 2: Export to Application Insights

Configure the OTLP exporter to send traces to your App Insights resource.

Open `lab/src/task2_appinsights_export.py`.

Requirements:
- Use `azure-monitor-opentelemetry` to configure the exporter with your connection string
- Run 10 agent calls against a test question set
- Verify traces appear in Azure Portal under Application Insights > Transaction Search
- Check that span attributes (token counts, model name) are visible in the trace detail view

Expected: within 2-3 minutes of running, you should see traces in the portal.

### Task 3: Kusto Queries

Write and test three KQL queries in App Insights > Logs.

Open `lab/src/task3_kusto_queries.kql` (also documented in the starter file).

Queries to write:
1. **p95 latency by operation**: group by span name, compute p95 duration over last 24h
2. **Total tokens per day**: sum input and output tokens across all agent runs, grouped by day
3. **Tool call error rate**: compute `errors / total` per tool name, per 5-minute window

Hint: App Insights stores OTel spans in the `dependencies` table. Span attributes become
`customDimensions` columns.

### Task 4: Eval Pipeline

Build an LLM-as-judge eval pipeline over 20 test cases.

Open `lab/src/task4_eval_pipeline.py`.

The test dataset is in `lab/src/eval_dataset.json` — 20 question/expected-answer pairs
covering general knowledge and reasoning.

Requirements:
- Run each question through the instrumented agent
- For each response, call the judge LLM with a structured scoring prompt
- Parse the JSON score response (accuracy 1-5, helpfulness 1-5)
- Print a summary table: per-question scores + aggregate averages
- Save results to `eval_results.json` for trend tracking

The judge prompt and scoring rubric are in the starter file. Do not change the rubric
between runs — consistency is what makes the trend meaningful.

### Task 5: Alerting

Set up an Application Insights alert that fires when tool call error rate exceeds 5%
in a 5-minute window.

Open `lab/src/task5_alert_setup.py` — this uses the Azure SDK to create the alert rule
programmatically (so it's reproducible, not a portal click).

Requirements:
- Create a metric alert on the App Insights resource
- Query: tool call error rate > 0.05 in 5-minute evaluation window
- Action: log the alert to stdout (no need for real email/webhook in lab)
- Test by injecting deliberate tool failures and confirming the alert would trigger

---

## New Environment Variables

```
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...
```

Get this from: `terraform output -raw connection_string` after applying the Terraform.

---

## Dependencies

```
opentelemetry-api>=1.24
opentelemetry-sdk>=1.24
opentelemetry-exporter-otlp-proto-grpc>=1.24
azure-monitor-opentelemetry>=1.4
httpx>=0.27
python-dotenv>=1.0
rich>=13.0
```

---

## Checklist

- [ ] OTel spans appear in console output with correct parent-child hierarchy
- [ ] Traces visible in App Insights Transaction Search within 5 minutes
- [ ] Token usage attributes visible in span detail (gen_ai.usage.input_tokens, etc.)
- [ ] All three Kusto queries return results without error
- [ ] Eval pipeline runs all 20 cases and prints a score table
- [ ] Can explain the difference between a trace and an eval
- [ ] Can explain why LLM-as-judge scales better than human annotation
- [ ] Can draw the span hierarchy for a single agent run on a whiteboard

---

## Key Insight

Observability for agents is not optional infrastructure you add later. It is the mechanism
by which you prove the system is working. Without eval scores, you don't know if a model
upgrade helped or hurt. Without traces, you can't explain why a specific run failed.

Ship the observability before you ship the feature.
