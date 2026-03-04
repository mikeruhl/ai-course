"""
Module 10 Lab E — Failure Detection and Circuit Breaker
========================================================
Detect coordination failures and prevent cascading errors.

Tasks:
  1. Implement CyclicDelegationError and cycle detection
  2. Implement AgentCircuitBreaker class
  3. Add invocation telemetry
  4. Test: make a looping agent fail, verify circuit opens

Run with: uv run python src/circuit_breaker.py
"""

from __future__ import annotations

import os
import time
from collections import Counter
from typing import Any, Callable

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# Azure OpenAI configuration (present for completeness — not used by the
# circuit breaker itself, but real agents would call the LLM)
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
# LLM helper (available for student tasks that extend this lab)
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict]) -> str:
    """
    Call Azure OpenAI synchronously via raw httpx POST.

    Args:
        messages: List of {"role": ..., "content": ...} dicts.

    Returns:
        The assistant message content as a plain string.

    Raises:
        RuntimeError: If the API returns a non-2xx status or env vars are missing.
    """
    if not ENDPOINT or not API_KEY:
        raise RuntimeError(
            "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY must be set in your .env file."
        )

    body = {"messages": messages, "temperature": 0.3}
    response = httpx.post(BASE_URL, headers=HEADERS, json=body, timeout=60.0)

    if response.status_code != 200:
        raise RuntimeError(
            f"Azure OpenAI returned {response.status_code}: {response.text}"
        )

    return response.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class CyclicDelegationError(Exception):
    """
    Raised when an agent appears too many times in the invocation sequence,
    indicating a delegation loop (A → B → A → B → ...).

    Attributes:
        agent_name:  The agent name that exceeded the call limit.
        call_count:  How many times it was called.
        max_calls:   The configured limit.
    """

    def __init__(self, agent_name: str, call_count: int, max_calls: int) -> None:
        self.agent_name = agent_name
        self.call_count = call_count
        self.max_calls = max_calls
        super().__init__(
            f"Cyclic delegation detected: agent '{agent_name}' was called "
            f"{call_count} time(s), exceeding the limit of {max_calls}."
        )


class CircuitOpenError(Exception):
    """
    Raised when a call is attempted on a circuit breaker that is in the OPEN state
    and the reset timeout has not yet elapsed.

    Attributes:
        agent_name:       The wrapped agent's name.
        retry_after_seconds: Approximate seconds until the circuit may recover.
    """

    def __init__(self, agent_name: str, retry_after_seconds: float) -> None:
        self.agent_name = agent_name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Circuit is OPEN for agent '{agent_name}'. "
            f"Retry after approximately {retry_after_seconds:.1f}s."
        )


# ---------------------------------------------------------------------------
# Invocation telemetry
# ---------------------------------------------------------------------------

# Global list — each entry is a record for one agent call attempt.
# Shape: {agent_name, input_size, output_size, latency_ms, success}
invocation_tracker: list[dict[str, Any]] = []


