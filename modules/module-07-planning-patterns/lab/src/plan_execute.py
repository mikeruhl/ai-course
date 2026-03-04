"""
Module 07 — Task 1: Plan-and-Execute Agent
==========================================
Two-agent system: Planner creates the plan, Executor runs each step.
The Planner can revise remaining steps after each execution.

Run with:
    uv run python src/plan_execute.py
"""

import json
import os

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

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

console = Console()


# ---------------------------------------------------------------------------
# Simulated tools for the executor
# ---------------------------------------------------------------------------

RESEARCH_DB = {
    "wwi causes": (
        "WWI causes include: nationalism (especially in the Balkans), the system of "
        "interlocking alliances, militarism and the arms race, and imperialist competition "
        "for colonies. The MAIN acronym is commonly used."
    ),
    "wwi assassination": (
        "The assassination of Archduke Franz Ferdinand in Sarajevo on 28 June 1914 by "
        "Gavrilo Princip was the immediate trigger. This set off the July Crisis — a "
        "chain of mobilizations driven by alliance obligations."
    ),
    "wwi alliances": (
        "Two main alliances: the Triple Entente (France, Russia, Britain) and the Triple "
        "Alliance (Germany, Austria-Hungary, Italy). When Austria-Hungary declared war on "
        "Serbia, Russia mobilized, pulling in Germany, then France, then Britain."
    ),
    "wwi nationalism": (
        "Pan-Slavic nationalism in the Balkans threatened Austria-Hungary's multi-ethnic "
        "empire. Pan-German nationalism drove German expansionism. Serbian nationalism "
        "motivated Princip. Nationalism made European leaders willing to go to war."
    ),
    "wwi militarism": (
        "European powers engaged in a major arms race from 1870–1914. Germany and Britain "
        "competed in naval buildup (Dreadnought race). Military planning (Schlieffen Plan) "
        "created rigid mobilization schedules that left little room for diplomacy."
    ),
}

written_sections: dict[str, str] = {}


def tool_search(query: str) -> str:
    """Simulated research tool."""
    key = query.lower()
    for k, v in RESEARCH_DB.items():
        if k in key or any(word in key for word in k.split()):
            return v
    return f"No research found for '{query}'."


def tool_write_section(title: str, content: str) -> str:
    """Store a written section."""
    written_sections[title] = content
    return f"Section '{title}' written ({len(content)} characters)."


EXECUTOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search for information on a topic to use in the report.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_section",
            "description": "Write and save a report section with a title and content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Section heading"},
                    "content": {"type": "string", "description": "Section body text"},
                },
                "required": ["title", "content"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Planner Agent
# ---------------------------------------------------------------------------

PLANNER_SYSTEM = """You are a planning agent. Your job is to create clear, numbered, sequential plans.

When creating a plan:
- Break the goal into concrete, actionable steps
- Each step should be executable by an agent with search and write tools
- Include at least one research step before each writing step
- End with an assembly or review step

Output ONLY a JSON array of step strings. No other text.
Example: ["Step 1: Search for X", "Step 2: Search for Y", "Step 3: Write introduction using X and Y"]
"""

REVISE_PLANNER_SYSTEM = """You are a planning agent reviewing a plan in progress.

Given:
- The original plan
- Steps completed so far with their results
- The remaining steps

Decide: should the remaining steps be revised based on what was learned?

Output ONLY a JSON array of the REMAINING steps (revised if needed).
If no revision is needed, output the same remaining steps unchanged.
"""


class PlannerAgent:

    def create_plan(self, goal: str) -> list[str]:
        """
        Call the model to create a numbered plan for the goal.
        Returns a list of step strings.
        """
        # TODO (Task 1): Call the model with PLANNER_SYSTEM + the goal.
        # Parse the response as JSON (the model outputs a JSON array).
        # Return the list of step strings.
        # Handle JSON parsing errors: if the model doesn't output valid JSON,
        # log a warning and return a fallback 3-step plan.
        raise NotImplementedError("TODO: implement PlannerAgent.create_plan()")

    def revise_plan(
        self,
        original_plan: list[str],
        completed_steps: list[tuple[str, str]],  # (step, result)
        remaining_steps: list[str],
    ) -> list[str]:
        """
        Review completed work and optionally revise remaining steps.
        Returns the (possibly updated) remaining steps.
        """
        if not remaining_steps:
            return []

        # TODO (Task 1): Build a prompt that shows:
        # - The original plan (numbered)
        # - Completed steps with their results (step + first 200 chars of result)
        # - The remaining steps
        # Ask the model: given what we learned, should remaining steps change?
        # Parse the response as JSON (list of remaining step strings).
        # If parsing fails, return remaining_steps unchanged.
        raise NotImplementedError("TODO: implement PlannerAgent.revise_plan()")


# ---------------------------------------------------------------------------
# Executor Agent
# ---------------------------------------------------------------------------

EXECUTOR_SYSTEM = """You are an execution agent. You are given one task step to complete.
Use your tools to complete ONLY the given step. Do not do more than what the step asks.
After using tools, summarize what you accomplished in 1-2 sentences.
"""


class ExecutorAgent:

    def execute_step(self, step: str, context: str = "") -> str:
        """
        Execute a single plan step using available tools.
        Returns a summary of what was accomplished.

        Args:
            step:    The step description from the planner
            context: Optional context from prior steps (accumulated observations)
        """
        user_content = f"Complete this step: {step}"
        if context:
            user_content += f"\n\nContext from previous steps:\n{context}"

        messages = [
            {"role": "system", "content": EXECUTOR_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        # TODO (Task 1): Implement the executor's tool loop.
        # - Call the model with EXECUTOR_TOOLS
        # - If finish_reason == "tool_calls": execute the tools
        #   (dispatch to tool_search or tool_write_section based on name)
        # - Append tool results and loop
        # - When finish_reason == "stop": return the final content
        # - Max 5 iterations for a single step
        raise NotImplementedError("TODO: implement ExecutorAgent.execute_step()")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_plan_execute(goal: str) -> dict[str, str]:
    """
    Run the Plan-and-Execute loop.

    Returns the dict of written sections (from tool_write_section calls).
    """
    console.print(Panel(f"[bold blue]Plan-and-Execute[/bold blue]\nGoal: {goal}"))

    planner = PlannerAgent()
    executor = ExecutorAgent()

    # Phase 1: Create initial plan
    console.print("\n[bold yellow]Phase 1: Planning[/bold yellow]")
    plan = planner.create_plan(goal)

    console.print("[bold]Initial Plan:[/bold]")
    for i, step in enumerate(plan, 1):
        console.print(f"  {i}. {step}")

    completed: list[tuple[str, str]] = []  # (step, result)
    accumulated_context = ""
    revised_count = 0

    # Phase 2: Execute steps with optional re-planning
    console.print("\n[bold yellow]Phase 2: Execution[/bold yellow]")

    remaining = list(plan)
    step_num = 0

    while remaining:
        step = remaining.pop(0)
        step_num += 1

        console.print(f"\n[cyan]Executing step {step_num}:[/cyan] {step}")

        # TODO (Task 1): Call executor.execute_step(step, accumulated_context)
        # Append (step, result) to completed.
        # Add result to accumulated_context.
        result = "TODO: call executor.execute_step()"
        completed.append((step, result))
        accumulated_context += f"\nStep {step_num} ({step}): {result[:300]}"

        console.print(f"[green]Result:[/green] {result[:200]}...")

        # Re-plan every 2 steps if there are remaining steps
        if step_num % 2 == 0 and remaining:
            console.print("[dim]Checking if plan needs revision...[/dim]")
            # TODO (Task 1): Call planner.revise_plan(plan, completed, remaining)
            # If the returned plan differs from remaining, print "Plan revised"
            # and show the changes. Update remaining to the new plan.
            pass

    # Phase 3: Summary
    console.print(Rule("[bold yellow]Phase 3: Results[/bold yellow]"))
    console.print(f"[bold]Written sections ({len(written_sections)}):[/bold]")
    for title, content in written_sections.items():
        console.print(Panel(content[:300] + "...", title=title))

    console.print(f"\n[dim]Total steps executed: {step_num}[/dim]")
    console.print(f"[dim]Plan revisions: {revised_count}[/dim]")

    return written_sections


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def chat(messages, temperature=0, max_tokens=800) -> dict:
    payload = {"model": MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    r = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def chat_with_tools(messages, tools, temperature=0, max_tokens=600) -> dict:
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
    goal = (
        "Research and outline a 3-section report on the causes of World War I. "
        "Sections: Underlying Causes, The Assassination, The Alliance Cascade."
    )
    sections = run_plan_execute(goal)
    console.print(f"\n[bold green]Document complete — {len(sections)} sections written.[/bold green]")
