"""
Module 10 Lab B — Handoff Chain (Swarm Pattern)
================================================
3-stage pipeline: planner → researcher → writer
Each agent hands off a shared context dict to the next.

Tasks:
  1. Implement the context schema validation
  2. Implement each agent (planner, researcher, writer)
  3. Build the pipeline runner with stage validation
  4. Add HandoffError for missing required context keys
  5. Test with a technical blog post task

Run with: uv run python src/handoff_chain.py
"""

from __future__ import annotations

import os
import time
from typing import TypedDict

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
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

BASE_URL = (
    f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions"
    f"?api-version={API_VERSION}"
)

HEADERS = {
    "Content-Type": "application/json",
    "api-key": API_KEY,
}


# ---------------------------------------------------------------------------
# Shared context schema
# ---------------------------------------------------------------------------

class AgentMetadata(TypedDict):
    agents_run: list[str]          # names of agents that have executed
    token_usage: dict[str, int]    # agent_name -> tokens consumed
    start_time: float              # pipeline start epoch time


class AgentContext(TypedDict):
    task: str                      # original task description (set by caller)
    plan: str | None               # output of planner_agent
    research: str | None           # output of researcher_agent
    draft: str | None              # output of writer_agent
    metadata: AgentMetadata


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class HandoffError(Exception):
    """
    Raised when a required context key is missing or None before an agent runs.

    Attributes:
        missing_keys: List of context keys that were absent.
        agent: The agent that detected the missing keys.
    """

    def __init__(self, missing_keys: list[str], agent: str) -> None:
        self.missing_keys = missing_keys
        self.agent = agent
        super().__init__(
            f"Handoff to '{agent}' failed — required context keys are missing or None: "
            + ", ".join(missing_keys)
        )


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict], agent_name: str, ctx: AgentContext) -> str:
    """
    Call Azure OpenAI synchronously and record token usage in the context.

    Args:
        messages:   List of {"role": ..., "content": ...} dicts.
        agent_name: Name of the calling agent (used for telemetry).
        ctx:        Shared pipeline context (token_usage updated in-place).

    Returns:
        The assistant message content as a plain string.

    Raises:
        RuntimeError: If the API returns a non-2xx status.
    """
    if not ENDPOINT or not API_KEY:
        raise RuntimeError(
            "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY must be set in your .env file."
        )

    body = {"messages": messages, "temperature": 0.4}
    response = httpx.post(BASE_URL, headers=HEADERS, json=body, timeout=120.0)

    if response.status_code != 200:
        raise RuntimeError(
            f"Azure OpenAI returned {response.status_code}: {response.text}"
        )

    data = response.json()
    tokens = data.get("usage", {}).get("total_tokens", 0)
    ctx["metadata"]["token_usage"][agent_name] = (
        ctx["metadata"]["token_usage"].get(agent_name, 0) + tokens
    )

    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Context validation
# ---------------------------------------------------------------------------

def validate_context(ctx: AgentContext, required_keys: list[str], agent: str) -> None:
    """
    Assert that every key in required_keys is present and non-None in ctx.

    TODO (Task 1): This function is fully implemented. Study how it integrates
    with the pipeline in run_pipeline() and consider edge cases:
      - What if a value is an empty string? Should that also be rejected?
      - Extend the check to raise HandoffError for falsy values if you think that is safer.

    Args:
        ctx:           The shared agent context.
        required_keys: Keys that must be present and non-None.
        agent:         Name of the agent about to run (used in the error message).

    Raises:
        HandoffError: If any required key is missing or None.
    """
    missing = [k for k in required_keys if ctx.get(k) is None]  # type: ignore[call-overload]
    if missing:
        raise HandoffError(missing_keys=missing, agent=agent)


# ---------------------------------------------------------------------------
# Pipeline agents
# ---------------------------------------------------------------------------

def planner_agent(ctx: AgentContext) -> None:
    """
    Stage 1 — Create a numbered plan for the task.

    Reads:  ctx["task"]
    Writes: ctx["plan"]
    Appends "planner" to ctx["metadata"]["agents_run"].

    The plan must be a clear, ordered list of steps the researcher can follow.
    """
    validate_context(ctx, required_keys=["task"], agent="planner")

    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior technical writer and planner. "
                "Given a writing task, produce a numbered outline with 4-6 main sections. "
                "Each section should have a one-sentence description of what it covers. "
                "Output plain text — no markdown fences."
            ),
        },
        {
            "role": "user",
            "content": f"Create a detailed outline for the following task:\n\n{ctx['task']}",
        },
    ]

    ctx["plan"] = call_llm(messages, agent_name="planner", ctx=ctx)
    ctx["metadata"]["agents_run"].append("planner")


