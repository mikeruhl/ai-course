"""
Module 10 Lab A — Orchestrator-Subagent Pattern
================================================
Build an orchestrator that routes queries to specialist agents.

Specialists: code_reviewer, security_analyst, performance_advisor

Tasks:
  1. Implement the three specialist agents (each returns JSON findings)
  2. Implement the orchestrator that routes to the right specialist
  3. Add confidence scoring — route to all specialists if confidence < 0.7
  4. Test with three routing test cases

Run with: uv run python src/orchestrator_subagent.py
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# Azure OpenAI configuration
# ---------------------------------------------------------------------------
ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
API_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

BASE_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"

HEADERS = {
    "Content-Type": "application/json",
    "api-key": API_KEY,
}

# ---------------------------------------------------------------------------
# Specialist system prompts
# ---------------------------------------------------------------------------
SPECIALIST_SYSTEM_PROMPTS: dict[str, str] = {
    "code_reviewer": (
        "You are an expert code reviewer. Analyse the provided code for quality, "
        "readability, maintainability, and adherence to best practices. "
        "Respond ONLY with valid JSON matching this schema exactly:\n"
        '{"findings": ["<finding1>", ...], "overall_grade": "A|B|C|D|F", '
        '"top_recommendation": "<single most important improvement>"}'
    ),
    "security_analyst": (
        "You are a senior application security engineer. Analyse the provided code "
        "for security vulnerabilities (OWASP Top 10, injection, auth issues, secrets, etc.). "
        "Respond ONLY with valid JSON matching this schema exactly:\n"
        '{"vulnerabilities": ["<vuln1>", ...], "risk_level": "critical|high|medium|low|none", '
        '"immediate_action": "<the single most urgent remediation step>"}'
    ),
    "performance_advisor": (
        "You are a performance engineering specialist. Analyse the provided code for "
        "bottlenecks, inefficient algorithms, memory issues, and scalability concerns. "
        "Respond ONLY with valid JSON matching this schema exactly:\n"
        '{"bottlenecks": ["<bottleneck1>", ...], "estimated_improvement": "<X% or description>", '
        '"priority_fix": "<the single highest-impact optimisation>"}'
    ),
}

# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict], response_format: dict | None = None) -> str:
    """
    Call Azure OpenAI synchronously via raw httpx POST.

    Args:
        messages: List of {"role": ..., "content": ...} dicts.
        response_format: Optional {"type": "json_object"} to force JSON mode.

    Returns:
        The assistant message content as a plain string.

    Raises:
        RuntimeError: If the API returns a non-2xx status.
    """
    if not ENDPOINT or not API_KEY:
        raise RuntimeError(
            "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY must be set in your .env file."
        )

    body: dict = {"messages": messages, "temperature": 0.2}
    if response_format:
        body["response_format"] = response_format

    response = httpx.post(BASE_URL, headers=HEADERS, json=body, timeout=60.0)

    if response.status_code != 200:
        raise RuntimeError(
            f"Azure OpenAI returned {response.status_code}: {response.text}"
        )

    return response.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Specialist agents
# ---------------------------------------------------------------------------

def code_reviewer_agent(query: str, code: str) -> dict:
    """
    Review code quality and return structured findings.

    TODO (Task 1): Improve the user prompt below to give the LLM more context
    about what the developer cares about. For example, include the query so the
    reviewer can focus its feedback on the area the developer asked about.

    Args:
        query: The developer's question or concern.
        code:  The source code to review.

    Returns:
        dict with keys: findings (list), overall_grade (str), top_recommendation (str)
    """
    # TODO (Task 1): Enhance this prompt — currently it ignores `query` entirely.
    # Consider prefixing the user message with something like:
    #   f"Developer concern: {query}\n\nCode to review:\n{code}"
    messages = [
        {"role": "system", "content": SPECIALIST_SYSTEM_PROMPTS["code_reviewer"]},
        {"role": "user", "content": f"Review this code:\n\n```python\n{code}\n```"},
    ]
    raw = call_llm(messages, response_format={"type": "json_object"})
    return json.loads(raw)


def security_analyst_agent(query: str, code: str) -> dict:
    """
    Analyse code for security vulnerabilities.

    TODO (Task 1): The prompt below does not surface `query` to the LLM.
    Update it so the analyst knows which threat area the developer is worried about.

    Args:
        query: The developer's security question or concern.
        code:  The source code to analyse.

    Returns:
        dict with keys: vulnerabilities (list), risk_level (str), immediate_action (str)
    """
    # TODO (Task 1): Incorporate `query` into the user message.
    messages = [
        {"role": "system", "content": SPECIALIST_SYSTEM_PROMPTS["security_analyst"]},
        {"role": "user", "content": f"Analyse this code for security issues:\n\n```python\n{code}\n```"},
    ]
    raw = call_llm(messages, response_format={"type": "json_object"})
    return json.loads(raw)


def performance_advisor_agent(query: str, code: str) -> dict:
    """
    Identify performance bottlenecks and recommend optimisations.

    TODO (Task 1): Surface `query` in the prompt so the advisor can prioritise
    feedback relevant to the developer's specific performance concern.

    Args:
        query: The developer's performance question or concern.
        code:  The source code to analyse.

    Returns:
        dict with keys: bottlenecks (list), estimated_improvement (str), priority_fix (str)
    """
    # TODO (Task 1): Incorporate `query` into the user message.
    messages = [
        {"role": "system", "content": SPECIALIST_SYSTEM_PROMPTS["performance_advisor"]},
        {"role": "user", "content": f"Identify performance issues in this code:\n\n```python\n{code}\n```"},
    ]
    raw = call_llm(messages, response_format={"type": "json_object"})
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

_ROUTING_SYSTEM_PROMPT = (
    "You are a routing orchestrator. Given a developer's query and code snippet, "
    "decide which specialist should handle it. "
    "Respond ONLY with valid JSON:\n"
    '{"agent": "code_reviewer|security_analyst|performance_advisor", '
    '"reason": "<one sentence explanation>", '
    '"confidence": <float between 0.0 and 1.0>}'
)

_SPECIALIST_MAP = {
    "code_reviewer": code_reviewer_agent,
    "security_analyst": security_analyst_agent,
    "performance_advisor": performance_advisor_agent,
}


def orchestrator(query: str, code: str) -> dict:
    """
    Route a query to the appropriate specialist agent (or all of them).

    Routing logic:
      - Ask the LLM which specialist fits best and how confident it is.
      - confidence >= 0.7  →  call that one specialist.
      - confidence < 0.7   →  TODO (Task 3): call ALL specialists and merge results.

    Args:
        query: The developer's question.
        code:  The relevant code snippet.

    Returns:
        dict with keys:
            routed_to (str | list): agent name(s) used
            routing_reason (str): why this agent was chosen
            confidence (float): routing confidence
            result (dict | list): findings from the specialist(s)
    """
    # Step 1: Ask the LLM for a routing decision.
    routing_messages = [
        {"role": "system", "content": _ROUTING_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Query: {query}\n\n"
                f"Code:\n```python\n{code}\n```"
            ),
        },
    ]
    routing_raw = call_llm(routing_messages, response_format={"type": "json_object"})
    routing = json.loads(routing_raw)

    agent_name: str = routing["agent"]
    reason: str = routing["reason"]
    confidence: float = float(routing["confidence"])

    # Step 2: Dispatch based on confidence.
    if confidence >= 0.7:
        agent_fn = _SPECIALIST_MAP[agent_name]
        result = agent_fn(query, code)
        return {
            "routed_to": agent_name,
            "routing_reason": reason,
            "confidence": confidence,
            "result": result,
        }

    # TODO (Task 3): confidence < 0.7 means the query spans multiple concerns.
    # Instead of raising NotImplementedError in production, call ALL specialists,
    # collect their results into a list, and return a merged response like:
    #
    #   results = []
    #   for name, fn in _SPECIALIST_MAP.items():
    #       results.append({"agent": name, "findings": fn(query, code)})
    #   return {
    #       "routed_to": list(_SPECIALIST_MAP.keys()),
    #       "routing_reason": reason,
    #       "confidence": confidence,
    #       "result": results,
    #   }
    raise NotImplementedError(
        "Task 3: Implement multi-specialist dispatch for low-confidence routing "
        f"(confidence={confidence:.2f}). See the TODO comment above this line."
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

TEST_CASES: list[dict] = [
    {
        "label": "Code quality concern",
        "query": "This function is hard to read. What can be improved?",
        "code": (
            "def p(d,k,v):\n"
            "    if k in d:\n"
            "        d[k]=d[k]+v\n"
            "    else:\n"
            "        d[k]=v\n"
            "    return d"
        ),
    },
    {
        "label": "Security concern",
        "query": "Is there a SQL injection vulnerability here?",
        "code": (
            "def get_user(username):\n"
            "    query = f\"SELECT * FROM users WHERE username = '{username}'\"\n"
            "    return db.execute(query).fetchone()"
        ),
    },
    {
        "label": "Performance concern",
        "query": "Why is this loop so slow with large lists?",
        "code": (
            "def find_duplicates(items):\n"
            "    duplicates = []\n"
            "    for i in range(len(items)):\n"
            "        for j in range(len(items)):\n"
            "            if i != j and items[i] == items[j]:\n"
            "                if items[i] not in duplicates:\n"
            "                    duplicates.append(items[i])\n"
            "    return duplicates"
        ),
    },
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    console.rule("[bold cyan]Module 10 Lab A — Orchestrator-Subagent Pattern[/bold cyan]")

    for i, case in enumerate(TEST_CASES, start=1):
        console.print(f"\n[bold yellow]Test Case {i}: {case['label']}[/bold yellow]")
        console.print(f"[dim]Query:[/dim] {case['query']}")
        console.print(Syntax(case["code"], "python", theme="monokai", line_numbers=True))

        start = time.perf_counter()
        try:
            outcome = orchestrator(case["query"], case["code"])
            elapsed = time.perf_counter() - start

            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_row("[green]Routed to[/green]", str(outcome["routed_to"]))
            table.add_row("[green]Confidence[/green]", f"{outcome['confidence']:.0%}")
            table.add_row("[green]Reason[/green]", outcome["routing_reason"])
            table.add_row("[green]Latency[/green]", f"{elapsed:.2f}s")
            console.print(table)

            result_json = json.dumps(outcome["result"], indent=2)
            console.print(
                Panel(
                    Syntax(result_json, "json", theme="monokai"),
                    title="[bold]Specialist findings[/bold]",
                    border_style="green",
                )
            )

        except NotImplementedError as exc:
            elapsed = time.perf_counter() - start
            console.print(
                Panel(
                    f"[yellow]{exc}[/yellow]",
                    title="[bold yellow]TODO — not yet implemented[/bold yellow]",
                    border_style="yellow",
                )
            )
        except Exception as exc:
            elapsed = time.perf_counter() - start
            console.print(f"[red]ERROR ({elapsed:.2f}s):[/red] {exc}")
            raise

    console.rule("[bold cyan]Done[/bold cyan]")


if __name__ == "__main__":
    main()
