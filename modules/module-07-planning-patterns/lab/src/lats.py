"""
Module 07 — Task 3: 2-Level LATS (Language Agent Tree Search)
==============================================================
Simplified LATS: generate N candidate approaches, score each,
execute the best one.

This is a practical approximation of full LATS that gives most of the
benefit (avoiding obviously bad first choices) at a fraction of the cost.

Run with:
    uv run python src/lats.py
"""

import json
import os

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
# Phase 1: Generate candidate approaches
# ---------------------------------------------------------------------------

APPROACH_GENERATOR_SYSTEM = """You are a strategic problem-solving assistant.

Given a question, generate {n} DIFFERENT approaches to answering it.
The approaches should vary in their strategy — not just be rephrasing of each other.

For example, for a math word problem:
- Approach 1: Take the words literally and compute
- Approach 2: Look for tricks or ambiguities in the phrasing
- Approach 3: Draw a diagram or use a different representation

Output ONLY a JSON array of {n} approach strings. No other text.
Example: ["Approach 1: ...", "Approach 2: ...", "Approach 3: ..."]
"""


def generate_approaches(question: str, n: int = 3) -> list[str]:
    """
    Generate n different approaches to answering the question.
    Returns a list of approach description strings.
    """
    # TODO (Task 3): Call the model with APPROACH_GENERATOR_SYSTEM (formatted with n)
    # and the question as user content.
    # Parse the response as a JSON array of strings.
    # Return the list of approach strings.
    # If parsing fails, return a list of n generic fallback approaches.
    raise NotImplementedError("TODO: implement generate_approaches()")


# ---------------------------------------------------------------------------
# Phase 2: Score each approach
# ---------------------------------------------------------------------------

SCORER_SYSTEM = """You are an evaluator of problem-solving approaches.

Given a question and a proposed approach to answer it, rate the approach on a scale of 0-10.

Consider:
- Does the approach account for any tricks or edge cases in the question?
- Is it likely to lead to a correct answer?
- Is it appropriate for the type of question?

Output ONLY a JSON object with this exact format:
{"score": <integer 0-10>, "reason": "<one sentence explanation>"}
"""


def score_approach(question: str, approach: str) -> dict:
    """
    Score an approach for answering the question.
    Returns {"score": int, "reason": str}.
    """
    user_content = f"Question: {question}\n\nApproach: {approach}"

    # TODO (Task 3): Call the model with SCORER_SYSTEM and user_content.
    # Parse the response as JSON.
    # Return the dict with "score" and "reason".
    # If parsing fails, return {"score": 5, "reason": "Could not evaluate"}.
    raise NotImplementedError("TODO: implement score_approach()")


# ---------------------------------------------------------------------------
# Phase 3: Execute the selected approach
# ---------------------------------------------------------------------------

EXECUTOR_SYSTEM = """You are a careful problem solver.

You will be given a question and a specific approach to use when answering it.
Follow the approach exactly. Show your reasoning step by step, then give your final answer.
"""


def execute_approach(question: str, approach: str) -> str:
    """
    Execute the selected approach to answer the question.
    Returns the full answer with reasoning.
    """
    user_content = f"Question: {question}\n\nUse this approach: {approach}\n\nAnswer:"

    # TODO (Task 3): Call the model with EXECUTOR_SYSTEM and user_content.
    # Return the text content of the response.
    raise NotImplementedError("TODO: implement execute_approach()")


# ---------------------------------------------------------------------------
# LATS orchestrator
# ---------------------------------------------------------------------------

def run_lats(question: str, n_branches: int = 3) -> dict:
    """
    Run 2-level LATS:
    1. Generate n_branches candidate approaches
    2. Score all approaches
    3. Select the highest-scoring approach
    4. Execute it

    Returns:
    {
        "question": str,
        "approaches": [{"approach": str, "score": int, "reason": str}, ...],
        "selected_approach": str,
        "answer": str,
        "total_model_calls": int,
    }
    """
    console.print(Panel(
        f"[bold]LATS (2-level, {n_branches} branches)[/bold]\n\n{question}",
        title="Language Agent Tree Search"
    ))

    total_calls = 0

    # Phase 1: Generate approaches
    console.print(f"\n[bold yellow]Phase 1: Generating {n_branches} approaches...[/bold yellow]")
    # TODO (Task 3): Call generate_approaches(question, n_branches)
    approaches = ["TODO: approach 1", "TODO: approach 2", "TODO: approach 3"]
    total_calls += 1  # generation = 1 call

    for i, approach in enumerate(approaches, 1):
        console.print(f"  [cyan]{i}.[/cyan] {approach}")

    # Phase 2: Score all approaches
    console.print(f"\n[bold yellow]Phase 2: Scoring approaches...[/bold yellow]")
    scored = []
    for approach in approaches:
        # TODO (Task 3): Call score_approach(question, approach)
        result = {"score": 0, "reason": "TODO: score approach"}
        total_calls += 1  # each scoring = 1 call
        scored.append({
            "approach": approach,
            "score": result["score"],
            "reason": result["reason"],
        })
        console.print(
            f"  Score {result['score']}/10: {approach[:60]}... "
            f"— {result['reason']}"
        )

    # Display scoring table
    table = Table(title="Approach Scores")
    table.add_column("#", width=3)
    table.add_column("Score", width=6)
    table.add_column("Approach")
    table.add_column("Reason")

    for i, s in enumerate(scored, 1):
        score_color = "green" if s["score"] >= 7 else "yellow" if s["score"] >= 4 else "red"
        table.add_row(
            str(i),
            f"[{score_color}]{s['score']}/10[/{score_color}]",
            s["approach"][:60] + "...",
            s["reason"],
        )
    console.print(table)

    # Phase 3: Select best approach
    best = max(scored, key=lambda x: x["score"])
    console.print(
        f"\n[bold yellow]Phase 3: Selected approach (score {best['score']}/10):[/bold yellow] "
        f"{best['approach']}"
    )

    # Phase 4: Execute selected approach
    console.print(f"\n[bold yellow]Phase 4: Executing...[/bold yellow]")
    # TODO (Task 3): Call execute_approach(question, best["approach"])
    answer = "TODO: execute approach"
    total_calls += 1

    console.print(Panel(answer, title="[bold green]Final Answer[/bold green]"))
    console.print(f"[dim]Total model calls: {total_calls} ({n_branches} scoring + 1 generation + 1 execution)[/dim]")

    return {
        "question": question,
        "approaches": scored,
        "selected_approach": best["approach"],
        "answer": answer,
        "total_model_calls": total_calls,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def chat(messages, temperature=0, max_tokens=500) -> dict:
    payload = {"model": MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    r = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    questions = [
        "A farmer has 17 sheep. All but 9 die. How many are left? Explain the trick in this question.",
        "What is heavier: a pound of feathers or a pound of gold?",
        "If you have 3 apples and take away 2, how many apples do YOU have?",
    ]

    for question in questions:
        console.rule()
        result = run_lats(question)
        console.print()

    # Reflection: Did LATS select a better approach than the naive first approach?
    # For the sheep puzzle: naive = "17 - 9 = 8". Correct = "all but 9 = 9".
    # Did the scorer correctly identify the approach that handles the trick?
    # TODO: Add a comment here with your observations after running.