def record_invocation(
    agent_name: str,
    input_size: int,
    output_size: int,
    latency_ms: float,
    success: bool,
) -> None:
    """
    Append one invocation record to the global tracker.

    Args:
        agent_name:  Name of the agent that was called.
        input_size:  Length (chars) of the input string.
        output_size: Length (chars) of the output string (0 on failure).
        latency_ms:  Wall-clock time the call took, in milliseconds.
        success:     True if the agent returned without raising an exception.
    """
    invocation_tracker.append(
        {
            "agent_name": agent_name,
            "input_size": input_size,
            "output_size": output_size,
            "latency_ms": round(latency_ms, 2),
            "success": success,
        }
    )


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def check_for_cycles(invocation_sequence: list[str], max_calls: int = 2) -> None:
    """
    Scan an ordered list of agent names for delegation loops.

    TODO (Task 1): This function is fully implemented. Study how it works, then
    call it from the orchestrator or pipeline runner whenever an agent completes.
    A good place is right after appending the agent name to the sequence.

    Args:
        invocation_sequence: Ordered list of agent names that have been invoked,
                             e.g. ["planner", "researcher", "planner"].
        max_calls:           Maximum allowed calls to any single agent.
                             Default is 2 (one retry is acceptable; loops are not).

    Raises:
        CyclicDelegationError: If any agent name appears more than max_calls times.

    Example:
        >>> check_for_cycles(["a", "b", "a", "b", "a"], max_calls=2)
        CyclicDelegationError: agent 'a' was called 3 time(s), exceeding the limit of 2.
    """
    counts = Counter(invocation_sequence)
    for agent_name, count in counts.items():
        if count > max_calls:
            raise CyclicDelegationError(
                agent_name=agent_name,
                call_count=count,
                max_calls=max_calls,
            )


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class AgentCircuitBreaker:
    """
    A circuit breaker that wraps agent function calls and trips open after
    repeated failures, preventing cascading errors across the system.

    States:
        CLOSED    — Normal operation. Calls pass through.
        OPEN      — Too many failures. Calls are rejected immediately.
        HALF_OPEN — Timeout elapsed. One probe call is allowed.
                    If it succeeds → CLOSED. If it fails → OPEN again.

    Usage:
        cb = AgentCircuitBreaker(max_failures=3, reset_timeout_seconds=30)
        result = cb.call(my_agent_fn, query="hello")
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"

    def __init__(
        self,
        max_failures: int = 3,
        reset_timeout_seconds: int = 60,
        agent_name: str = "unknown",
    ) -> None:
        """
        Args:
            max_failures:           Number of consecutive failures before opening.
            reset_timeout_seconds:  Seconds to wait in OPEN before trying HALF_OPEN.
            agent_name:             Label used in telemetry and error messages.
        """
        self.max_failures = max_failures
        self.reset_timeout_seconds = reset_timeout_seconds
        self.agent_name = agent_name

        self._state: str = self.CLOSED
        self._failure_count: int = 0
        self._opened_at: float | None = None  # epoch time when circuit opened

    def get_state(self) -> str:
        """Return the current circuit state: 'closed', 'open', or 'half-open'."""
        return self._state

    def call(self, agent_fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Invoke agent_fn(*args, **kwargs) through the circuit breaker.

        State machine:
          OPEN + timeout NOT elapsed  →  raise CircuitOpenError immediately.
          OPEN + timeout elapsed      →  transition to HALF_OPEN, allow one call.
          HALF_OPEN + call succeeds   →  transition to CLOSED, reset failure count.
          HALF_OPEN + call fails      →  transition back to OPEN, reset timer.
          CLOSED + call succeeds      →  reset failure count, return result.
          CLOSED + call fails         →  increment failure count.
                                         If failure count >= max_failures → OPEN.

        TODO (Task 2): Implement this method.
          1. Check if state is OPEN:
               elapsed = time.time() - self._opened_at
               if elapsed < self.reset_timeout_seconds: raise CircuitOpenError(...)
               else: self._state = self.HALF_OPEN
          2. Record start time for latency.
          3. Try calling agent_fn(*args, **kwargs).
          4. On success:
               self._state = self.CLOSED
               self._failure_count = 0
               record_invocation(..., success=True)
               return result
          5. On exception:
               self._failure_count += 1
               if self._failure_count >= self.max_failures:
                   self._state = self.OPEN
                   self._opened_at = time.time()
               record_invocation(..., success=False)
               re-raise the exception

        Args:
            agent_fn: The agent callable to wrap.
            *args:    Positional arguments forwarded to agent_fn.
            **kwargs: Keyword arguments forwarded to agent_fn.

        Returns:
            Whatever agent_fn returns on success.

        Raises:
            CircuitOpenError:       If the circuit is OPEN and timeout has not elapsed.
            (original exception):   Re-raised if agent_fn fails.
            NotImplementedError:    Until Task 2 is complete.
        """
        # TODO (Task 2): Replace this NotImplementedError with the state machine.
        # See the full algorithm in the docstring above.
        raise NotImplementedError(
            "Task 2: Implement AgentCircuitBreaker.call().\n"
            "  Follow the 5-step state machine described in the docstring.\n"
            "  Key methods/attributes to use:\n"
            "    self._state, self._failure_count, self._opened_at\n"
            "    self.CLOSED, self.OPEN, self.HALF_OPEN\n"
            "    self.max_failures, self.reset_timeout_seconds\n"
            "    record_invocation(), CircuitOpenError, time.time()"
        )


# ---------------------------------------------------------------------------
# Broken test agent
# ---------------------------------------------------------------------------

def looping_agent(query: str) -> str:
    """
    A deliberately broken agent that always raises ValueError.

    This simulates a subagent that has entered a bad state — perhaps due to
    a corrupted prompt, a downstream dependency failure, or a logic bug.

    In the real world you would fix the agent; in this lab we use it to drive
    the circuit breaker through its full state machine.

    TODO (Task 4): After implementing AgentCircuitBreaker.call(), observe the
    console output. You should see:
      Call 1 → CLOSED, failure count = 1
      Call 2 → CLOSED, failure count = 2
      Call 3 → CLOSED, failure count = 3 → transitions to OPEN
      Call 4 → CircuitOpenError (circuit is OPEN)
      Call 5 → CircuitOpenError (circuit is OPEN)

    Args:
        query: Ignored — the agent fails unconditionally.

    Raises:
        ValueError: Always.
    """
    raise ValueError(
        f"looping_agent is broken and cannot process query: '{query}'"
    )


