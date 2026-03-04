"""
Module 4 Lab — Async Agent Loops + Streaming
=============================================
Convert the synchronous agent loop from Module 3 to fully async.
Add streaming support with SSE parsing and tool call delta accumulation.

Run with:
    uv run python src/async_agent.py
    uv run python src/async_agent.py --task "your question here"
    uv run python src/async_agent.py --stream "your question here"
    uv run python src/async_agent.py --benchmark

Tasks:
  1. Implement AsyncAgent.run()          — async agent loop with asyncio.gather
  2. Implement AsyncAgent.stream()       — SSE streaming, text only
  3. Extend stream() for tool calls      — accumulate deltas, execute tools
  4. Implement benchmark()               — sequential vs concurrent timing
  5. Implement stream_with_progress()    — rich-formatted live output
"""

import argparse
import asyncio
import fnmatch
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

# ---------------------------------------------------------------------------
# LLM connection — defaults to Ollama (local). Set LLM_PROVIDER=azure to use Azure OpenAI.
# ---------------------------------------------------------------------------
PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")

if PROVIDER == "azure":
    ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    API_KEY = os.environ["AZURE_OPENAI_KEY"]
    DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
    BASE_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
    HEADERS = {"api-key": API_KEY, "Content-Type": "application/json"}
    MODEL = DEPLOYMENT
else:  # ollama
    ENDPOINT = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
    BASE_URL = f"{ENDPOINT}/v1/chat/completions"
    HEADERS = {"Content-Type": "application/json"}
    MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
MAX_ITERATIONS = 10

console = Console()

