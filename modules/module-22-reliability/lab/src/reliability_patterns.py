"""
Module 22 Lab — Reliability Patterns
======================================
Implement production reliability patterns for AI agents.

Tasks:
  A. Retry        — exponential backoff with jitter for Azure OpenAI calls
  B. Circuit Breaker — track failures, trip open, half-open probe
  C. Fallback Chain  — primary model → cheaper model → cached response
  D. Guardrails      — validate LLM outputs against schemas, reject/retry

Run with:
    uv run reliability --task A
    uv run reliability --task B
    uv run reliability --task C
    uv run reliability --task D
"""

import argparse
import asyncio
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

PROVIDER = os.environ.get("LLM_PROVIDER", "azure")

if PROVIDER == "vertex":
    import google.auth
    import google.auth.transport.requests
    GCP_PROJECT = os.environ["GCP_PROJECT_ID"]
    GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
    _credentials, _ = google.auth.default()
    _credentials.refresh(google.auth.transport.requests.Request())
    CHAT_URL = f"https://{GCP_REGION}-aiplatform.googleapis.com/v1/projects/{GCP_PROJECT}/locations/{GCP_REGION}/endpoints/openapi/chat/completions"
    HEADERS = {"Authorization": f"Bearer {_credentials.token}", "Content-Type": "application/json"}
    MODEL = os.environ.get("VERTEX_MODEL", "google/gemini-2.0-flash")
else:  # azure (default)
    ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    API_KEY = os.environ["AZURE_OPENAI_KEY"]
    DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
    CHAT_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
    HEADERS = {"Content-Type": "application/json", "api-key": API_KEY}
    MODEL = DEPLOYMENT

console = Console()


