"""
Module 10 Lab C — Peer-to-Peer Debate
======================================
Two advocate agents debate a technical topic. A judge decides the winner.

Tasks:
  1. Implement advocate_for() and advocate_against()
  2. Run 3 rounds of debate (opening, rebuttal, closing)
  3. Implement the judge agent
  4. Print formatted debate transcript
  5. Test with: message queue vs direct HTTP calls decision

Run with: uv run python src/peer_debate.py
"""

from __future__ import annotations

import os
import time

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

# Debate configuration
TOTAL_ROUNDS = 3
ROUND_NAMES = {1: "Opening Statement", 2: "Rebuttal", 3: "Closing Argument"}


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict]) -> str:
    """
    Call Azure OpenAI synchronously via raw httpx POST.

    Args:
        messages: List of {"role": ..., "content": ...} dicts.

    Returns:
        The assistant message content as a plain string.

    Raises:
        RuntimeError: If the API returns a non-2xx status.
    """
    if not ENDPOINT or not API_KEY:
        raise RuntimeError(
            "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY must be set in your .env file."
        )

    body = {"messages": messages, "temperature": 0.7}
    response = httpx.post(BASE_URL, headers=HEADERS, json=body, timeout=60.0)

    if response.status_code != 200:
        raise RuntimeError(
            f"Azure OpenAI returned {response.status_code}: {response.text}"
        )

    return response.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Advocate agents
# ---------------------------------------------------------------------------

def advocate_for(
    position: str,
    context: str,
    round_num: int,
    opponent_arg: str | None,
) -> str:
    """
    Generate an argument in FAVOUR of the position.

    TODO (Task 1): This function is implemented. Study the system prompt and
    consider whether the instructions should differ per round_num:
      - Round 1 (opening): establish the strongest positive case.
      - Round 2 (rebuttal): directly counter the opponent's specific points.
      - Round 3 (closing):  summarise and leave the judge with a memorable statement.
    Update the system prompt or user message to make each round feel distinct.

    Args:
        position:     The proposition being debated (e.g. "use message queues").
        context:      Background context about the decision being made.
        round_num:    1 = opening, 2 = rebuttal, 3 = closing.
        opponent_arg: The opponent's previous argument (None in round 1).

    Returns:
        A string containing the advocate's argument for this round.
    """
    round_label = ROUND_NAMES.get(round_num, f"Round {round_num}")

    # TODO (Task 1): Make the instructions round-specific. Right now all rounds
    # use the same generic instruction. Consider an if/elif block on round_num.
    system_prompt = (
        f"You are a skilled technical advocate arguing IN FAVOUR of: '{position}'. "
        f"You are in a structured debate — this is your {round_label}. "
        "Make clear, concrete technical arguments. Be persuasive but factually accurate. "
        "Keep your argument to 3-5 sentences."
    )

    user_parts = [f"Context: {context}"]
    if opponent_arg:
        user_parts.append(f"\nOpponent's previous argument:\n{opponent_arg}")
    user_parts.append(f"\nNow deliver your {round_label} argument FOR the position.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
    return call_llm(messages)


def advocate_against(
    position: str,
    context: str,
    round_num: int,
    opponent_arg: str | None,
) -> str:
    """
    Generate an argument AGAINST the position.

    TODO (Task 1): Same improvement opportunity as advocate_for — make each
    round's prompt distinctly suited to opening, rebuttal, or closing strategy.

    Args:
        position:     The proposition being debated.
        context:      Background context about the decision being made.
        round_num:    1 = opening, 2 = rebuttal, 3 = closing.
        opponent_arg: The opponent's previous argument (None in round 1).

    Returns:
        A string containing the advocate's argument against the position for this round.
    """
    round_label = ROUND_NAMES.get(round_num, f"Round {round_num}")

    # TODO (Task 1): Make the instructions round-specific.
    system_prompt = (
        f"You are a skilled technical advocate arguing AGAINST: '{position}'. "
        f"You are in a structured debate — this is your {round_label}. "
        "Make clear, concrete technical arguments. Be persuasive but factually accurate. "
        "Keep your argument to 3-5 sentences."
    )

    user_parts = [f"Context: {context}"]
    if opponent_arg:
        user_parts.append(f"\nOpponent's previous argument:\n{opponent_arg}")
    user_parts.append(f"\nNow deliver your {round_label} argument AGAINST the position.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
    return call_llm(messages)


# ---------------------------------------------------------------------------
# Judge agent
# ---------------------------------------------------------------------------

def judge_agent(position: str, debate_transcript: list[dict]) -> dict:
    """
    Evaluate the debate and declare a winner.

    TODO (Task 3): The judge currently receives the full transcript as plain text.
    Consider whether the judge should weigh later rounds more heavily (closer to
    the final decision). You could instruct the judge to explicitly state which
    round was the most decisive.

    Args:
        position:         The proposition that was debated.
        debate_transcript: List of round dicts, each with keys:
                           {"round": int, "for": str, "against": str}

    Returns:
        dict with keys:
            winner (str):      "for" | "against" | "tie"
            reason (str):      Explanation of the verdict.
            key_points (list): 2-4 decisive points the judge identified.
    """
    # Format the transcript for the judge.
    transcript_text = ""
    for entry in debate_transcript:
        round_label = ROUND_NAMES.get(entry["round"], f"Round {entry['round']}")
        transcript_text += (
            f"\n--- {round_label} ---\n"
            f"FOR: {entry['for']}\n\n"
            f"AGAINST: {entry['against']}\n"
        )

    system_prompt = (
        "You are an impartial expert judge evaluating a technical debate. "
        "Assess the arguments on their technical merit, clarity, and persuasiveness. "
        "Respond ONLY with valid JSON:\n"
        '{"winner": "for|against|tie", "reason": "<2-3 sentence verdict>", '
        '"key_points": ["<point1>", "<point2>", ...]}'
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Proposition: '{position}'\n\n"
                f"Full debate transcript:\n{transcript_text}\n\n"
                "Deliver your verdict."
            ),
        },
    ]

    import json
    raw = call_llm(messages)
    # Strip markdown fences if the model wraps the JSON.
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ---------------------------------------------------------------------------
# Debate runner
# ---------------------------------------------------------------------------

