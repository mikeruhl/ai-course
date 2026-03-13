# Module 4: Async Agent Loops + Streaming

**Chapter 1 — Foundations**

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

**Goal:** Convert a synchronous agent loop to fully async, proving that `await` and `asyncio.gather` enable concurrent I/O without changing the logic structure.

**What to do:**

1. Open `lab/src/async_agent.py` and locate the `execute_tool_calls()` function (line 239) and the `AsyncAgent.run()` method (line 282)
2. In `execute_tool_calls()` (line 239): define an inner `async def execute_one(tc)` that extracts `name` and `arguments` from the tool call, parses `arguments` with `json.loads()`, calls `await call_tool_async(name, args)` wrapped in try/except, logs the call with `console.print()`, and returns a dict with `{"role": "tool", "tool_call_id": tc["id"], "content": result}`. Then use `asyncio.gather(*[execute_one(tc) for tc in tool_calls])` to run all tool calls concurrently and return the list of results.
3. In `AsyncAgent.run()` (line 282): replace the `NotImplementedError` at line 303 with a complete loop body. Build the payload dict with `messages`, `tools`, and `tool_choice`. Call `await self._client.post(BASE_URL, headers=HEADERS, json=payload)` and extract the JSON response. Get `message` from `response_data["choices"][0]["message"]` and `finish_reason` from `response_data["choices"][0]["finish_reason"]`. Append the assistant message to `messages`. If `finish_reason == "stop"`, return `message["content"]`. If `finish_reason == "tool_calls"`, await `execute_tool_calls(message["tool_calls"])` and extend `messages` with the results, then continue the loop.
4. Run the command:
   ```bash
   uv run python src/async_agent.py --task "What files are in the current directory?"
   ```

**Expected result:**
- Output similar to:
  ```
  --- Iteration 1 ---
  [TOOL] list_directory({"path": "."})
  --- Iteration 2 ---
  Final Answer:
  The current directory contains the following files and directories:
    dir  src
    file pyproject.toml
    file .env.example
    file .env
  ```
- The agent completes in 2 iterations: one to call the tool, one to formulate the answer.

**Why this matters:**
The `await` keyword yields control during network waits, enabling one Python process to serve many concurrent agent sessions. Without async, each session blocks the entire process during every LLM and tool call, making it impossible to scale beyond a handful of users.

---

### Task 2: Implement Basic Streaming (Text Only)

**Goal:** Implement SSE streaming so tokens print to the terminal as they are generated, reducing perceived latency to first-token time instead of full-response time.

**What to do:**

1. Open `lab/src/async_agent.py` and locate the `AsyncAgent.stream()` method (line 325)
2. At line 353, replace the `NotImplementedError` with streaming logic. Build a payload dict identical to Task 1 but add `"stream": true`. Use `async with self._client.stream("POST", BASE_URL, headers=HEADERS, json=payload) as resp:` to get a streaming response context manager.
3. Inside the context manager (starting around line 350), add an `async for line in resp.aiter_lines():` loop. Skip lines that don't start with `"data: "` using `if not line.startswith("data: "): continue`. Strip the prefix with `payload = line[6:]`. If `payload == "[DONE]"`, break. Otherwise, parse with `chunk = json.loads(payload)`, extract `delta = chunk["choices"][0]["delta"]`, and if `delta.get("content")` exists, print it with `print(delta["content"], end="", flush=True)` and accumulate it in a `collected_content` list. After the loop, extract `finish_reason` from the final chunk and handle `"stop"` by returning the joined content.
4. Run the command:
   ```bash
   uv run python src/async_agent.py --stream "Explain event loops in Python in 3 paragraphs."
   ```

**Expected result:**
- Tokens appear one-by-one in the terminal with no buffering — text flows smoothly rather than appearing all at once
- First token appears within ~200–500ms; the full response takes 3–8 seconds
- Output ends with a `Final Answer` panel containing the complete accumulated text

**Why this matters:**
Streaming does not reduce total generation time — the model produces tokens at the same rate. The benefit is UX: users see progress immediately, which reduces perceived latency by 5–10x in chat interfaces. This is the standard approach for any user-facing LLM interaction.

---

### Task 3: Streaming with Tool Call Accumulation

**Goal:** Extend the streaming implementation to handle tool call deltas, which arrive as fragmented JSON argument strings that must be accumulated before execution.

**What to do:**

1. Open `lab/src/async_agent.py`, still in the `AsyncAgent.stream()` method (line 325). Extend your Task 2 implementation with tool call handling.
2. Before the streaming loop (around line 343), initialize `tool_calls_acc: dict[int, dict] = {}` to track tool call accumulation. Inside the `async for line in resp.aiter_lines():` loop, after extracting `delta`, check if `delta.get("tool_calls")` exists. For each `tc_delta` in `delta.get("tool_calls", [])`, get the index with `idx = tc_delta["index"]`. If `idx` not in `tool_calls_acc`, initialize it with `{"id": "", "function": {"name": "", "arguments": ""}}`. Then accumulate: if `tc_delta.get("id")`, set `tool_calls_acc[idx]["id"] = tc_delta["id"]`. If `tc_delta.get("function", {}).get("name")`, append to `tool_calls_acc[idx]["function"]["name"]`. If `tc_delta.get("function", {}).get("arguments")`, append to `tool_calls_acc[idx]["function"]["arguments"]`.
3. After the streaming loop ends, check `finish_reason`. If it's `"tool_calls"`, convert `tool_calls_acc` to a list with `tool_calls = list(tool_calls_acc.values())`. Construct the assistant message dict with `{"role": "assistant", "content": None, "tool_calls": tool_calls}` and append it to `messages`. Call `tool_results = await execute_tool_calls(tool_calls)` and extend `messages` with the results. Continue the outer for loop to make another streaming call.
4. Run the command:
   ```bash
   uv run python src/async_agent.py --stream "What Python files exist in the current directory? List them with their sizes."
   ```

