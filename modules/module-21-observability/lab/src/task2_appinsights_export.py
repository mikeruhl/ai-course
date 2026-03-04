"""
Task 2: Export OTel traces to Azure Application Insights.

Replace the console exporter from Task 1 with the azure-monitor-opentelemetry
exporter. Run 10 agent calls, then verify traces appear in the Azure Portal under
Application Insights > Transaction Search.

Expected timeline: traces appear within 2-3 minutes of running.

Usage:
    uv run python src/task2_appinsights_export.py
"""

import os
import time

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console()

# ---------------------------------------------------------------------------
# TODO: Configure azure-monitor-opentelemetry exporter
#
# Replace the ConsoleSpanExporter from Task 1 with the App Insights exporter.
#
# The azure-monitor-opentelemetry package provides a single configure() call:
#
#   from azure.monitor.opentelemetry import configure_azure_monitor
#   configure_azure_monitor(
#       connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
#   )
#
# Call this BEFORE any tracer.start_as_current_span() calls.
# It sets up the global TracerProvider, MeterProvider, and LoggingHandler.
#
# Reference:
#   https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-enable
# ---------------------------------------------------------------------------

# TODO: import and call configure_azure_monitor here


# ---------------------------------------------------------------------------
# Reuse your instrumented agent from Task 1
# ---------------------------------------------------------------------------

# TODO: import run_agent from task1_instrumented_agent
# from task1_instrumented_agent import run_agent


TEST_QUESTIONS = [
    "What's the weather in London?",
    "What is 42 * 17?",
    "What's the weather in New York?",
    "Calculate the square root of 144.",
    "What's the weather in Berlin and Paris? Which is cooler?",
    "What is 2 ** 20?",
    "What's the weather in Tokyo?",
    "Calculate 15% of 847.",
    "What's the weather in Sydney?",
    "What is the sum of all integers from 1 to 100?",
]


def run_batch_with_tracking() -> list[dict]:
    """
    Run all test questions and track results + timing.

    TODO: For each question, record:
        - run_id
        - question (first 60 chars)
        - answer (first 80 chars)
        - duration_ms
        - success (bool)
    """
    results = []
    for i, question in enumerate(TEST_QUESTIONS, 1):
        console.print(f"\n[bold]Question {i}/{len(TEST_QUESTIONS)}:[/bold] {question[:60]}")
        start = time.monotonic()

        try:
            # TODO: call run_agent(question) — traces will auto-export to App Insights
            answer = "TODO: call run_agent here"
            duration_ms = (time.monotonic() - start) * 1000
            results.append({
                "question": question[:60],
                "answer": answer[:80],
                "duration_ms": round(duration_ms),
                "success": True,
            })
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            results.append({
                "question": question[:60],
                "answer": f"ERROR: {e}",
                "duration_ms": round(duration_ms),
                "success": False,
            })

    return results


def print_results_table(results: list[dict]) -> None:
    table = Table(title="Batch Run Results", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Question", max_width=40)
    table.add_column("Answer", max_width=40)
    table.add_column("Duration", justify="right")
    table.add_column("OK", justify="center")

    for i, r in enumerate(results, 1):
        ok = "[green]Y[/green]" if r["success"] else "[red]N[/red]"
        table.add_row(str(i), r["question"], r["answer"], f"{r['duration_ms']}ms", ok)

    console.print(table)

    successful = sum(1 for r in results if r["success"])
    avg_ms = sum(r["duration_ms"] for r in results) / len(results)
    console.print(f"\n[bold]Success rate:[/bold] {successful}/{len(results)}")
    console.print(f"[bold]Avg duration:[/bold] {avg_ms:.0f}ms")


if __name__ == "__main__":
    console.print("[bold blue]Module 21 — Task 2: App Insights Export[/bold blue]")
    console.print("Running 10 agent calls. Traces will be exported to App Insights.\n")

    results = run_batch_with_tracking()
    print_results_table(results)

    console.print("\n[yellow]Traces are being exported in the background.[/yellow]")
    console.print("[yellow]Wait 2-3 minutes, then check:[/yellow]")
    console.print("  Azure Portal > Application Insights > Transaction Search")
    console.print("  Filter by: Operation Name = 'agent_run'")
    console.print("\n[dim]Sleeping 5 seconds to allow final batch flush...[/dim]")
    time.sleep(5)
    console.print("[green]Done.[/green]")
