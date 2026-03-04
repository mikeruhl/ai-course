"""
Module 11 Lab C — Agent Discovery
===================================
Simulate a multi-agent registry where an orchestrator discovers
available agents dynamically.

Tasks:
  1. Build a local agent registry (JSON file)
  2. Implement registry discovery (poll multiple servers for their cards)
  3. Implement LLM-based agent selection from the registry
  4. Demo: user query → discover agents → select best → submit task

Run with: uv run python src/a2a_discover.py
"""

import json
import os
import uuid

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# Known agent URLs for demo (would come from a service registry in production)
# ---------------------------------------------------------------------------
KNOWN_AGENT_URLS = [
    "http://localhost:8080",   # researcher-agent (Lab A)
    "http://localhost:8081",   # hypothetical summariser-agent
    "http://localhost:8082",   # hypothetical code-agent
]


# ---------------------------------------------------------------------------
# Task 1 & 2: Discovery
# ---------------------------------------------------------------------------

def discover_agent(url: str) -> dict | None:
    """
    Fetch the Agent Card from a single URL.
    Returns the card dict, or None if the server is unreachable.
    """
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{url.rstrip('/')}/.well-known/agent.json")
            resp.raise_for_status()
            card = resp.json()
            card["_discovered_url"] = url   # stash where we found it
            return card
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        return None


def discover_all_agents(urls: list[str]) -> list[dict]:
    """
    Poll every URL in the list and collect successful Agent Cards.
    Silently skips unreachable servers — in production you would log these.
    """
    agents: list[dict] = []
    for url in urls:
        console.print(f"  Probing [cyan]{url}[/cyan] … ", end="")
        card = discover_agent(url)
        if card:
            console.print(f"[green]found[/green] ({card.get('name', '?')})")
            agents.append(card)
        else:
            console.print("[dim]unreachable[/dim]")
    return agents


def print_agent_registry(agents: list[dict]) -> None:
    """Render discovered agents as a rich table."""
    table = Table(title="Discovered Agents", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Name", style="bold cyan")
    table.add_column("URL")
    table.add_column("Skills")
    table.add_column("Streaming")

    for i, card in enumerate(agents, start=1):
        skill_names = ", ".join(s["name"] for s in card.get("skills", []))
        streaming = str(card.get("capabilities", {}).get("streaming", False))
        table.add_row(
            str(i),
            card.get("name", "—"),
            card.get("_discovered_url", "—"),
            skill_names or "—",
            streaming,
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Task 3: LLM-based agent selection
# ---------------------------------------------------------------------------

def select_agent_for_task(agents: list[dict], task_description: str) -> dict:
    """
    Task 3: Use Azure OpenAI to pick the best agent for the task.

    Given a list of Agent Cards and a task description, ask an LLM which
    agent is most suited.  Return the selected agent card.

    Implementation notes:
      - Build a prompt that includes each agent's name, description, and skills.
      - Ask the LLM to respond with just the agent name.
      - Match the response back to the agents list.
      - Fall back to agents[0] if parsing fails.

    Hint — raw REST call to Azure OpenAI:
      endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
      deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
      api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
      url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    """
    raise NotImplementedError("Task 3: implement LLM-based agent selection")


# ---------------------------------------------------------------------------
# Task 4: End-to-end demo
# ---------------------------------------------------------------------------

def submit_task_to_agent(agent_card: dict, input_text: str) -> dict:
    """
    Submit a task to the selected agent's /tasks/send endpoint.
    Uses the URL stashed in _discovered_url during discovery.
    """
    server_url = agent_card.get("_discovered_url", agent_card.get("url", ""))
    url = f"{server_url.rstrip('/')}/tasks/send"
    payload = {
        "id": str(uuid.uuid4()),
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": input_text}],
        },
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def main() -> None:
    console.rule("[bold]Module 11 Lab C — Agent Discovery[/bold]")

    # Step 1 & 2: Discover all reachable agents
    console.print("\n[bold]Step 1: Discovering agents...[/bold]")
    agents = discover_all_agents(KNOWN_AGENT_URLS)

    if not agents:
        console.print("[red]No agents discovered. Start at least one server:[/red]")
        console.print("  uv run python src/a2a_server.py")
        return

    print_agent_registry(agents)

    # Step 3: Select best agent for a sample task
    task_description = "I need to answer a detailed research question about transformer architectures."
    console.print(f"\n[bold]Step 3: Selecting agent for task:[/bold] [italic]{task_description}[/italic]")

    try:
        selected = select_agent_for_task(agents, task_description)
        console.print(f"Selected: [bold green]{selected.get('name')}[/bold green]")
    except NotImplementedError as exc:
        console.print(f"[yellow]Skipping (not yet implemented): {exc}[/yellow]")
        # Fall back to first discovered agent for demo purposes
        selected = agents[0]
        console.print(f"Falling back to first discovered agent: [cyan]{selected.get('name')}[/cyan]")

    # Step 4: Submit a real task to the selected agent
    query = "What is the difference between attention and self-attention in transformers?"
    console.print(f"\n[bold]Step 4: Submitting task to {selected.get('name')}[/bold]")
    console.print(f"Query: [italic]{query}[/italic]")

    try:
        result = submit_task_to_agent(selected, query)
        status = result.get("status", "unknown")
        color = {"completed": "green", "failed": "red"}.get(status, "yellow")
        console.print(f"Status: [{color}]{status}[/{color}]")
        if result.get("output"):
            console.print(f"\n[bold]Result:[/bold]\n{result['output']}")
        elif result.get("error"):
            console.print(f"[red]Error:[/red] {result['error']}")
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Task failed: {exc.response.status_code}[/red]")
    except httpx.ConnectError:
        console.print("[red]Lost connection to agent during task submission.[/red]")


if __name__ == "__main__":
    main()
