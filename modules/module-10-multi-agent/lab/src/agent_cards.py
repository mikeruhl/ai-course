"""
Module 10 Lab D — Agent Cards (Data-Driven Routing)
====================================================
Replace hardcoded routing with Agent Cards loaded from JSON files.

Tasks:
  1. Create 3 Agent Card JSON files in cards/ directory
     (already created: code_reviewer.json, security_analyst.json, performance_advisor.json)
  2. Implement CardRegistry.find_best_match() using LLM-based matching
  3. Refactor orchestrator to use card-based routing
  4. Add a new specialist (architecture_reviewer.json) WITHOUT changing orchestrator code

Run with: uv run python src/agent_cards.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

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

# Resolve the cards directory relative to this file so the script works
# from any working directory.
CARDS_DIR = Path(__file__).parent / "cards"


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict], response_format: dict | None = None) -> str:
    """
    Call Azure OpenAI synchronously via raw httpx POST.

    Args:
        messages:        List of {"role": ..., "content": ...} dicts.
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

    body: dict = {"messages": messages, "temperature": 0.1}
    if response_format:
        body["response_format"] = response_format

    response = httpx.post(BASE_URL, headers=HEADERS, json=body, timeout=60.0)

    if response.status_code != 200:
        raise RuntimeError(
            f"Azure OpenAI returned {response.status_code}: {response.text}"
        )

    return response.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# CardRegistry
# ---------------------------------------------------------------------------

class CardRegistry:
    """
    Load and query Agent Cards from a directory of JSON files.

    Each JSON file in the cards directory is treated as one agent card.
    The card's "name" field is used as the agent identifier.

    Usage:
        registry = CardRegistry(str(CARDS_DIR))
        names = registry.list_agents()
        card  = registry.get_card("code_reviewer")
        best  = registry.find_best_match("Is this SQL vulnerable to injection?")
    """

    def __init__(self, cards_dir: str) -> None:
        """
        Load all *.json card files from cards_dir.

        Args:
            cards_dir: Path to the directory containing card JSON files.

        Raises:
            FileNotFoundError: If cards_dir does not exist.
            ValueError: If any card file is missing a "name" field.
        """
        self._dir = Path(cards_dir)
        if not self._dir.exists():
            raise FileNotFoundError(f"Cards directory not found: {self._dir}")

        self._cards: dict[str, dict] = {}
        for card_path in sorted(self._dir.glob("*.json")):
            with card_path.open(encoding="utf-8") as fh:
                card = json.load(fh)
            name = card.get("name")
            if not name:
                raise ValueError(
                    f"Card file '{card_path.name}' is missing a 'name' field."
                )
            self._cards[name] = card

        console.log(
            f"[green]CardRegistry loaded {len(self._cards)} card(s):[/green] "
            + ", ".join(self._cards.keys())
        )

    def list_agents(self) -> list[str]:
        """Return names of all registered agents in alphabetical order."""
        return sorted(self._cards.keys())

    def get_card(self, name: str) -> dict:
        """
        Retrieve a specific agent card by name.

        Args:
            name: The agent name (must match the card's "name" field).

        Returns:
            The full card dict.

        Raises:
            KeyError: If no card with that name is registered.
        """
        if name not in self._cards:
            raise KeyError(
                f"No agent card named '{name}'. "
                f"Available agents: {self.list_agents()}"
            )
        return self._cards[name]

    def find_best_match(self, query: str) -> str:
        """
        Use the LLM to select the most appropriate agent for a given query.

        The LLM receives a summary of every registered agent (name + description)
        and returns the name of the best match. This means adding a new card JSON
        file automatically makes a new agent available for routing — no code changes
        required.

        TODO (Task 2): Implement this method. Follow these steps:
          a. Build a summary string listing each agent's name and description.
             Example format:
               - code_reviewer: Reviews source code for quality ...
               - security_analyst: Analyses code for vulnerabilities ...
          b. Call call_llm() with a system prompt instructing the LLM to respond
             ONLY with the agent name (no JSON, no explanation) that best matches
             the query.
          c. Strip whitespace from the response and validate it is in list_agents().
          d. Return the matched agent name.

        Args:
            query: The user's question or task description.

        Returns:
            The name of the best-matching agent (must be in list_agents()).

        Raises:
            NotImplementedError: Until Task 2 is complete.
            ValueError:          If the LLM returns an unknown agent name.
        """
        # TODO (Task 2): Replace this NotImplementedError with your implementation.
        # Hint: build `agent_descriptions` like:
        #   agent_descriptions = "\n".join(
        #       f"- {name}: {self._cards[name]['description']}"
        #       for name in self.list_agents()
        #   )
        # Then craft a prompt and call call_llm().
        raise NotImplementedError(
            "Task 2: Implement find_best_match().\n"
            "  a. Build a list of agent names + descriptions from self._cards.\n"
            "  b. Ask the LLM which agent name best fits the query.\n"
            "  c. Validate the returned name is in self.list_agents().\n"
            "  d. Return the matched name.\n"
            "See the docstring above for full details."
        )

    def describe_all(self) -> None:
        """Pretty-print all registered cards to the console."""
        for name, card in self._cards.items():
            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_row("[cyan]Name[/cyan]", card.get("name", name))
            table.add_row("[cyan]Description[/cyan]", card.get("description", ""))
            table.add_row("[cyan]Cost tier[/cyan]", card.get("cost_tier", "unknown"))
            skills = card.get("skills", [])
            table.add_row("[cyan]Skills[/cyan]", ", ".join(skills))
            console.print(
                Panel(table, title=f"[bold]{name}[/bold]", border_style="blue")
            )


