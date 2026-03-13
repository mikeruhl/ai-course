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

**Goal:** Add OpenTelemetry tracing to a ReAct-style agent so every LLM call and tool call is captured as a span with structured attributes.

**What to do:**
1. Open `lab/src/task1_instrumented_agent.py` and examine the agent structure:
   - Lines 58-87: `call_llm_with_span()` function makes Azure OpenAI calls via httpx
   - Lines 90-105: `call_tool_with_span()` function executes tool calls
   - Lines 156-209: `run_agent()` orchestrates the agent loop
2. Complete the four TODO sections:
   - **Line 36-44**: Create a `TracerProvider`, add a `BatchSpanProcessor(ConsoleSpanExporter())`, call `trace.set_tracer_provider()`, then get a tracer with `trace.get_tracer("module-21-agent")`
   - **Line 58-87**: In `call_llm_with_span()`, wrap the httpx.post call in a span using `tracer.start_as_current_span("llm_call")`. After getting the response, set attributes: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reason`, `gen_ai.response.id`
   - **Line 90-105**: In `call_tool_with_span()`, create a child span named `f"tool_{tool_name}"` using `trace.use_span(parent_span)` context. Set attributes: `tool.name`, `tool.call_id`, `tool.success` (True/False after execution)
   - **Line 178**: In `run_agent()`, wrap the entire agent loop (lines 180-209) in a root span named `"agent_run"` with attributes `agent.run_id` and `agent.user_input`
3. Run: `uv run python src/task1_instrumented_agent.py`

**Expected result:**
- Three questions execute successfully:
  - "What's the weather in Seattle and Tokyo? Which one is warmer?"
  - "What is 2 to the power of 32?"
  - "What is the weather in Paris? Convert the temperature to Fahrenheit."
- Console output shows agent responses followed by JSON span data:
  ```
  Agent run a1b2c3d4
  What's the weather in Seattle and Tokyo? Which one is warmer?
    Tool: get_weather({'city': 'Seattle'})
    Tool: get_weather({'city': 'Tokyo'})
  Answer: Both cities are at 18°C...

  {"name": "tool_get_weather", "context": {"trace_id": "0x...", "span_id": "0x..."},
   "parent_id": "0x...", "attributes": {"tool.name": "get_weather", "tool.call_id": "call_xyz",
   "tool.success": true}}
  {"name": "llm_call", "attributes": {"gen_ai.system": "azure_openai",
   "gen_ai.usage.input_tokens": 185, "gen_ai.usage.output_tokens": 42, ...}}
  {"name": "agent_run", "attributes": {"agent.run_id": "a1b2c3d4-...", ...}}
  ```
- Verify parent-child hierarchy: each `tool_*` span's `parent_id` matches the `span_id` of the corresponding `llm_call` span, which itself has the `agent_run` span as parent

**Why this matters:**
Without structured spans, debugging a failed agent run means reading logs line by line and reconstructing the execution flow manually. With OTel spans, you get a queryable trace tree where every LLM call is tagged with token counts, latency, and model parameters, and every tool call is tagged with success/failure status. This structured telemetry is the foundation for the cost analysis, latency dashboards, and error rate alerts you'll build in Tasks 2-5. In production, trace IDs let you reconstruct exactly what happened in any user session, even across distributed systems.

### Task 2: Export to Application Insights

**Goal:** Replace the console exporter with the Azure Monitor exporter so traces flow into Application Insights for persistent storage, querying, and dashboarding.

**What to do:**
1. Open `lab/src/task2_appinsights_export.py` and review the structure:
   - Lines 54-65: `TEST_QUESTIONS` contains 10 test prompts for batch execution
   - Lines 68-103: `run_batch_with_tracking()` orchestrates the batch run and collects timing data
   - Lines 106-123: `print_results_table()` renders results in a Rich table
2. Complete the three TODO sections:
   - **Line 43**: Add the import and call to configure Azure Monitor:
     ```python
     from azure.monitor.opentelemetry import configure_azure_monitor
     configure_azure_monitor(
         connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
     )
     ```
   - **Line 51**: Uncomment the import: `from task1_instrumented_agent import run_agent`
   - **Line 86**: Replace the placeholder string with an actual call: `answer = run_agent(question)`
3. Ensure your `.env` file contains `APPLICATIONINSIGHTS_CONNECTION_STRING` (from Terraform output)
4. Run: `uv run python src/task2_appinsights_export.py`

**Expected result:**
- Script executes all 10 test questions sequentially
- Rich table displays results:
  ```
  Batch Run Results
  ┌───┬──────────────────────────────┬──────────────────────────────┬──────────┬────┐
  │ # │ Question                     │ Answer                       │ Duration │ OK │
  ├───┼──────────────────────────────┼──────────────────────────────┼──────────┼────┤
  │ 1 │ What's the weather in London?│ The weather in London is 18°C│   1842ms │ Y  │
  │ 2 │ What is 42 * 17?             │ 42 * 17 = 714               │    923ms │ Y  │
  │ 3 │ What's the weather in New...?│ The weather in New York is...│   1654ms │ Y  │
  │...│ ...                          │ ...                          │      ... │ ...│
  └───┴──────────────────────────────┴──────────────────────────────┴──────────┴────┘
  Success rate: 10/10
  Avg duration: 1450ms
  ```
- Script sleeps 5 seconds at the end to allow batch flush
- After 2-3 minutes, navigate to Azure Portal > Application Insights > Transaction Search
- Filter by "Operation Name" = `agent_run` to see all 10 traces
- Click any trace to view the full span hierarchy with attributes

**Why this matters:**
Console output is ephemeral and useless in production — it disappears when the process restarts and cannot be queried retroactively. Exporting to Application Insights gives you persistent, indexed telemetry with built-in retention policies. The `configure_azure_monitor()` one-liner is the standard pattern for any Python workload on Azure — it automatically sets up the TracerProvider, MeterProvider, and LoggingHandler with proper batching and export intervals. This same configuration works for Azure Functions, App Service, Container Apps, and AKS.

### Task 3: Kusto Queries

**Goal:** Write three KQL queries that turn raw OTel span data into operational dashboards for latency, token usage, and error rates.

**What to do:**
1. Open `lab/src/task3_kusto_queries.kql` in your editor
2. Review the query structure and comments:
   - Lines 11-29: Query 1 skeleton for p95 latency analysis
   - Lines 33-55: Query 2 skeleton for token usage over time
   - Lines 59-80: Query 3 skeleton for tool error rate tracking
   - Lines 84-105: Bonus query for cost attribution by feature (fully implemented as reference)
3. Complete the three TODO sections:
   - **Query 1 (lines 22-29)**: Add `summarize` clause to compute `p50 = percentile(duration, 50)`, `p95 = percentile(duration, 95)`, `calls = count()`, `avg_ms = avg(duration)` grouped by `name`. Add `order by p95 desc`
   - **Query 2 (lines 46-55)**: Add `extend` to extract `input_tokens = toint(customDimensions["gen_ai.usage.input_tokens"])` and `output_tokens = toint(customDimensions["gen_ai.usage.output_tokens"])`. Add `summarize total_input = sum(input_tokens), total_output = sum(output_tokens)` by `bin(timestamp, 1d)`. Add `extend total_tokens = total_input + total_output`. Add `render columnchart`
   - **Query 3 (lines 71-80)**: Add `extend` to extract `tool_name = tostring(customDimensions["tool.name"])` and `tool_success = tobool(customDimensions["tool.success"])`. Add `summarize total = count(), errors = countif(tool_success == false)` by `bin(timestamp, 5m), tool_name`. Add `extend error_rate = todouble(errors) / todouble(total)`. Add `render timechart`
4. Navigate to Azure Portal > Application Insights > Logs
5. Paste and run each completed query

**Expected result:**
- Query 1 returns a table sorted by p95 latency:
  ```
  name             | p50    | p95     | calls | avg_ms
  ──────────────────────────────────────────────────────
  agent_run        | 3200   | 5800    | 10    | 3450
  llm_call         | 1100   | 2200    | 24    | 1280
  tool_calculate   | 3      | 7       | 6     | 4
  tool_get_weather | 2      | 5       | 18    | 3
  ```
  This shows agent runs averaging 3.4s with p95 at 5.8s, while tool calls complete in milliseconds
- Query 2 renders a stacked column chart with two series (input tokens, output tokens) per day. For the 10-run batch, you'll see a single day's bar showing ~4,500 input tokens and ~1,200 output tokens
- Query 3 renders a time chart with one line per tool. With no deliberate failures injected, error rates should be 0% across all 5-minute windows

**Why this matters:**
KQL queries are how you detect production issues before users report them. A sudden spike in `gen_ai.usage.output_tokens` might indicate a prompt regression causing the model to generate verbose responses, doubling your costs overnight. A rising tool error rate signals an upstream dependency (database, external API) starting to degrade — you can page the on-call engineer before the circuit breaker trips. A p95 latency increase from 2s to 8s means users are waiting, even if p50 looks normal. These three queries form the foundation of your agent health dashboard; pin them to an Azure Dashboard for continuous monitoring.

### Task 4: Eval Pipeline

**Goal:** Build an LLM-as-judge evaluation pipeline that scores agent outputs against a golden dataset, producing a repeatable quality metric for detecting regressions.

**What to do:**
1. Create `lab/src/eval_dataset.json` with 20 test cases in this format:
   ```json
   [
     {"question": "What is 2^32?", "expected": "4294967296"},
     {"question": "What's the weather in Paris in Fahrenheit?", "expected": "64.4°F (partly cloudy)"},
     ...
   ]
   ```
2. Create `lab/src/task4_eval_pipeline.py` with the following components:
   - Load test cases from `eval_dataset.json`
   - For each case: call `run_agent(question)` to get the actual output
   - Send (question, expected, actual) to a judge LLM with this prompt structure:
     ```
     You are evaluating an AI assistant's response.
     Question: {question}
     Expected: {expected}
     Actual: {actual}

     Score on a 1-5 scale:
     - accuracy: factual correctness
     - helpfulness: directly answers the question
     Respond with JSON: {"accuracy": N, "helpfulness": N, "reasoning": "..."}
     ```
   - Parse the judge's JSON response, handle validation errors
   - Compute average scores across all cases
   - Save detailed results to `eval_results.json` with timestamp
3. Run: `uv run python src/task4_eval_pipeline.py`

**Expected result:**
- Progress output showing each eval case:
  ```
  Evaluating 1/20: What is 2^32?
    Actual: The result is 4294967296
    Judge: accuracy=5, helpfulness=4
  Evaluating 2/20: What's the weather in Paris in Fahrenheit?
    Actual: The weather in Paris is 18°C, which is 64.4°F
    Judge: accuracy=5, helpfulness=5
  ...
  ```
- Final summary table:
  ```
  Eval Results (20 cases)
  ┌────┬────────────────────────────────────┬──────────┬─────────────┐
  │ #  │ Question                           │ Accuracy │ Helpfulness │
  ├────┼────────────────────────────────────┼──────────┼─────────────┤
  │ 1  │ What is 2^32?                      │ 5        │ 4           │
  │ 2  │ Weather in Paris in Fahrenheit?    │ 5        │ 5           │
  │ 3  │ What is 15% of 847?                │ 5        │ 5           │
  │...│ ...                                 │ ...      │ ...         │
  ├────┼────────────────────────────────────┼──────────┼─────────────┤
  │    │ AVERAGE                            │ 4.6      │ 4.5         │
  └────┴────────────────────────────────────┴──────────┴─────────────┘
  ```
- JSON file saved at `lab/src/eval_results.json` with full details for tracking trends over time

**Why this matters:**
You cannot unit-test non-deterministic outputs with `assertEqual()`. An eval pipeline with a fixed rubric and golden dataset is the only way to detect quality regressions when you change system prompts, swap models (e.g., GPT-4o to GPT-4o-mini), or update tool implementations. The key discipline: never change the rubric or dataset between runs — consistency is what makes the trend meaningful. If average accuracy drops from 4.6 to 3.8 after a prompt change, you have evidence of a regression. Run this pipeline in CI/CD before deploying agent updates to production.

### Task 5: Alerting

**Goal:** Programmatically create an Application Insights alert rule that fires when tool call error rate exceeds 5% in a 5-minute window, enabling proactive incident response.

**What to do:**
1. Create `lab/src/task5_alert_setup.py` with these components:
   - Import `azure-mgmt-monitor` SDK: `from azure.mgmt.monitor import MonitorManagementClient`
   - Authenticate using `DefaultAzureCredential` (requires `az login`)
   - Create a scheduled query alert rule targeting your App Insights resource
   - Set the KQL condition based on Query 3 from Task 3:
     ```kusto
     dependencies
     | where name startswith "tool_"
     | extend tool_success = tobool(customDimensions["tool.success"])
     | summarize error_rate = todouble(countif(tool_success == false)) / todouble(count())
     | where error_rate > 0.05
     ```
   - Configure evaluation frequency: 5 minutes, window size: 5 minutes
   - Set severity: 2 (Warning)
   - For the lab, use a console log action (no email/webhook)
2. Add a test mode that injects failures:
   - Modify `task1_instrumented_agent.py` temporarily: in `_execute_tool()` at line 108, add `if random.random() < 0.15: raise ConnectionError("Simulated failure")` to cause ~15% failure rate
   - Re-run Task 2 batch to generate failure traces
3. Run: `uv run python src/task5_alert_setup.py`

**Expected result:**
- Script authenticates and creates the alert rule:
  ```
  Creating alert rule: tool-error-rate-alert
  Target resource: /subscriptions/abc123.../providers/microsoft.insights/components/app-insights-module21
  Condition: KQL query returns error_rate > 0.05
  Evaluation: every 5 minutes, window 5 minutes
  Severity: Warning (2)

  Alert rule created successfully!
  Resource ID: /subscriptions/.../microsoft.insights/scheduledQueryRules/tool-error-rate-alert
  ```
- After injecting failures and running Task 2 again, navigate to Azure Portal > Application Insights > Alerts
- Within 5-10 minutes, the alert fires and appears in the Alerts list with state "Fired"
- Click the alert to see the triggering KQL query result showing error_rate = 0.15 (15%)

**Why this matters:**
Dashboards require someone to actively monitor them — they are reactive tools. Alerts are proactive: they push problems to you the moment thresholds are breached. In production, an agent whose tools silently fail (e.g., database timeout, external API 500) will continue running and generating plausible-sounding but factually wrong answers. Users may not notice immediately, but your reputation degrades with every incorrect response. A 5% error rate threshold gives you a 5-10 minute warning before the problem becomes user-visible, allowing you to investigate, roll back, or fail over. Creating alerts as code (not via portal clicks) makes them reproducible, version-controlled, and deployable via CI/CD alongside your agent.

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
