"""
Module 07 — Task 2: Reflexion for Code Generation
==================================================
Generate code → evaluate by running it → feed errors back → try again.

Run with:
    uv run python src/reflexion.py
"""

import json
import os
import subprocess
import sys
import textwrap
import tempfile

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

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
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Coding problems
# Each problem has: description, test harness code, expected outputs
# ---------------------------------------------------------------------------

PROBLEMS = [
    {
        "id": 1,
        "description": (
            "Write a Python function called `reverse_words(s: str) -> str` that reverses "
            "the order of words in a string. Words are separated by spaces. "
            "Handle multiple spaces between words (normalize to single space in output). "
            "Do not use any imports."
        ),
        "test_harness": textwrap.dedent("""\
            # Test harness — do not modify
            assert reverse_words("hello world") == "world hello", f"Test 1 failed: {reverse_words('hello world')}"
            assert reverse_words("  foo   bar  baz  ") == "baz bar foo", f"Test 2 failed: {reverse_words('  foo   bar  baz  ')}"
            assert reverse_words("single") == "single", f"Test 3 failed: {reverse_words('single')}"
            assert reverse_words("") == "", f"Test 4 failed: {reverse_words('')}"
            print("ALL TESTS PASSED")
        """),
    },
    {
        "id": 2,
        "description": (
            "Write a Python function called `flatten(nested: list) -> list` that flattens "
            "a nested list to exactly one level. Only flatten one level deep — do not "
            "recursively flatten deeply nested lists. Do not use any imports."
        ),
        "test_harness": textwrap.dedent("""\
            assert flatten([1, [2, 3], [4, 5]]) == [1, 2, 3, 4, 5], f"Test 1 failed"
            assert flatten([[1, 2], [3, 4], [5]]) == [1, 2, 3, 4, 5], f"Test 2 failed"
            assert flatten([1, 2, 3]) == [1, 2, 3], f"Test 3 failed"
            assert flatten([[1, [2, 3]], [4]]) == [1, [2, 3], 4], f"Test 4 failed: one level only"
            assert flatten([]) == [], f"Test 5 failed"
            print("ALL TESTS PASSED")
        """),
    },
    {
        "id": 3,
        "description": (
            "Write a Python function called `count_vowels(s: str) -> int` that counts "
            "the number of vowels (a, e, i, o, u) in a string. Case-insensitive. "
            "Do not use any imports."
        ),
        "test_harness": textwrap.dedent("""\
            assert count_vowels("hello") == 2, f"Test 1 failed: {count_vowels('hello')}"
            assert count_vowels("HELLO") == 2, f"Test 2 failed: case insensitive"
            assert count_vowels("rhythm") == 0, f"Test 3 failed: no vowels"
            assert count_vowels("aeiou") == 5, f"Test 4 failed: all vowels"
            assert count_vowels("") == 0, f"Test 5 failed: empty string"
            print("ALL TESTS PASSED")
        """),
    },
]


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

GENERATOR_SYSTEM = """You are an expert Python programmer. Write clean, correct Python functions.

Rules:
- Output ONLY the function definition (no imports unless the problem allows them)
- No test code, no main block, no extra explanations
- Use type hints
- Handle edge cases (empty input, None, etc.)
"""

REFLEXION_SYSTEM = """You are an expert Python programmer fixing a failing solution.

You will be given:
1. The original problem description
2. Your previous attempt
3. The test failure output

Your job: write a CORRECTED version of the function.

Rules:
- Study the error carefully — what specific test case failed and why?
- Output ONLY the corrected function definition
- No test code, no explanations outside the function
"""


def generate_code(problem_description: str) -> str:
    """
    Generate a Python function for the given problem description.
    Returns only the function code (no test harness).
    """
    # TODO (Task 2): Call the model with GENERATOR_SYSTEM + problem_description.
    # Extract the text content and return it.
    # The model should output ONLY the function definition.
    raise NotImplementedError("TODO: implement generate_code()")