async def chat_raw(client: httpx.AsyncClient, messages: list[dict], timeout: float = 30) -> dict:
    """Raw chat call — returns full response dict, does NOT handle errors."""
    resp = await client.post(
        CHAT_URL, headers=HEADERS,
        json={"messages": messages, "temperature": 0},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Task A — Retry with exponential backoff + jitter
# ---------------------------------------------------------------------------

async def retry_with_backoff(
    client: httpx.AsyncClient,
    messages: list[dict],
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
) -> dict:
    """
    Retry pattern with full jitter.

    Delay = random(0, min(max_delay, base_delay * 2^attempt))

    Full jitter prevents thundering herd — when many clients retry
    simultaneously after a shared failure, jitter spreads their retries
    across the delay window.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = await chat_raw(client, messages)
            if attempt > 0:
                console.print(f"  [green]Succeeded on attempt {attempt + 1}[/green]")
            return result
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code == 429:
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    delay = float(retry_after)
                    console.print(f"  [yellow]429 — Retry-After: {delay}s[/yellow]")
                else:
                    delay = min(max_delay, base_delay * (2 ** attempt))
                    delay = random.uniform(0, delay)
                    console.print(f"  [yellow]429 — backoff: {delay:.2f}s (attempt {attempt + 1})[/yellow]")
                await asyncio.sleep(delay)
            elif e.response.status_code >= 500:
                delay = min(max_delay, base_delay * (2 ** attempt))
                delay = random.uniform(0, delay)
                console.print(f"  [yellow]{e.response.status_code} — backoff: {delay:.2f}s[/yellow]")
                await asyncio.sleep(delay)
            else:
                raise
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            last_error = e
            delay = min(max_delay, base_delay * (2 ** attempt))
            delay = random.uniform(0, delay)
            console.print(f"  [yellow]Network error — backoff: {delay:.2f}s[/yellow]")
            await asyncio.sleep(delay)

    raise last_error  # type: ignore


async def task_a():
    """Demonstrate retry with exponential backoff + jitter."""
    console.print(Panel("Task A — Retry with Exponential Backoff + Jitter", style="bold cyan"))

    console.print("\n[bold]Simulating retry delay schedule (no actual failures):[/bold]")
    table = Table(title="Backoff Schedule (base=1s, max=60s)")
    table.add_column("Attempt", width=10)
    table.add_column("Max Delay", width=12)
    table.add_column("Sample Jittered", width=15)
    for i in range(6):
        max_d = min(60, 1.0 * (2 ** i))
        jittered = random.uniform(0, max_d)
        table.add_row(str(i + 1), f"{max_d:.1f}s", f"{jittered:.2f}s")
    console.print(table)

    console.print("\n[bold]Making a real call with retry wrapper:[/bold]")
    async with httpx.AsyncClient() as client:
        result = await retry_with_backoff(
            client,
            [{"role": "user", "content": "Say 'Retry test passed' in exactly 3 words."}],
        )
        content = result["choices"][0]["message"]["content"]
        console.print(f"[green]Response:[/green] {content}")


# ---------------------------------------------------------------------------
# Task B — Circuit breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for tool/API calls.

    CLOSED  → normal operation; failures increment counter
    OPEN    → all calls rejected immediately (fail fast)
    HALF_OPEN → one probe call allowed; success resets, failure re-opens
    """
    failure_threshold: int = 3
    recovery_timeout: float = 10.0
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0
    success_count: int = 0
    total_calls: int = 0

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — allow one probe
        return True

    def record_success(self):
        self.total_calls += 1
        self.success_count += 1
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0

    def record_failure(self):
        self.total_calls += 1
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN


async def call_with_circuit_breaker(
    cb: CircuitBreaker,
    fn,
    *args,
    **kwargs,
) -> dict | None:
    if not cb.can_execute():
        console.print(f"  [red]Circuit OPEN — call rejected (fail fast)[/red]")
        return None
    try:
        result = await fn(*args, **kwargs)
        cb.record_success()
        return result
    except Exception as e:
        cb.record_failure()
        console.print(f"  [yellow]Failure recorded ({cb.failure_count}/{cb.failure_threshold}): {e}[/yellow]")
        if cb.state == CircuitState.OPEN:
            console.print(f"  [red]Circuit TRIPPED OPEN — will recover in {cb.recovery_timeout}s[/red]")
        return None


async def task_b():
    """Demonstrate circuit breaker with simulated failures."""
    console.print(Panel("Task B — Circuit Breaker", style="bold cyan"))

    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)

    call_count = 0

    async def flaky_tool(query: str) -> dict:
        """Simulates a tool that fails on every other call."""
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 0:
            raise ConnectionError(f"Simulated failure on call {call_count}")
        return {"result": f"Success for: {query}"}

    console.print("[bold]Running 10 calls against a flaky tool (fails every other call):[/bold]\n")
    for i in range(10):
        result = await call_with_circuit_breaker(cb, flaky_tool, f"query-{i}")
        status = f"[green]{result}[/green]" if result else "[red]None[/red]"
        console.print(f"  Call {i+1}: state={cb.state.value}, result={status}")
        if cb.state == CircuitState.OPEN:
            console.print(f"  [dim]Waiting for recovery timeout ({cb.recovery_timeout}s)...[/dim]")
            await asyncio.sleep(cb.recovery_timeout + 0.1)
            console.print(f"  [dim]Recovery timeout elapsed — state: {cb.state.value}[/dim]")

    table = Table(title="Circuit Breaker Stats")
    table.add_column("Metric", width=20)
    table.add_column("Value", width=15)
    table.add_row("Total calls", str(cb.total_calls))
    table.add_row("Successes", str(cb.success_count))
    table.add_row("Failures", str(cb.failure_count))
    table.add_row("Final state", cb.state.value)
    console.print(table)


# ---------------------------------------------------------------------------
# Task C — Fallback chain
# ---------------------------------------------------------------------------

