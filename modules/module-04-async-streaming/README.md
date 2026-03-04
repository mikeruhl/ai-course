# Module 4: Async Agent Loops + Streaming

**Week 2 · Phase 1 — Foundations**

---

## Learning Objectives

By the end of this module you will:

- Convert a synchronous agent loop to fully async using `asyncio` + `httpx.AsyncClient`
- Process parallel tool calls concurrently with `asyncio.gather` and measure the throughput gain
- Implement streaming (SSE) responses so tokens appear in real time
- Handle streaming tool calls — accumulate argument deltas before executing
- Know when to stream (UX responsiveness) vs. when to batch (throughput pipelines)

---

## Prerequisites

- [Module 3](../module-03-tool-use/README.md) complete — you need the working agent loop
- Azure OpenAI resources from Module 1 still running

---

## Concepts

### 1. Why Async Matters for Agents

The dominant bottleneck in an agent loop is not CPU — it is I/O:

```
LLM call:   ~1–5 seconds
Tool call:  ~50ms–2s depending on the tool
```

A synchronous agent handling 10 parallel user sessions or executing 5 tool
calls sequentially wastes almost all of its time waiting on the network.

Async changes the execution model. Instead of:

```
[task 1 LLM call: 2s] → [task 2 LLM call: 2s] → [task 3 LLM call: 2s]
Total: 6s
```

You get:

```
[task 1 LLM call: 2s]
[task 2 LLM call: 2s]  (concurrent)
[task 3 LLM call: 2s]  (concurrent)
Total: ~2s
```

**This is not just a performance optimisation. It is a scaling requirement.**
A production agent serving many users must be async or it will not scale.

### 2. httpx.AsyncClient

`httpx` provides a drop-in async HTTP client. The API is nearly identical
to the sync version — just add `async def`, `await`, and use `AsyncClient`:

**Sync:**
```python
import httpx

with httpx.Client() as client:
    response = client.post(url, headers=headers, json=payload)
    data = response.json()
```

**Async:**
```python
import httpx
import asyncio

async def call_api():
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        data = response.json()
```

The key difference: `await` yields control back to the event loop while
waiting for the network response. Other coroutines can run during that wait.

**Sharing a client:** For an agent that makes many calls, create one
`AsyncClient` instance and reuse it. Creating a new client per call
re-establishes the TCP connection each time.

```python
class AsyncAgent:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        await self._client.aclose()
```

Or use it as an async context manager on the outer scope:

```python
async with httpx.AsyncClient() as client:
    results = await asyncio.gather(
        run_agent("task 1", client),
        run_agent("task 2", client),
        run_agent("task 3", client),
    )
```

### 3. asyncio.gather for Parallel Tool Execution

When the model returns multiple tool calls in one response, you can execute
them concurrently with `asyncio.gather`:

```python
async def execute_all_tools(tool_calls: list[dict]) -> list[dict]:
    """Execute all tool calls concurrently. Return list of tool result messages."""

    async def execute_one(tc: dict) -> dict:
        name = tc["function"]["name"]
        args = json.loads(tc["function"]["arguments"])
        try:
            result = await call_tool_async(name, args)
        except Exception as e:
            result = f"Error: {e}"
        return {
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": result,
        }

    return list(await asyncio.gather(*[execute_one(tc) for tc in tool_calls]))
```

`asyncio.gather` schedules all coroutines concurrently and waits until
all complete. If any coroutine raises an exception, gather re-raises it
(unless you use `return_exceptions=True`).

**When does concurrency actually help here?**
Only when tools do I/O (HTTP requests, database queries, filesystem reads
on network drives). Pure CPU tools like string parsing gain nothing from
asyncio — they need multiprocessing for true parallelism.

### 4. The Azure OpenAI Streaming Protocol

Azure OpenAI supports Server-Sent Events (SSE) streaming. Add `"stream": true`
to your request body.

**What comes back:**

The response body is a stream of newline-delimited lines. Each event is:

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{...},"finish_reason":null}]}\n\n
```

The final event is always:

```
data: [DONE]\n\n
```

**The structure of each chunk:**

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion.chunk",
  "choices": [{
    "index": 0,
    "delta": {
      "role": "assistant",       // only in first chunk
      "content": "Hello"         // token text, or null if tool call
    },
    "finish_reason": null        // "stop" or "tool_calls" on final chunk
  }]
}
```