# ---------------------------------------------------------------------------
# Tool Definitions
# Reused from Module 3 — same tools, same schemas
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List the files and subdirectories at a given path on the local filesystem. "
                "Use this to explore directory structure. Returns one entry per line, "
                "prefixed with 'file' or 'dir'. "
                "Do NOT use this to read file contents — use read_file for that."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative or absolute path to the directory to list. "
                            "Use '.' for the current directory."
                        ),
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the full text contents of a file on the local filesystem. "
                "Use this when you need to examine code or document content. "
                "Returns an error if the file is binary or exceeds 20kb. "
                "Do NOT use this to list directory contents — use list_directory instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative or absolute path to the file to read.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Recursively search a directory for files matching a glob pattern. "
                "Use this when you need to find files by name (e.g. '*.py', 'README.md'). "
                "Returns a list of matching file paths relative to the search directory. "
                "Does NOT search file contents — only matches file names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The root directory to search recursively.",
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Glob pattern to match against file names, e.g. '*.py', "
                            "'*.toml', 'README.*'. Not a content search."
                        ),
                    },
                },
                "required": ["directory", "pattern"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool Implementations (async wrappers around sync filesystem ops)
# The filesystem tools are inherently synchronous (local disk).
# In production you'd use asyncio.to_thread() to avoid blocking the event loop.
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_BYTES = 20_000
SAFE_ROOT = Path(".").resolve()


def _safe_path(path_str: str) -> Path:
    """Resolve path and verify it stays within SAFE_ROOT."""
    resolved = (SAFE_ROOT / path_str).resolve()
    if not resolved.is_relative_to(SAFE_ROOT):
        raise ValueError(f"Path '{path_str}' is outside the allowed directory")
    return resolved


async def tool_list_directory(path: str) -> str:
    # asyncio.to_thread runs blocking code without blocking the event loop
    return await asyncio.to_thread(_sync_list_directory, path)


async def tool_read_file(path: str) -> str:
    return await asyncio.to_thread(_sync_read_file, path)


async def tool_search_files(directory: str, pattern: str) -> str:
    return await asyncio.to_thread(_sync_search_files, directory, pattern)


def _sync_list_directory(path: str) -> str:
    try:
        target = _safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not target.exists():
        return f"Error: path does not exist: {path}"
    if not target.is_dir():
        return f"Error: path is a file, not a directory: {path}"
    entries = []
    for item in sorted(target.iterdir()):
        kind = "dir" if item.is_dir() else "file"
        entries.append(f"{kind}  {item.name}")
    return "\n".join(entries) if entries else "(empty directory)"


def _sync_read_file(path: str) -> str:
    try:
        target = _safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not target.exists():
        return f"Error: file does not exist: {path}"
    if not target.is_file():
        return f"Error: path is a directory, not a file: {path}"
    size = target.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        return f"Error: file too large ({size:,} bytes, max {MAX_FILE_SIZE_BYTES:,})"
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "Error: file appears to be binary and cannot be read as text"


def _sync_search_files(directory: str, pattern: str) -> str:
    try:
        target = _safe_path(directory)
    except ValueError as e:
        return f"Error: {e}"
    if not target.exists():
        return f"Error: directory does not exist: {directory}"
    if not target.is_dir():
        return f"Error: path is not a directory: {directory}"
    matches = []
    for item in target.rglob("*"):
        if item.is_file() and fnmatch.fnmatch(item.name, pattern):
            matches.append(str(item.relative_to(SAFE_ROOT)))
    if not matches:
        return f"No files matching '{pattern}' found in '{directory}'"
    return "\n".join(sorted(matches))


async def call_tool_async(name: str, arguments: dict) -> str:
    """Dispatch a tool call by name. Returns result as a string."""
    if name == "list_directory":
        return await tool_list_directory(arguments["path"])
    elif name == "read_file":
        return await tool_read_file(arguments["path"])
    elif name == "search_files":
        return await tool_search_files(arguments["directory"], arguments["pattern"])
    else:
        return f"Error: unknown tool '{name}'"


# ---------------------------------------------------------------------------
# Helper: execute a list of tool calls concurrently
# ---------------------------------------------------------------------------
async def execute_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """
    Execute all tool calls concurrently using asyncio.gather.
    Returns a list of tool result messages ready to append to the conversation.
    """
    # TODO (Task 1 / Task 3): implement this function
    # For each tool call:
    #   1. Parse the arguments string with json.loads()
    #   2. Log the call: console.print(f"[dim][TOOL] {name}({args})[/dim]")
    #   3. Call call_tool_async(name, args) — wrap in try/except
    #   4. Return {"role": "tool", "tool_call_id": tc["id"], "content": result}
    #
    # Use asyncio.gather to run all of them concurrently.
    # Hint: define an inner async def execute_one(tc) and gather over all tc.
    raise NotImplementedError("Task 1: implement execute_tool_calls()")


# ---------------------------------------------------------------------------
# The Async Agent
# ---------------------------------------------------------------------------
class AsyncAgent:
    """
    Async agent with three operating modes:
      - run()                 — standard async loop, parallel tool execution
      - stream()              — streaming SSE, accumulate deltas
      - stream_with_progress()— streaming with rich live display
    """

    SYSTEM_PROMPT = (
        "You are a helpful assistant with access to filesystem tools. "
        "Use the tools to find information and answer the user's question accurately."
    )

    def __init__(self) -> None:
        # A single shared client for all calls — reuses connections
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        await self._client.aclose()

    # -----------------------------------------------------------------------
    # Task 1: Async Agent Loop
    # -----------------------------------------------------------------------
    async def run(self, user_query: str) -> str:
        """
        Run the agent loop asynchronously.

        Uses asyncio.gather to execute parallel tool calls concurrently.
        Returns the model's final text response.
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ]

        console.print(Panel(f"[bold]Query:[/bold] {user_query}", border_style="blue"))

        for iteration in range(1, MAX_ITERATIONS + 1):
            console.print(f"\n[dim]--- Iteration {iteration} ---[/dim]")

            # TODO: await the API call using self._client.post(...)
            # Payload: {"messages": messages, "tools": TOOLS, "tool_choice": "auto"}
            # Do NOT include "stream": true here — that is for stream() below
            response_data = None  # replace with actual awaited call
            raise NotImplementedError("Task 1: implement the async loop body")

            # TODO: extract message and finish_reason from response_data
            message = None
            finish_reason = None

            # TODO: append assistant message to messages (always required)

            # TODO: if finish_reason == "stop", return message["content"]

            # TODO: if finish_reason == "tool_calls":
            #   - call execute_tool_calls(message["tool_calls"])
            #   - extend messages with the returned tool result messages
            #   - continue the loop

            # TODO: handle unexpected finish_reason (content_filter, length)

        return f"Error: agent exceeded {MAX_ITERATIONS} iterations without completing"

    # -----------------------------------------------------------------------
    # Task 2 & 3: Streaming
    # -----------------------------------------------------------------------
    async def stream(self, user_query: str) -> str:
        """
        Run the agent loop with SSE streaming.

        Task 2: implement streaming for text-only responses.
        Task 3: extend to handle tool calls in the stream.

        Returns the full accumulated response text.
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ]

        console.print(Panel(f"[bold]Query (streaming):[/bold] {user_query}", border_style="cyan"))

        for iteration in range(1, MAX_ITERATIONS + 1):
            console.print(f"\n[dim]--- Iteration {iteration} (stream) ---[/dim]")

            # TODO (Task 2): Make a streaming request.
            # Add "stream": true to the payload.
            # Use self._client.stream("POST", BASE_URL, ...) as an async context manager.
            # This gives you the response object before the body is fully received.
            #
            # Template:
            #   async with self._client.stream("POST", BASE_URL, headers=HEADERS, json=payload) as resp:
            #       async for line in resp.aiter_lines():
            #           ...
            raise NotImplementedError("Task 2: implement the streaming body")

            # TODO (Task 2): Inside the aiter_lines() loop:
            # 1. Skip lines that don't start with "data: "
            # 2. Strip the "data: " prefix (line[6:])
            # 3. If the stripped payload is "[DONE]", break
            # 4. json.loads() the payload
            # 5. Get the delta from chunk["choices"][0]["delta"]
            # 6. If delta has "content", print it (end="", flush=True) and accumulate it

            # TODO (Task 3): Also handle tool call deltas.
            # Maintain a tool_calls_acc dict keyed by the tool call index (tc_delta["index"]).
            # Accumulate: id, function.name, function.arguments (these arrive as string fragments)
            # After finish_reason == "tool_calls":
            #   - Reconstruct the assistant message with the accumulated tool_calls
            #   - Append it to messages
            #   - Call execute_tool_calls() and extend messages with results
            #   - Continue the outer loop (do NOT return yet)

        return f"Error: agent exceeded {MAX_ITERATIONS} iterations without completing"

    # -----------------------------------------------------------------------
    # Task 5: Streaming with Rich Progress Display
    # -----------------------------------------------------------------------
    async def stream_with_progress(self, user_query: str) -> str:
        """
        Streaming agent loop with a rich-formatted live display.

        Display requirements:
        - Show a status line while waiting for first token
        - Print tokens as they arrive using rich Console
        - Show tool calls in a distinct style: [cyan][TOOL] name(args)[/cyan]
        - Clearly demarcate the final answer

        Hint: rich.live.Live can update a Panel in real-time.
        Alternatively, use console.print with end="" for simpler streaming output.
        """
        # TODO (Task 5): implement rich progress display around the streaming loop
        # You can reuse stream() logic and add formatting around it,
        # or implement a fresh loop here with richer output.
        raise NotImplementedError("Task 5: implement stream_with_progress()")