async def task_c():
    """Fallback chain: primary model → cheaper model → cached response."""
    console.print(Panel("Task C — Fallback Chain", style="bold cyan"))

    cache: dict[str, str] = {
        "What is Azure OpenAI?": "Azure OpenAI Service provides REST API access to OpenAI's models including GPT-4o and GPT-4o-mini.",
    }

    async def try_primary(client: httpx.AsyncClient, prompt: str) -> str | None:
        """Attempt primary model."""
        try:
            result = await chat_raw(client, [{"role": "user", "content": prompt}], timeout=10)
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            console.print(f"  [yellow]Primary failed: {e}[/yellow]")
            return None

    async def try_fallback(client: httpx.AsyncClient, prompt: str) -> str | None:
        """Attempt fallback with lower temperature and simpler system prompt."""
        try:
            resp = await client.post(
                CHAT_URL, headers=HEADERS,
                json={
                    "messages": [
                        {"role": "system", "content": "Answer briefly."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": 100,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            console.print(f"  [yellow]Fallback failed: {e}[/yellow]")
            return None

    def try_cache(prompt: str) -> str | None:
        """Check local cache."""
        return cache.get(prompt)

    prompts = [
        "What is Azure OpenAI?",
        "Explain the circuit breaker pattern in 2 sentences.",
        "What is the capital of France?",
    ]

    async with httpx.AsyncClient() as client:
        for prompt in prompts:
            console.print(f"\n[yellow]Query:[/yellow] {prompt}")

            # Tier 1: primary
            answer = await try_primary(client, prompt)
            tier = "Primary"

            # Tier 2: fallback model (same endpoint, constrained params)
            if answer is None:
                answer = await try_fallback(client, prompt)
                tier = "Fallback"

            # Tier 3: cache
            if answer is None:
                answer = try_cache(prompt)
                tier = "Cache"

            if answer is None:
                answer = "[All tiers exhausted — no response available]"
                tier = "None"

            console.print(f"  [dim]Tier used:[/dim] {tier}")
            console.print(Panel(answer, border_style="green"))


# ---------------------------------------------------------------------------
# Task D — Output guardrails
# ---------------------------------------------------------------------------

EXPECTED_SCHEMA = {
    "type": "object",
    "required": ["action", "confidence", "reasoning"],
    "properties": {
        "action": {"type": "string", "enum": ["approve", "reject", "escalate"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string"},
    },
}


def validate_output(text: str, schema: dict) -> tuple[bool, str]:
    """Validate LLM output against a JSON schema (simplified validator)."""
    try:
        cleaned = re.sub(r"```json\s*|\s*```", "", text.strip())
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"

    if not isinstance(data, dict):
        return False, f"Expected object, got {type(data).__name__}"

    for field_name in schema.get("required", []):
        if field_name not in data:
            return False, f"Missing required field: {field_name}"

    props = schema.get("properties", {})
    for field_name, field_schema in props.items():
        if field_name not in data:
            continue
        value = data[field_name]
        expected_type = field_schema.get("type")
        if expected_type == "string" and not isinstance(value, str):
            return False, f"Field '{field_name}' must be string, got {type(value).__name__}"
        if expected_type == "number" and not isinstance(value, (int, float)):
            return False, f"Field '{field_name}' must be number, got {type(value).__name__}"
        if "enum" in field_schema and value not in field_schema["enum"]:
            return False, f"Field '{field_name}' must be one of {field_schema['enum']}, got '{value}'"
        if "minimum" in field_schema and value < field_schema["minimum"]:
            return False, f"Field '{field_name}' must be >= {field_schema['minimum']}"
        if "maximum" in field_schema and value > field_schema["maximum"]:
            return False, f"Field '{field_name}' must be <= {field_schema['maximum']}"

    return True, "Valid"


async def task_d():
    """Validate LLM outputs against schemas with retry on failure."""
    console.print(Panel("Task D — Output Guardrails", style="bold cyan"))

    prompts = [
        "A user submitted a code change that adds eval() to handle user input. Should this be approved?",
        "A user wants to add a logging statement to track API latency. Should this be approved?",
        "A user proposes replacing the ORM with raw SQL queries for a public-facing endpoint. Should this be approved?",
    ]

    schema_desc = json.dumps(EXPECTED_SCHEMA, indent=2)

    async with httpx.AsyncClient() as client:
        for prompt in prompts:
            console.print(f"\n[yellow]Review request:[/yellow] {prompt}")

            valid = False
            for attempt in range(3):
                messages = [
                    {
                        "role": "system",
                        "content": (
                            f"You are a code review bot. Respond ONLY with valid JSON matching this schema:\n"
                            f"{schema_desc}\n\nNo markdown, no explanation outside the JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
                result = await chat_raw(client, messages)
                output = result["choices"][0]["message"]["content"]
                is_valid, reason = validate_output(output, EXPECTED_SCHEMA)

                if is_valid:
                    console.print(f"  [green]Attempt {attempt + 1}: Valid[/green]")
                    data = json.loads(re.sub(r"```json\s*|\s*```", "", output.strip()))
                    table = Table()
                    table.add_column("Field", width=15)
                    table.add_column("Value", max_width=60)
                    for k, v in data.items():
                        table.add_row(k, str(v))
                    console.print(table)
                    valid = True
                    break
                else:
                    console.print(f"  [yellow]Attempt {attempt + 1}: Invalid — {reason}[/yellow]")
                    console.print(f"  [dim]Raw output: {output[:100]}[/dim]")

            if not valid:
                console.print(f"  [red]All attempts failed validation — escalating to human.[/red]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Module 22 — Reliability Patterns Lab")
    parser.add_argument("--task", choices=["A", "B", "C", "D"], required=True)
    args = parser.parse_args()

    dispatch = {"A": task_a, "B": task_b, "C": task_c, "D": task_d}
    asyncio.run(dispatch[args.task]())


if __name__ == "__main__":
    main()