def run_debate(position: str, context: str) -> dict:
    """
    Run a full structured debate over TOTAL_ROUNDS rounds.

    TODO (Task 2): This function is fully implemented. After completing Tasks 1
    and 3, extend run_debate to accept a custom number of rounds via a parameter,
    defaulting to TOTAL_ROUNDS = 3.

    Args:
        position: The proposition to debate.
        context:  Background context for both advocates.

    Returns:
        dict with keys:
            rounds (list[dict]): Each round's arguments.
            verdict (dict):      Judge's decision.
    """
    rounds: list[dict] = []
    last_for_arg: str | None = None
    last_against_arg: str | None = None

    for round_num in range(1, TOTAL_ROUNDS + 1):
        console.log(
            f"[cyan]Round {round_num}:[/cyan] {ROUND_NAMES.get(round_num, f'Round {round_num}')}"
        )

        # FOR advocate sees the most recent AGAINST argument as "opponent".
        for_arg = advocate_for(
            position=position,
            context=context,
            round_num=round_num,
            opponent_arg=last_against_arg,
        )

        # AGAINST advocate sees the FOR argument from this same round.
        against_arg = advocate_against(
            position=position,
            context=context,
            round_num=round_num,
            opponent_arg=for_arg,
        )

        rounds.append({"round": round_num, "for": for_arg, "against": against_arg})
        last_for_arg = for_arg
        last_against_arg = against_arg

    console.log("[cyan]Requesting verdict from judge...[/cyan]")
    verdict = judge_agent(position=position, debate_transcript=rounds)

    return {"rounds": rounds, "verdict": verdict}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    console.rule("[bold cyan]Module 10 Lab C — Peer-to-Peer Debate[/bold cyan]")

    position = "Services should communicate via a message queue rather than direct HTTP calls"
    context = (
        "We are designing a new microservices backend for an e-commerce platform. "
        "The team is split on whether inter-service communication should use an async "
        "message queue (e.g., Azure Service Bus) or synchronous HTTP REST calls. "
        "The system must handle 10,000 orders/hour at peak with <500ms p99 latency."
    )

    console.print(
        Panel(
            f"[bold]Proposition:[/bold] {position}\n\n[dim]{context}[/dim]",
            title="Debate Setup",
            border_style="cyan",
        )
    )

    start = time.perf_counter()
    result = run_debate(position=position, context=context)
    elapsed = time.perf_counter() - start

    # Print each round as a panel pair.
    for entry in result["rounds"]:
        round_num = entry["round"]
        round_label = ROUND_NAMES.get(round_num, f"Round {round_num}")

        console.print(f"\n[bold yellow]Round {round_num}: {round_label}[/bold yellow]")
        console.print(
            Panel(
                entry["for"],
                title="[bold green]FOR[/bold green]",
                border_style="green",
                padding=(0, 1),
            )
        )
        console.print(
            Panel(
                entry["against"],
                title="[bold red]AGAINST[/bold red]",
                border_style="red",
                padding=(0, 1),
            )
        )

    # Verdict
    verdict = result["verdict"]
    winner_label = {
        "for": "[bold green]FOR wins[/bold green]",
        "against": "[bold red]AGAINST wins[/bold red]",
        "tie": "[bold yellow]TIE[/bold yellow]",
    }.get(verdict.get("winner", "tie"), "[bold]Unknown[/bold]")

    verdict_table = Table(show_header=False, box=None, padding=(0, 1))
    verdict_table.add_row("Verdict", winner_label)
    verdict_table.add_row("Reason", verdict.get("reason", ""))

    key_points = verdict.get("key_points", [])
    if key_points:
        verdict_table.add_row("Key points", "\n".join(f"• {p}" for p in key_points))

    console.print(
        Panel(
            verdict_table,
            title="[bold]Judge's Verdict[/bold]",
            border_style="magenta",
            padding=(1, 2),
        )
    )

    console.print(f"\n[dim]Total debate time: {elapsed:.1f}s[/dim]")
    console.rule("[bold cyan]Done[/bold cyan]")


if __name__ == "__main__":
    main()
