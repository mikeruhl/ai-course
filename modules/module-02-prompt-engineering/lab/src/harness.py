"""
Module 2 Lab — Task 3: Eval Harness
=====================================
A simple prompt evaluation framework.

Usage:
    uv run python src/harness.py --cases test_cases/cases.json --runs 5
    uv run python src/harness.py --cases test_cases/cases.json --runs 5 --prompt-version v2

Test case format (test_cases/cases.json):
    [
      {
        "id": "sentiment-positive-01",
        "input": "I love this!",
        "expected": "positive",
        "scorer": "contains",
        "prompt_version": "v1"
      }
    ]

Scorers:
    "exact"    — output == expected (case-insensitive, stripped)
    "contains" — expected substring appears in output
    "json_key" — output is JSON and contains expected as a key:value pair
                 expected format: "key=value" e.g. "sentiment=positive"
    "llm"      — use the LLM itself to judge (slower, more flexible)
"""

import argparse
import json
import os
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

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
# TODO: Paste in your best system prompt from Task 1 here
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """
TODO: paste your system prompt here
"""


@dataclass
class TestCase:
    id: str
    input: str
    expected: str
    scorer: str
    prompt_version: str = "v1"


@dataclass
class RunResult:
    case_id: str
    run_number: int
    output: str
    passed: bool
    scorer: str


def chat(user_input: str) -> str:
    """Call the LLM with the current SYSTEM_PROMPT."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        "temperature": 0,
        "max_tokens": 300,
    }
    resp = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def llm_judge(output: str, expected: str, original_input: str) -> bool:
    """Use the LLM to judge whether output satisfies the expected behavior."""
    judge_prompt = f"""You are an impartial evaluator.

User input: {original_input}
Model output: {output}
Expected behavior: {expected}

Does the model output satisfy the expected behavior?
Reply with only "PASS" or "FAIL" followed by a one-sentence reason.
"""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": judge_prompt}],
        "temperature": 0,
        "max_tokens": 100,
    }
    resp = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    verdict = resp.json()["choices"][0]["message"]["content"].strip()
    return verdict.upper().startswith("PASS")


def score(output: str, expected: str, scorer: str, original_input: str) -> bool:
    """Score a single output against expected using the specified scorer."""
    # TODO: implement each scorer
    if scorer == "exact":
        # TODO: return True if output matches expected (case-insensitive, stripped)
        raise NotImplementedError("implement exact scorer")

    elif scorer == "contains":
        # TODO: return True if expected appears in output (case-insensitive)
        raise NotImplementedError("implement contains scorer")

    elif scorer == "json_key":
        # TODO: parse output as JSON, check for key=value pair in expected
        # expected format: "sentiment=positive"
        raise NotImplementedError("implement json_key scorer")

    elif scorer == "llm":
        return llm_judge(output, expected, original_input)

    else:
        raise ValueError(f"Unknown scorer: {scorer}")


def run_evaluation(cases: list[TestCase], n_runs: int) -> list[RunResult]:
    results = []
    for case in cases:
        console.print(f"\n[bold]Case:[/bold] {case.id}")
        for run in range(1, n_runs + 1):
            output = chat(case.input)
            passed = score(output, case.expected, case.scorer, case.input)
            results.append(RunResult(case.id, run, output, passed, case.scorer))
            status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
            console.print(f"  Run {run}: {status}  output={output[:80]!r}")
    return results


def print_report(results: list[RunResult], cases: list[TestCase]):
    case_results = defaultdict(list)
    for r in results:
        case_results[r.case_id].append(r.passed)

    table = Table(title="Eval Results")
    table.add_column("Case ID")
    table.add_column("Pass Rate")
    table.add_column("Runs")
    table.add_column("Status")

    overall_passes = 0
    overall_total = 0

    for case in cases:
        runs = case_results[case.id]
        passes = sum(runs)
        total = len(runs)
        pass_rate = passes / total if total > 0 else 0
        overall_passes += passes
        overall_total += total

        status = "[green]OK[/green]" if pass_rate >= 0.8 else "[red]FLAKY[/red]" if pass_rate > 0 else "[red]FAIL[/red]"
        table.add_row(case.id, f"{pass_rate:.0%}", str(total), status)

    console.print(table)

    overall = overall_passes / overall_total if overall_total > 0 else 0
    color = "green" if overall >= 0.9 else "yellow" if overall >= 0.7 else "red"
    console.print(f"\n[bold {color}]Overall pass rate: {overall:.1%} ({overall_passes}/{overall_total})[/bold {color}]")


def main():
    parser = argparse.ArgumentParser(description="Prompt eval harness")
    parser.add_argument("--cases", default="test_cases/cases.json")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--prompt-version", default="v1")
    args = parser.parse_args()

    with open(args.cases) as f:
        raw = json.load(f)

    cases = [
        TestCase(**c) for c in raw
        if c.get("prompt_version", "v1") == args.prompt_version
    ]

    console.print(f"[bold]Running {len(cases)} cases × {args.runs} runs[/bold]")
    results = run_evaluation(cases, args.runs)
    print_report(results, cases)


if __name__ == "__main__":
    main()
