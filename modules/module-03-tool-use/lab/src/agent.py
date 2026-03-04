"""
Module 3 Lab — The Raw Agent Loop
===================================
Implement a filesystem Q&A agent using only httpx and the Azure OpenAI API.
No frameworks. No SDKs beyond httpx.

Run with:
    uv run python src/agent.py

Tasks:
  1. Implement run_agent() — the core loop
  2. Improve tool descriptions to reduce wrong tool selection
  3. Handle parallel tool calls
  4. Add error resilience and argument validation
  5. Answer the codebase Q&A queries at the bottom
"""

import fnmatch
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

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
# TODO (Task 2): These descriptions are intentionally weak. Improve them.
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Lists files.",  # TODO: improve this description
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path.",  # TODO: improve
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
            "description": "Reads a file.",  # TODO: improve this description
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to file.",  # TODO: improve
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
            "description": "Searches files.",  # TODO: improve this description
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Where to search.",  # TODO: improve
                    },
                    "pattern": {
                        "type": "string",
                        "description": "What to search for.",  # TODO: improve
                    },
                },
                "required": ["directory", "pattern"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool Implementations
# Do not modify these — they work correctly.
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_BYTES = 20_000  # 20kb cap on file reads
SAFE_ROOT = Path(".").resolve()  # agents can only read within this directory


def _safe_path(path_str: str) -> Path:
    """Resolve path and verify it's within SAFE_ROOT. Raises ValueError otherwise."""
    resolved = (SAFE_ROOT / path_str).resolve()
    if not resolved.is_relative_to(SAFE_ROOT):
        raise ValueError(f"Path '{path_str}' is outside the allowed directory")
    return resolved


def tool_list_directory(path: str) -> str:
    target = _safe_path(path)
    if not target.exists():
        return f"Error: path does not exist: {path}"
    if not target.is_dir():
        return f"Error: path is a file, not a directory: {path}"

    entries = []
    for item in sorted(target.iterdir()):
        kind = "dir" if item.is_dir() else "file"
        entries.append(f"{kind}  {item.name}")

    return "\n".join(entries) if entries else "(empty directory)"


def tool_read_file(path: str) -> str:
    target = _safe_path(path)
    if not target.exists():
        return f"Error: file does not exist: {path}"
    if not target.is_file():
        return f"Error: path is a directory, not a file: {path}"

    size = target.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        return f"Error: file is too large ({size:,} bytes). Max is {MAX_FILE_SIZE_BYTES:,} bytes."

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: file appears to be binary and cannot be read as text"


def tool_search_files(directory: str, pattern: str) -> str:
    target = _safe_path(directory)
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


def call_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call by name. Returns result as a string."""
    if name == "list_directory":
        return tool_list_directory(arguments["path"])
    elif name == "read_file":
        return tool_read_file(arguments["path"])
    elif name == "search_files":
        return tool_search_files(arguments["directory"], arguments["pattern"])
    else:
        return f"Error: unknown tool '{name}'"


# ---------------------------------------------------------------------------
# The Agent Loop
# TODO (Task 1): Implement this function
# ---------------------------------------------------------------------------
def run_agent(user_query: str) -> str:
    """
    Run the agent loop until the model gives a final answer or hits max iterations.

    Returns the model's final text response.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant with access to filesystem tools. "
                "Use the tools to find information and answer the user's question accurately."
            ),
        },
        {"role": "user", "content": user_query},
    ]

    console.print(Panel(f"[bold]Query:[/bold] {user_query}", border_style="blue"))

    for iteration in range(1, MAX_ITERATIONS + 1):
        console.print(f"\n[dim]--- Iteration {iteration} ---[/dim]")

        # TODO: Call the API with messages and TOOLS
        # Hint: include "tool_choice": "auto" in the payload
        response = None  # replace with actual API call
        raise NotImplementedError(
            "Task 1: implement the API call and loop logic below"
        )

        # TODO: Get the message and finish_reason from the response
        message = None
        finish_reason = None

        # TODO: Append the assistant message to messages (always do this)

        # TODO: If finish_reason == "stop", return the message content

        # TODO: If finish_reason == "tool_calls":
        #   - For each tool call in message["tool_calls"]:
        #     - Parse the arguments (json.loads on the arguments string)
        #     - Log the tool call (console.print)
        #     - Execute via call_tool()
        #     - Log the result
        #     - Append a tool result message to messages
        #   - Continue the loop (don't return yet)

        # TODO: Handle unexpected finish_reason values

    return f"Error: agent exceeded {MAX_ITERATIONS} iterations without completing"


# ---------------------------------------------------------------------------
# Task 5: Codebase Q&A queries
# Run these after completing Tasks 1-4
# ---------------------------------------------------------------------------
QUERIES = [
    "How many Python files are in the modules directory? List their paths.",
    "What Python dependencies does module-02 use? Check its pyproject.toml.",
    "Find all files that contain the word 'terraform' in their name.",
    "What are the learning objectives of module-01? Check its README.",
]

if __name__ == "__main__":
    # Run a single query to test your implementation
    # Uncomment the QUERIES loop once Task 1 is working

    test_query = "What files are in the modules directory?"
    result = run_agent(test_query)
    console.print(Panel(f"[bold green]Final Answer:[/bold green]\n{result}", border_style="green"))

    # Uncomment to run all Task 5 queries:
    # for query in QUERIES:
    #     answer = run_agent(query)
    #     console.print(Panel(f"[bold green]Answer:[/bold green]\n{answer}", border_style="green"))
    #     print()