# ---------------------------------------------------------------------------
# Demo queries
# ---------------------------------------------------------------------------

DEMO_QUERIES = [
    "Is there a SQL injection vulnerability in this database access code?",
    "This nested loop is taking 30 seconds to process 10,000 items.",
    "Can you review this function for readability and naming?",
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    console.rule("[bold cyan]Module 10 Lab D — Agent Cards (Data-Driven Routing)[/bold cyan]")

    # Step 1: Load registry and show all cards.
    console.print("\n[bold]Step 1: Load registry and display all registered agent cards[/bold]")
    registry = CardRegistry(str(CARDS_DIR))
    registry.describe_all()

    # Step 2: Show agent list.
    console.print("\n[bold]Step 2: List all registered agent names[/bold]")
    agents = registry.list_agents()
    console.print(f"  Agents: {agents}")

    # Step 3: find_best_match for demo queries.
    console.print("\n[bold]Step 3: Route demo queries via find_best_match()[/bold]")
    results_table = Table(title="Routing Results", show_lines=True)
    results_table.add_column("Query", max_width=50)
    results_table.add_column("Best match", style="bold green")

    for query in DEMO_QUERIES:
        try:
            best = registry.find_best_match(query)
            results_table.add_row(query, best)
        except NotImplementedError as exc:
            results_table.add_row(
                query,
                f"[yellow]TODO: {exc.args[0].splitlines()[0]}[/yellow]",
            )
        except ValueError as exc:
            results_table.add_row(query, f"[red]Error: {exc}[/red]")

    console.print(results_table)

    # Step 4: Explain extensibility.
    console.print(
        Panel(
            "[bold]Task 4 — How to add a new specialist without changing orchestrator code:[/bold]\n\n"
            "1. Create [cyan]src/cards/architecture_reviewer.json[/cyan] with the same schema\n"
            "   (name, description, skills, input_schema, output_schema, cost_tier).\n\n"
            "2. That's it. CardRegistry.find_best_match() passes ALL card descriptions\n"
            "   to the LLM, so the new card is automatically considered for routing.\n\n"
            "3. The orchestrator code never needs to change — it just calls\n"
            "   registry.find_best_match(query) and receives a name.\n\n"
            "[dim]This is the power of data-driven routing: the routing policy lives in\n"
            "JSON files, not in if/elif chains buried in orchestrator code.[/dim]",
            title="Extensibility Demo",
            border_style="magenta",
        )
    )

    console.rule("[bold cyan]Done[/bold cyan]")


if __name__ == "__main__":
    main()