**Expected result:**
- Output similar to:
  ```
  --- Iteration 1 (stream) ---
  [TOOL] list_directory({"path": "."})
  --- Iteration 2 (stream) ---
  [TOOL] read_file({"path": "src/async_agent.py"})
  --- Iteration 3 (stream) ---
  The Python files in the current directory are:
  - src/async_agent.py (15,234 bytes)
  ```
- Tool call arguments accumulate silently across multiple SSE chunks, then execute all at once after the stream completes

**Why this matters:**
In production streaming agents, tool call arguments arrive as partial JSON fragments (e.g., `{"loc` then `ation":` then `"Seattle"}`). Attempting to parse each fragment individually causes `json.JSONDecodeError`. The accumulator pattern is the only correct approach — and every production streaming agent must implement it.

---

### Task 4: Sequential vs. Concurrent Benchmark

**Goal:** Quantify the throughput gain from async concurrency by measuring wall-clock time for sequential vs. concurrent execution of identical LLM tasks.

**What to do:**

1. Open `lab/src/async_agent.py` and locate the `benchmark()` function (line 399)
2. At line 416, replace the `NotImplementedError` with the sequential benchmark. Record the start time with `start = time.perf_counter()`. Use a for loop: `for task in tasks:` and call `await agent.run(task)` inside. After the loop, calculate `sequential_time = time.perf_counter() - start`.
3. At line 422, implement the concurrent benchmark. Record the start time again. Call `await asyncio.gather(*[agent.run(task) for task in tasks])` to run all 5 tasks concurrently. Calculate `concurrent_time = time.perf_counter() - start`.
4. At line 429, build the results table. Create a `Table()` with title `"Sequential vs. Concurrent Benchmark"`. Add columns: `"Mode"`, `"Tasks"`, `"Total Time"`, `"Time per Task"`. Add two rows: one for sequential with values `"Sequential"`, `"5"`, `f"{sequential_time:.1f}s"`, `f"{sequential_time/5:.1f}s"`, and one for concurrent with `"Concurrent"`, `"5"`, `f"{concurrent_time:.1f}s"`, `f"{concurrent_time/5:.1f}s"`. Print the table with `console.print(table)`. Then calculate and print speedup: `console.print(f"\nSpeedup: {sequential_time / concurrent_time:.1f}x")`.
5. Run the command:
   ```bash
   uv run python src/async_agent.py --benchmark
   ```

**Expected result:**
- Output similar to:
  ```
  ┌────────────┬───────┬────────────┬───────────────┐
  │ Mode       │ Tasks │ Total Time │ Time per Task │
  ├────────────┼───────┼────────────┼───────────────┤
  │ Sequential │ 5     │ 12.4s      │ 2.5s          │
  │ Concurrent │ 5     │ 3.8s       │ 0.8s          │
  └────────────┴───────┴────────────┴───────────────┘
  Speedup: 3.3x
  ```
- Anything above 2x on 5 tasks confirms the benefit. Typical results: 3–4x speedup.

**Why this matters:**
This benchmark proves the async scaling claim with real numbers from your Azure deployment. The speedup is sub-linear (not 5x for 5 tasks) because of rate limiting, connection pool contention, and server-side queuing. Understanding these diminishing returns is critical for capacity planning — you cannot just throw more concurrency at the problem indefinitely.

---

### Task 5: Progress Display

**Goal:** Build a production-quality streaming progress display that shows thinking state, live tokens, tool call notifications, and a clearly demarcated final answer.

**What to do:**

1. Open `lab/src/async_agent.py` and locate the `stream_with_progress()` method (line 377)
2. At line 393, replace the `NotImplementedError` with rich-formatted streaming. Reuse your Task 3 streaming loop logic but add rich formatting. Before the first token arrives, print `console.print("[dim]Thinking...[/dim]")`. When tool calls are detected and executed (after `finish_reason == "tool_calls"`), the `execute_tool_calls()` function already logs them as `[dim][TOOL] name(args)[/dim]`. When streaming content tokens, use `console.print(delta["content"], end="")` instead of plain `print()` to maintain rich formatting.
3. After the streaming loop completes and you have the full response text, wrap it in a Panel. Use `Panel(final_answer, title="Final Answer", border_style="green")` and print it with `console.print()`. This creates a clearly demarcated final output.
4. Run the command:
   ```bash
   uv run python src/async_agent.py --progress "Read all the README files in the modules directory and give me a one-sentence summary of each module."
   ```

**Expected result:**
- Output similar to:
  ```
  Thinking...
  [TOOL] search_files({"directory": ".", "pattern": "README.md"})
  [TOOL] read_file({"path": "modules/module-01-.../README.md"})
  [TOOL] read_file({"path": "modules/module-02-.../README.md"})
  ...streaming tokens appear here as they generate...
  ╭─ Final Answer ──────────────────────────────────╮
  │ Module 1: Setting up Azure OpenAI and making... │
  │ Module 2: Prompt engineering techniques for...  │
  │ ...                                             │
  ╰─────────────────────────────────────────────────╯
  ```
- Multiple tool calls execute concurrently, and the user sees activity throughout the entire multi-step process

**Why this matters:**
Long-running agent tasks that involve multiple tool calls can take 30+ seconds. Without progress feedback, users assume the system is broken and retry or abandon. A live progress display turns a frustrating black-box wait into a transparent, trustworthy interaction — this is a baseline UX requirement for any production agent.

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
