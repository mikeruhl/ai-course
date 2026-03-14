"""
Module 06 — Task 5: ReAct vs Plain Tool Loop Benchmark
=======================================================
Run 10 reasoning tasks through two agents and compare:
  - Number of tool calls made
  - Answer correctness (manual check)
  - Total tokens used

NOTE AFTER COMPLETING: Add your observations at the top of this file.
What did you find? Did ReAct reduce wrong tool calls on multi-hop tasks?
At what token cost?

# STUDENT OBSERVATIONS (fill in after running):
# Multi-hop tasks (1, 4, 7): ReAct made ___ fewer wrong tool calls
# Single-hop tasks (2, 5, 8): Difference was ___
# Average token overhead of ReAct: ___x
# Conclusion: ___

Run with:
    uv run python src/benchmark.py
"""

import json
import os
import time

import httpx
from dotenv import load_dotenv
from rich.console import Console
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
elif PROVIDER == "vertex":
    import google.auth
    import google.auth.transport.requests
    GCP_PROJECT = os.environ["GCP_PROJECT_ID"]
    GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
    _credentials, _ = google.auth.default()
    _credentials.refresh(google.auth.transport.requests.Request())
    BASE_URL = f"https://{GCP_REGION}-aiplatform.googleapis.com/v1/projects/{GCP_PROJECT}/locations/{GCP_REGION}/endpoints/openapi/chat/completions"
    HEADERS = {"Authorization": f"Bearer {_credentials.token}", "Content-Type": "application/json"}
    MODEL = os.environ.get("VERTEX_MODEL", "google/gemini-2.0-flash")
else:  # ollama
    ENDPOINT = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
    BASE_URL = f"{ENDPOINT}/v1/chat/completions"
    HEADERS = {"Content-Type": "application/json"}
    MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")

console = Console()

# ---------------------------------------------------------------------------
# Benchmark tasks
# Each task has: question, expected_answer_contains, type
# Types: "multi-hop", "single-hop", "ambiguous"
# ---------------------------------------------------------------------------

BENCHMARK_TASKS = [
    {
        "id": 1,
        "type": "multi-hop",
        "question": "Who invented the telephone and what nationality were they?",
        "expected_contains": ["bell", "scottish", "british", "american"],
        "notes": "Requires: find inventor, then look up nationality",
    },
    {
        "id": 2,
        "type": "single-hop",
        "question": "What year did Thomas Edison develop the light bulb?",
        "expected_contains": ["1879"],
        "notes": "Single lookup",
    },
    {
        "id": 3,
        "type": "multi-hop",
        "question": "What was the name of the plan Germany used to invade France in WWI, and why did it bring Britain into the war?",
        "expected_contains": ["schlieffen", "belgium", "neutral"],
        "notes": "Requires: find plan name, then find why Britain entered",
    },
    {
        "id": 4,
        "type": "single-hop",
        "question": "What does the acronym MAIN stand for in WWI history?",
        "expected_contains": ["militarism", "alliances", "imperialism", "nationalism"],
        "notes": "Single fact lookup",
    },
    {
        "id": 5,
        "type": "ambiguous",
        "question": "Who killed Archduke Franz Ferdinand?",
        "expected_contains": ["princip", "gavrilo"],
        "notes": "Ambiguous phrasing — could ask for name or group",
    },
    {
        "id": 6,
        "type": "multi-hop",
        "question": "James Madison co-wrote a famous series of essays. What were they called and how many essays were in the series?",
        "expected_contains": ["federalist", "85"],
        "notes": "Requires: find Madison's essays, then find count",
    },
    {
        "id": 7,
        "type": "single-hop",
        "question": "Who presided over the Constitutional Convention of 1787?",
        "expected_contains": ["washington", "george"],
        "notes": "Single lookup",
    },
    {
        "id": 8,
        "type": "ambiguous",
        "question": "What triggered the start of World War One?",
        "expected_contains": ["assassination", "ferdinand", "sarajevo"],
        "notes": "Many valid answers — test if agent chooses the most direct cause",
    },
    {
        "id": 9,
        "type": "multi-hop",
        "question": "What was the Triple Alliance and which country eventually switched sides?",
        "expected_contains": ["germany", "austria", "italy"],
        "notes": "Requires: find alliance members, then Italy's switch",
    },
    {
        "id": 10,
        "type": "ambiguous",
        "question": "How many people died in World War One?",
        "expected_contains": ["20 million", "million"],
        "notes": "Number varies by source — test if agent hedges appropriately",
    },
]

# ---------------------------------------------------------------------------
# Simulated tools (same knowledge base as research_agent.py)
# ---------------------------------------------------------------------------

KNOWLEDGE_BASE = {
    "telephone": "Alexander Graham Bell invented the telephone. He received patent 174,465 in 1876.",
    "alexander graham bell": "Alexander Graham Bell (1847–1922) was Scottish-born, later became a naturalized American citizen.",
    "light bulb thomas edison": "Thomas Edison developed the incandescent light bulb in 1879.",
    "wwi main acronym": "MAIN: Militarism, Alliances, Imperialism, Nationalism — the four underlying causes of WWI.",
    "franz ferdinand assassination": "Archduke Franz Ferdinand was assassinated by Gavrilo Princip on 28 June 1914 in Sarajevo.",
    "schlieffen plan": "Germany's Schlieffen Plan called for invading France through Belgium. Violation of Belgian neutrality brought Britain into WWI.",
    "james madison federalist": "James Madison co-wrote The Federalist Papers with Hamilton and Jay. 85 essays total, published 1787–1788.",
    "constitutional convention 1787": "George Washington presided over the Constitutional Convention of 1787.",
    "wwi triggers": "WWI was triggered by the assassination of Franz Ferdinand, Austria-Hungary's ultimatum to Serbia, and Germany's invasion of Belgium.",
    "triple alliance": "The Triple Alliance (1882): Germany, Austria-Hungary, Italy. Italy switched sides in 1915, joining the Entente.",
    "wwi casualties": "World War One resulted in approximately 20 million deaths (military and civilian).",
}