# ---------------------------------------------------------------------------
# Telemetry display
# ---------------------------------------------------------------------------

def print_telemetry_table() -> None:
    """Print the global invocation_tracker as a rich table."""
    if not invocation_tracker:
        console.print("[dim]No invocations recorded.[/dim]")
        return

    table = Table(title="Invocation Telemetry", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Agent", style="bold cyan", no_wrap=True)
    table.add_column("Input chars", justify="right")
    table.add_column("Output chars", justify="right")
    table.add_column("Latency ms", justify="right")
    table.add_column("Success")

    for i, record in enumerate(invocation_tracker, start=1):
        success_cell = (
            "[green]yes[/green]" if record["success"] else "[red]no[/red]"
        )
        table.add_row(
            str(i),
            record["agent_name"],
            str(record["input_size"]),
            str(record["output_size"]),
            f"{record['latency_ms']:.1f}",
            success_cell,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    console.rule("[bold cyan]Module 10 Lab E — Failure Detection and Circuit Breaker[/bold cyan]")

    # --- Part A: Cycle detection demo ---
    console.print("\n[bold]Part A: Cycle Detection[/bold]")

    safe_sequence = ["planner", "researcher", "writer"]
    console.print(f"  Sequence {safe_sequence} → ", end="")
    try:
        check_for_cycles(safe_sequence, max_calls=2)
        console.print("[green]OK — no cycle detected[/green]")
    except CyclicDelegationError as exc:
        console.print(f"[red]CyclicDelegationError: {exc}[/red]")

    looping_sequence = ["planner", "researcher", "planner", "researcher", "planner"]
    console.print(f"  Sequence {looping_sequence} → ", end="")
    try:
        check_for_cycles(looping_sequence, max_calls=2)
        console.print("[green]OK — no cycle detected[/green]")
    except CyclicDelegationError as exc:
        console.print(f"[red]CyclicDelegationError: {exc}[/red]")

    # --- Part B: Circuit Breaker demo ---
    console.print("\n[bold]Part B: Circuit Breaker — calling looping_agent 5 times[/bold]")

    cb = AgentCircuitBreaker(
        max_failures=3,
        reset_timeout_seconds=60,
        agent_name="looping_agent",
    )

    state_history: list[tuple[int, str, str]] = []  # (call_num, state_before, outcome)

    for call_num in range(1, 6):
        state_before = cb.get_state()
        console.print(
            f"\n  [dim]Call {call_num}[/dim] | state before: [bold]{state_before}[/bold]"
        )
        try:
            result = cb.call(looping_agent, query=f"query-{call_num}")
            outcome = f"[green]SUCCESS: {result}[/green]"
        except CircuitOpenError as exc:
            outcome = f"[yellow]CircuitOpenError: {exc}[/yellow]"
        except NotImplementedError as exc:
            outcome = f"[magenta]TODO: {exc.args[0].splitlines()[0]}[/magenta]"
        except ValueError as exc:
            outcome = f"[red]ValueError (agent failed): {exc}[/red]"

        state_after = cb.get_state()
        console.print(f"  Outcome: {outcome}")
        console.print(f"  State after: [bold]{state_after}[/bold]")

        if state_before != state_after:
            console.print(
                f"  [bold magenta]State transition:[/bold magenta] "
                f"{state_before} → {state_after}"
            )

        state_history.append((call_num, state_before, state_after))

    # State transition summary
    console.print(
        Panel(
            "\n".join(
                f"  Call {n}: {before} → {after}"
                + (" [bold magenta](transition)[/bold magenta]" if before != after else "")
                for n, before, after in state_history
            ),
            title="[bold]State Transition Summary[/bold]",
            border_style="magenta",
        )
    )

    # Telemetry
    console.print("\n[bold]Invocation Telemetry[/bold]")
    print_telemetry_table()

    # What the student should see (expected behaviour).
    console.print(
        Panel(
            "[bold]Expected behaviour after Task 2 is complete:[/bold]\n\n"
            "  Call 1 → CLOSED, failure_count=1, ValueError re-raised\n"
            "  Call 2 → CLOSED, failure_count=2, ValueError re-raised\n"
            "  Call 3 → CLOSED, failure_count=3 → transitions to [red]OPEN[/red]\n"
            "  Call 4 → [yellow]CircuitOpenError[/yellow] (circuit is OPEN, call rejected)\n"
            "  Call 5 → [yellow]CircuitOpenError[/yellow] (circuit is OPEN, call rejected)\n\n"
            "[dim]Calls 4 and 5 should NOT appear in the telemetry table because the\n"
            "circuit breaker rejects them before the agent function is ever invoked.[/dim]",
            title="Reference: Expected Output",
            border_style="blue",
        )
    )

    console.rule("[bold cyan]Done[/bold cyan]")


if __name__ == "__main__":
    main()