def refine_code(problem_description: str, previous_code: str, error_feedback: str) -> str:
    """
    Generate an improved version of the code given the error feedback.
    Returns only the function code.
    """
    user_content = (
        f"Problem:\n{problem_description}\n\n"
        f"Previous attempt:\n```python\n{previous_code}\n```\n\n"
        f"Test failure:\n{error_feedback}\n\n"
        f"Write a corrected version of the function."
    )

    # TODO (Task 2): Call the model with REFLEXION_SYSTEM + user_content.
    # Return only the function code.
    raise NotImplementedError("TODO: implement refine_code()")


def evaluate_code(code: str, test_harness: str) -> tuple[bool, str]:
    """
    Run the code + test harness in a subprocess.
    Returns (passed: bool, feedback: str).

    The test harness assumes the function is already defined (from code).
    We combine code + harness, write to a temp file, and run it.
    """
    full_script = code.rstrip() + "\n\n" + test_harness

    # TODO (Task 2): Write full_script to a temporary .py file.
    # Run it with subprocess.run([sys.executable, tmpfile], capture_output=True, text=True, timeout=10)
    # If returncode == 0 and "ALL TESTS PASSED" in stdout: return (True, "All tests passed")
    # Otherwise: return (False, stderr or stdout showing the failure)
    # Handle subprocess.TimeoutExpired: return (False, "Code timed out after 10 seconds")
    raise NotImplementedError("TODO: implement evaluate_code()")


def run_reflexion(problem: dict, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """
    Run the Reflexion loop for one coding problem.

    Returns a result dict:
    {
        "problem_id": int,
        "attempts": int,
        "passed": bool,
        "final_code": str,
        "history": [(attempt_num, code, passed, feedback), ...]
    }
    """
    console.print(Panel(
        f"[bold]Problem {problem['id']}[/bold]\n{problem['description'][:200]}...",
        title="Reflexion: Code Generation"
    ))

    history = []
    code = None
    passed = False

    for attempt in range(1, max_attempts + 1):
        console.print(f"\n[bold cyan]Attempt {attempt}/{max_attempts}[/bold cyan]")

        # Generate or refine code
        if attempt == 1:
            # TODO (Task 2): Call generate_code(problem["description"])
            code = "TODO: generate code"
        else:
            last_feedback = history[-1][3]
            # TODO (Task 2): Call refine_code(problem["description"], code, last_feedback)
            code = "TODO: refine code"

        # Display the generated code
        console.print(Syntax(code, "python", theme="monokai", line_numbers=True))

        # Evaluate
        # TODO (Task 2): Call evaluate_code(code, problem["test_harness"])
        passed, feedback = False, "TODO: evaluate code"

        history.append((attempt, code, passed, feedback))

        if passed:
            console.print(f"[bold green]PASSED on attempt {attempt}[/bold green]")
            break
        else:
            console.print(f"[bold red]FAILED[/bold red]")
            console.print(f"[dim]Feedback: {feedback[:300]}[/dim]")

    if not passed:
        console.print(f"[bold red]Failed all {max_attempts} attempts.[/bold red]")

    return {
        "problem_id": problem["id"],
        "attempts": len(history),
        "passed": passed,
        "final_code": code,
        "history": history,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def chat(messages, temperature=0.2, max_tokens=600) -> dict:
    """Slight temperature for code generation to allow variation across attempts."""
    payload = {"model": MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    r = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    all_results = []

    for problem in PROBLEMS:
        result = run_reflexion(problem)
        all_results.append(result)

    # Summary
    console.rule("[bold]Reflexion Summary[/bold]")
    passed_count = sum(1 for r in all_results if r["passed"])
    console.print(f"Problems passed: {passed_count}/{len(PROBLEMS)}")

    for r in all_results:
        status = "[green]PASS[/green]" if r["passed"] else "[red]FAIL[/red]"
        console.print(
            f"  Problem {r['problem_id']}: {status} "
            f"(solved in {r['attempts']} attempt{'s' if r['attempts'] != 1 else ''})"
        )

    # Token cost analysis
    # TODO (Task 2): Add token tracking to generate_code and refine_code.
    # Print total tokens used across all attempts.
    # Compare: if each problem had taken 3 attempts (worst case), how many tokens?