# ---------------------------------------------------------------------------
# Task 4: Benchmark — Sequential vs. Concurrent
# ---------------------------------------------------------------------------
async def benchmark() -> None:
    """
    Run 5 identical tasks sequentially, then concurrently.
    Print a comparison table with wall-clock times and speedup.
    """
    # A simple task that requires one LLM call and no tools
    # so the benchmark measures network I/O, not tool execution
    tasks = [
        "What is the capital of France? Answer in one word."
    ] * 5

    agent = AsyncAgent()
    try:
        # TODO (Task 4): Sequential run
        # Use a for loop with `await agent.run(task)` for each task
        # Record wall-clock time with time.perf_counter()
        sequential_time: float = 0.0
        raise NotImplementedError("Task 4: implement sequential benchmark")

        # TODO (Task 4): Concurrent run
        # Use asyncio.gather(*[agent.run(task) for task in tasks])
        # Record wall-clock time
        concurrent_time: float = 0.0
        raise NotImplementedError("Task 4: implement concurrent benchmark")

        # TODO (Task 4): Print results
        # Build a rich Table showing:
        #   Mode | Tasks | Total Time | Time per Task
        #   Sequential | 5 | Xs | Xs
        #   Concurrent | 5 | Xs | Xs
        # Then print speedup: f"Speedup: {sequential_time / concurrent_time:.1f}x"

    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    parser = argparse.ArgumentParser(description="Module 4: Async Agent + Streaming")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--task", type=str, help="Run async agent loop on a query")
    group.add_argument("--stream", type=str, help="Run streaming agent on a query")
    group.add_argument("--progress", type=str, help="Run streaming with rich progress display")
    group.add_argument("--benchmark", action="store_true", help="Run sequential vs concurrent benchmark")
    args = parser.parse_args()

    if args.benchmark:
        await benchmark()
        return

    agent = AsyncAgent()
    try:
        if args.stream:
            result = await agent.stream(args.stream)
            console.print(Panel(f"[bold green]Final Answer:[/bold green]\n{result}", border_style="green"))
        elif args.progress:
            result = await agent.stream_with_progress(args.progress)
            console.print(Panel(f"[bold green]Final Answer:[/bold green]\n{result}", border_style="green"))
        else:
            query = args.task or "What Python files exist in the current directory?"
            result = await agent.run(query)
            console.print(Panel(f"[bold green]Final Answer:[/bold green]\n{result}", border_style="green"))
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