def tool_search(query: str) -> str:
    key = query.lower().strip()
    for k, v in KNOWLEDGE_BASE.items():
        if k in key or key in k or any(w in k for w in key.split() if len(w) > 3):
            return v
    return f"No result for '{query}'."


BENCHMARK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search a knowledge base. Be specific with your query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"],
            },
        },
    }
]


# ---------------------------------------------------------------------------
# Agent implementations
# ---------------------------------------------------------------------------

def run_plain_tool_loop(question: str) -> tuple[str, int, int]:
    """
    Plain tool loop — no CoT system prompt, no reasoning trace requirement.
    Returns (answer, tool_call_count, total_tokens)
    """
    # TODO (Task 5): Implement the plain tool loop.
    # System prompt: just "You are a helpful assistant. Answer questions accurately."
    # No instruction to reason before tool calls.
    # Loop: call model -> if tool_calls, execute -> append result -> repeat.
    # Return (final_answer, number_of_tool_calls_made, total_tokens)
    raise NotImplementedError("TODO: implement run_plain_tool_loop()")


def run_react_tool_loop(question: str) -> tuple[str, int, int]:
    """
    ReAct tool loop — CoT system prompt requires reasoning before every action.
    Returns (answer, tool_call_count, total_tokens)
    """
    # TODO (Task 5): Implement the ReAct tool loop.
    # System prompt: explicitly require a Thought in the content field before each tool call.
    # Same tool execution logic as plain loop.
    # Return (final_answer, number_of_tool_calls_made, total_tokens)
    raise NotImplementedError("TODO: implement run_react_tool_loop()")


def check_answer(answer: str, expected_contains: list[str]) -> bool:
    """Returns True if any expected string appears in the answer (case-insensitive)."""
    answer_lower = answer.lower()
    return any(e.lower() in answer_lower for e in expected_contains)


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark():
    results = []

    for task in BENCHMARK_TASKS:
        console.print(f"\n[bold]Task {task['id']} ({task['type']})[/bold]: {task['question'][:80]}")

        # Plain tool loop
        try:
            plain_answer, plain_calls, plain_tokens = run_plain_tool_loop(task["question"])
            plain_correct = check_answer(plain_answer, task["expected_contains"])
        except NotImplementedError:
            plain_answer, plain_calls, plain_tokens, plain_correct = "NOT IMPLEMENTED", 0, 0, False

        # ReAct loop
        try:
            react_answer, react_calls, react_tokens = run_react_tool_loop(task["question"])
            react_correct = check_answer(react_answer, task["expected_contains"])
        except NotImplementedError:
            react_answer, react_calls, react_tokens, react_correct = "NOT IMPLEMENTED", 0, 0, False

        results.append({
            "id": task["id"],
            "type": task["type"],
            "plain_correct": plain_correct,
            "plain_calls": plain_calls,
            "plain_tokens": plain_tokens,
            "react_correct": react_correct,
            "react_calls": react_calls,
            "react_tokens": react_tokens,
        })

        console.print(
            f"  Plain: {'[green]CORRECT[/green]' if plain_correct else '[red]WRONG[/red]'} "
            f"| {plain_calls} calls | {plain_tokens} tokens"
        )
        console.print(
            f"  ReAct: {'[green]CORRECT[/green]' if react_correct else '[red]WRONG[/red]'} "
            f"| {react_calls} calls | {react_tokens} tokens"
        )

    # Summary table
    table = Table(title="Benchmark Results: ReAct vs Plain Tool Loop")
    table.add_column("Task")
    table.add_column("Type")
    table.add_column("Plain Correct")
    table.add_column("Plain Calls")
    table.add_column("Plain Tokens")
    table.add_column("ReAct Correct")
    table.add_column("ReAct Calls")
    table.add_column("ReAct Tokens")
    table.add_column("Token Overhead")

    for r in results:
        overhead = (
            f"{r['react_tokens'] / r['plain_tokens']:.1f}x"
            if r["plain_tokens"] > 0
            else "N/A"
        )
        table.add_row(
            str(r["id"]),
            r["type"],
            "[green]Y[/green]" if r["plain_correct"] else "[red]N[/red]",
            str(r["plain_calls"]),
            str(r["plain_tokens"]),
            "[green]Y[/green]" if r["react_correct"] else "[red]N[/red]",
            str(r["react_calls"]),
            str(r["react_tokens"]),
            overhead,
        )

    console.print(table)

    # Aggregate stats
    multi_hop = [r for r in results if r["type"] == "multi-hop"]
    plain_mh_correct = sum(1 for r in multi_hop if r["plain_correct"])
    react_mh_correct = sum(1 for r in multi_hop if r["react_correct"])

    console.print(f"\n[bold]Multi-hop accuracy:[/bold]")
    console.print(f"  Plain: {plain_mh_correct}/{len(multi_hop)}")
    console.print(f"  ReAct: {react_mh_correct}/{len(multi_hop)}")

    total_plain_tokens = sum(r["plain_tokens"] for r in results if r["plain_tokens"] > 0)
    total_react_tokens = sum(r["react_tokens"] for r in results if r["react_tokens"] > 0)
    if total_plain_tokens > 0:
        console.print(f"\n[bold]Overall token overhead:[/bold] {total_react_tokens / total_plain_tokens:.2f}x")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def chat_with_tools(messages, tools, temperature=0, max_tokens=500) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    run_benchmark()