**The delta accumulation pattern:**

Tokens arrive one at a time. You accumulate them:

```python
collected_content = []

async for line in response.aiter_lines():
    if not line.startswith("data: "):
        continue
    payload = line[6:]  # strip "data: " prefix
    if payload == "[DONE]":
        break
    chunk = json.loads(payload)
    delta = chunk["choices"][0]["delta"]
    if delta.get("content"):
        collected_content.append(delta["content"])
        print(delta["content"], end="", flush=True)  # live output

full_response = "".join(collected_content)
```

### 5. Streaming Tool Calls

When the model wants to call a tool while streaming, the tool call arguments
arrive as deltas too. This is more complex:

```json
// First chunk with tool call start
{"delta": {"tool_calls": [{"index": 0, "id": "call_abc", "type": "function", "function": {"name": "get_weather", "arguments": ""}}]}}

// Subsequent chunks build up the arguments
{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"loc"}}]}}
{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "ation\":"}}]}}
{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": " \"Seattle\"}"}}]}}

// Final chunk
{"delta": {}, "finish_reason": "tool_calls"}
```

You must accumulate the full tool call before executing it:

```python
# Accumulator structure keyed by tool call index
tool_calls_acc: dict[int, dict] = {}

for chunk in stream:
    delta = chunk["choices"][0]["delta"]
    for tc_delta in delta.get("tool_calls", []):
        idx = tc_delta["index"]
        if idx not in tool_calls_acc:
            tool_calls_acc[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
        if tc_delta.get("id"):
            tool_calls_acc[idx]["id"] = tc_delta["id"]
        fn = tc_delta.get("function", {})
        if fn.get("name"):
            tool_calls_acc[idx]["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            tool_calls_acc[idx]["function"]["arguments"] += fn["arguments"]

# After stream ends, tool_calls_acc has the complete tool calls
tool_calls = list(tool_calls_acc.values())
```

### 6. When to Stream vs. When to Batch

| Scenario | Recommendation | Why |
|---|---|---|
| User-facing chat interface | Stream | User sees output immediately; perceived latency drops dramatically |
| Background pipeline processing | Do not stream | Overhead of SSE parsing with no UX benefit; batch is simpler |
| Agent producing a long report | Stream | User knows it is working; can cancel early |
| Parallel agent tasks (benchmark) | Do not stream | Streaming adds connection overhead; you want raw throughput |
| Tool call heavy agent | Either | Tool execution dominates — streaming text between tool calls is low value |

**Streaming does not make the model go faster.** Total time to complete is
the same. Streaming makes it *feel* faster because first-token latency is
much lower than waiting for the full response.

### 7. Throughput Benchmarking

To measure the actual benefit of async concurrency:

```python
import asyncio
import time

async def benchmark():
    tasks = ["Summarize the theory of relativity in one sentence."] * 5

    # Sequential
    start = time.perf_counter()
    for task in tasks:
        await run_agent_async(task)
    sequential_time = time.perf_counter() - start

    # Concurrent
    start = time.perf_counter()
    await asyncio.gather(*[run_agent_async(task) for task in tasks])
    concurrent_time = time.perf_counter() - start

    speedup = sequential_time / concurrent_time
    print(f"Sequential: {sequential_time:.1f}s")
    print(f"Concurrent: {concurrent_time:.1f}s")
    print(f"Speedup:    {speedup:.1f}x")
```

Expected result on typical Azure OpenAI: 3–4x speedup on 5 tasks,
diminishing returns after ~10 (rate limits, connection pooling).

---

## Azure Setup

No new Terraform needed. Uses the same Azure OpenAI resources from Module 1.

---

## Lab Setup

```bash
cd modules/module-04-async-streaming/lab
cp .env.example .env
# edit .env with your values
uv sync
```

---

## Lab Tasks

### Task 1: Convert the Sync Loop to Async

In `src/async_agent.py`, implement `AsyncAgent.run()`.

The scaffold has the class structure. Your job:

1. Replace the `NotImplementedError` in `run()` with a working async loop
2. Use `httpx.AsyncClient` — the client is already set up in `__init__`
3. Handle `finish_reason == "stop"` and `finish_reason == "tool_calls"` the
   same as Module 3, but with `await` on the HTTP call
4. Use `asyncio.gather` to execute multiple tool calls concurrently

Verify it works:

```bash
uv run python src/async_agent.py --task "What files are in the current directory?"
```

### Task 2: Implement Basic Streaming (Text Only)

Implement `AsyncAgent.stream()` — a streaming variant that:

1. Sends the request with `"stream": true`
2. Uses `response.aiter_lines()` to read the SSE stream
3. Parses each `data:` line as JSON
4. Prints each content delta to stdout as it arrives
5. Accumulates and returns the full response when `[DONE]` is received

You should see tokens printing live, not all at once at the end.

**Test prompt:** *"Explain event loops in Python in 3 paragraphs."*

Observe: does the first token appear faster with streaming than the full
response appears with the non-streaming version?

### Task 3: Streaming with Tool Call Accumulation

Extend the `stream()` implementation to handle tool calls in the stream.

The scaffold has the `tool_calls_acc` dict pattern shown in the concepts section.
Your implementation must:

1. Detect `"tool_calls"` deltas and accumulate them correctly
2. After the stream ends with `finish_reason == "tool_calls"`:
   - Execute the accumulated tool calls (using `asyncio.gather`)
   - Append results to the message history
   - Make another streaming call to the model
   - Continue until `finish_reason == "stop"`
3. Print something to indicate tool execution (e.g., `[TOOL] calling get_weather`)

**Test prompt:** *"What Python files exist in the current directory? List them with their sizes."*

This should trigger `list_directory` and possibly `read_file` tool calls.

### Task 4: Sequential vs. Concurrent Benchmark

Implement the `benchmark()` function in `src/async_agent.py`.

It should:

1. Create a list of 5 identical simple tasks (short prompt, no tools needed)
2. Run them sequentially using a `for` loop with `await`
3. Run them concurrently using `asyncio.gather`
4. Print a formatted table showing wall-clock time for each approach and the speedup

```
Sequential:  12.4s
Concurrent:   3.8s
Speedup:      3.3x
```

Run it:

```bash
uv run python src/async_agent.py --benchmark
```

**Record your actual speedup number** — it will vary based on Azure region,
model, and rate limits. Anything above 2x on 5 tasks confirms the benefit.

### Task 5: Progress Display

Build a simple progress display using streaming. When the agent is processing
a long task, the user should see:

1. A spinner or indicator showing the agent is thinking
2. Each token printed as it arrives (not buffered)
3. Tool call notifications: `[calling list_directory with path="."]`
4. The final answer clearly demarcated

Use `rich.live` or `rich.console` to format the output. The scaffold has
a `stream_with_progress()` function stub to implement.

**Test prompt:** *"Read all the README files in the modules directory and give
me a one-sentence summary of each module."*

This is a multi-step task that will use several tool calls — a good stress
test for the progress display.

---

## Conceptual Checkpoints

1. Why does `asyncio.gather` only help when tools do I/O? What would you use
   instead if a tool was CPU-bound (e.g., running a local model inference)?

2. Streaming does not make the total response faster — so what is the actual
   UX benefit? Can you construct a case where streaming makes UX *worse*?

3. Why must you accumulate tool call argument deltas as strings and only call
   `json.loads()` after the stream ends? What would happen if you tried to
   parse each delta chunk as JSON immediately?

4. In the benchmark, why might you see less than linear speedup as you add
   more concurrent tasks? Name at least two limiting factors specific to
   the Azure OpenAI service.

5. If your streaming agent crashes halfway through a multi-turn tool-calling
   conversation, how would you resume it? What state would you need to have
   persisted?

---

## Resources

- [Azure OpenAI streaming guide](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/streaming)
- [httpx async client docs](https://www.python-httpx.org/async/)
- [asyncio.gather docs](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather)
- [Server-Sent Events spec](https://html.spec.whatwg.org/multipage/server-sent-events.html)

---

**Next:** [Module 5 — Structured Outputs at Depth](../module-05-structured-outputs/README.md)