def researcher_agent(ctx: AgentContext) -> None:
    """
    Stage 2 — Research each point in the plan and gather supporting content.

    Reads:  ctx["task"], ctx["plan"]
    Writes: ctx["research"]
    Appends "researcher" to ctx["metadata"]["agents_run"].

    TODO (Task 2): The system prompt below is generic. Improve it by:
      - Instructing the model to cite concrete technical details and examples.
      - Asking it to flag any points where it is uncertain so the writer can caveat them.
      - Specifying the target audience (e.g., senior engineers familiar with Python).
    """
    validate_context(ctx, required_keys=["task", "plan"], agent="researcher")

    # TODO (Task 2): Enhance this system prompt — see docstring above.
    messages = [
        {
            "role": "system",
            "content": (
                "You are a technical researcher. Given a plan, expand each section "
                "with relevant facts, examples, and explanations. "
                "Structure your research matching the plan's section order."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task: {ctx['task']}\n\n"
                f"Outline to research:\n{ctx['plan']}"
            ),
        },
    ]

    ctx["research"] = call_llm(messages, agent_name="researcher", ctx=ctx)
    ctx["metadata"]["agents_run"].append("researcher")


def writer_agent(ctx: AgentContext) -> None:
    """
    Stage 3 — Write the final polished draft from the plan and research.

    Reads:  ctx["task"], ctx["plan"], ctx["research"]
    Writes: ctx["draft"]
    Appends "writer" to ctx["metadata"]["agents_run"].
    """
    validate_context(ctx, required_keys=["task", "plan", "research"], agent="writer")

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert technical blog writer. "
                "Using the provided outline and research notes, write a polished, "
                "engaging blog post aimed at senior software engineers. "
                "Use clear headings, short paragraphs, and concrete code examples where helpful. "
                "Aim for approximately 800-1000 words."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task: {ctx['task']}\n\n"
                f"Outline:\n{ctx['plan']}\n\n"
                f"Research notes:\n{ctx['research']}"
            ),
        },
    ]

    ctx["draft"] = call_llm(messages, agent_name="writer", ctx=ctx)
    ctx["metadata"]["agents_run"].append("writer")


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(task: str) -> AgentContext:
    """
    Execute the three-stage handoff pipeline for a given task.

    TODO (Task 3): The pipeline currently runs stages unconditionally.
    Add a progress display using rich.progress so the student can see
    which stage is running in real time.

    Args:
        task: The top-level writing task description.

    Returns:
        Completed AgentContext with plan, research, and draft filled in.

    Raises:
        HandoffError: If a required context key is missing at any stage boundary.
    """
    ctx: AgentContext = {
        "task": task,
        "plan": None,
        "research": None,
        "draft": None,
        "metadata": {
            "agents_run": [],
            "token_usage": {},
            "start_time": time.time(),
        },
    }

    stages = [
        ("planner", planner_agent),
        ("researcher", researcher_agent),
        ("writer", writer_agent),
    ]

    for stage_name, stage_fn in stages:
        console.log(f"[cyan]Running stage:[/cyan] [bold]{stage_name}[/bold]")
        stage_fn(ctx)
        console.log(
            f"[green]Stage complete:[/green] {stage_name} "
            f"(tokens so far: {sum(ctx['metadata']['token_usage'].values())})"
        )

    return ctx


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    console.rule("[bold cyan]Module 10 Lab B — Handoff Chain (Swarm Pattern)[/bold cyan]")

    task = (
        "Write a technical blog post explaining why Python's GIL is being removed "
        "and what it means for async code."
    )

    console.print(Panel(task, title="[bold]Task[/bold]", border_style="cyan"))

    try:
        ctx = run_pipeline(task)
    except HandoffError as exc:
        console.print(f"[red]HandoffError:[/red] {exc}")
        return

    # Summary table
    total_elapsed = time.time() - ctx["metadata"]["start_time"]
    table = Table(title="Pipeline Summary", show_lines=True)
    table.add_column("Agent", style="bold cyan", no_wrap=True)
    table.add_column("Tokens", justify="right")
    table.add_column("Output preview", max_width=60)

    outputs = {
        "planner": ctx["plan"] or "",
        "researcher": ctx["research"] or "",
        "writer": ctx["draft"] or "",
    }

    for agent_name in ctx["metadata"]["agents_run"]:
        preview = (outputs[agent_name][:120] + "...") if len(outputs[agent_name]) > 120 else outputs[agent_name]
        tokens = ctx["metadata"]["token_usage"].get(agent_name, 0)
        table.add_row(agent_name, str(tokens), preview)

    console.print(table)
    console.print(f"\n[dim]Total elapsed: {total_elapsed:.1f}s | "
                  f"Total tokens: {sum(ctx['metadata']['token_usage'].values())}[/dim]")

    # Final draft
    console.print(
        Panel(
            ctx["draft"] or "(no draft produced)",
            title="[bold green]Final Draft[/bold green]",
            border_style="green",
            padding=(1, 2),
        )
    )

    console.rule("[bold cyan]Done[/bold cyan]")


if __name__ == "__main__":
    main()
