"""
Task 1: Instrument an agent with OpenTelemetry spans.

Every LLM call becomes a span with GenAI semantic convention attributes.
Every tool call becomes a child span of the LLM call that requested it.
The full agent run is the root span.

Run with the console exporter first to see traces locally before wiring up
App Insights in Task 2.

Usage:
    uv run python src/task1_instrumented_agent.py
"""

import json
import os
import uuid
from contextlib import contextmanager

import httpx
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import StatusCode
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()

# ---------------------------------------------------------------------------
# OTel setup — console exporter so you can see spans locally
# ---------------------------------------------------------------------------

# TODO: Create a TracerProvider with a ConsoleSpanExporter.
# Steps:
#   1. Create a TracerProvider
#   2. Add a BatchSpanProcessor wrapping a ConsoleSpanExporter
#   3. Set it as the global tracer provider via trace.set_tracer_provider(...)
#   4. Get a tracer: tracer = trace.get_tracer("module-21-agent")
#
# Reference: https://opentelemetry.io/docs/languages/python/getting-started/
tracer = None  # TODO: replace with trace.get_tracer("module-21-agent")


# ---------------------------------------------------------------------------
# LLM client (raw httpx — no SDK wrapper so tracing is explicit)
# ---------------------------------------------------------------------------

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
    DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]
    API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
    CHAT_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
    HEADERS = {"api-key": API_KEY, "Content-Type": "application/json"}
    MODEL = DEPLOYMENT


def call_llm_with_span(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """
    Make an LLM API call and record it as an OTel span.

    TODO: Wrap this function body in a span named "llm_call".
    The span should have these attributes (GenAI semantic conventions):
        gen_ai.system            = "azure_openai"
        gen_ai.request.model     = DEPLOYMENT
        gen_ai.request.temperature = 0
        gen_ai.usage.input_tokens  = response["usage"]["prompt_tokens"]
        gen_ai.usage.output_tokens = response["usage"]["completion_tokens"]
        gen_ai.response.finish_reason = response["choices"][0]["finish_reason"]
        gen_ai.response.id         = response["id"]

    If the call fails, record the exception on the span and re-raise.
    """
    # TODO: open a span before the httpx call, set attributes after getting the response
    response = httpx.post(
        CHAT_URL,
        headers=HEADERS,
        json={
            "messages": messages,
            "tools": tools or [],
            "tool_choice": "auto" if tools else "none",
            "temperature": 0,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def call_tool_with_span(tool_name: str, tool_call_id: str, args: dict, parent_span) -> str:
    """
    Execute a tool and record it as a child span.

    TODO: Create a child span named f"tool_{tool_name}" as a child of parent_span.
    Attributes:
        tool.name     = tool_name
        tool.call_id  = tool_call_id
        tool.success  = True/False (set after execution)
        tool.error    = error message (only if failed)

    Use trace.use_span(parent_span) as the context when creating the child span.
    """
    # TODO: wrap the tool execution in a child span
    result = _execute_tool(tool_name, args)
    return result


def _execute_tool(name: str, args: dict) -> str:
    """Toy tools for the lab — replace with real tools from module-03 if you like."""
    if name == "get_weather":
        city = args.get("city", "unknown")
        return json.dumps({"city": city, "temp_c": 18, "condition": "partly cloudy"})
    if name == "calculate":
        expr = args.get("expression", "")
        try:
            # NOTE: eval is fine for a controlled lab; never in production
            result = eval(expr)  # noqa: S307
            return json.dumps({"result": result})
        except Exception as e:
            return json.dumps({"error": str(e)})
    return json.dumps({"error": f"Unknown tool: {name}"})


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Python math expression, e.g. '2 ** 10'"},
                },
                "required": ["expression"],
            },
        },
    },
]


def run_agent(user_message: str, run_id: str | None = None) -> str:
    """
    Run the agent loop with full OTel tracing.

    TODO: Wrap the entire agent loop in a root span named "agent_run".
    Root span attributes:
        agent.run_id      = run_id
        agent.user_input  = user_message (first 200 chars)

    Pass the root span as parent context when calling call_tool_with_span.
    """
    run_id = run_id or str(uuid.uuid4())
    console.print(Panel(f"[bold]Agent run[/bold] {run_id[:8]}\n{user_message}", style="blue"))

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant with access to weather and calculation tools.",
        },
        {"role": "user", "content": user_message},
    ]

    # TODO: open root span here, set agent.run_id attribute

    max_iterations = 10
    for iteration in range(max_iterations):
        response = call_llm_with_span(messages, TOOLS)
        message = response["choices"][0]["message"]
        finish_reason = response["choices"][0]["finish_reason"]

        messages.append(message)

        if finish_reason == "stop":
            final_answer = message.get("content", "")
            console.print(f"[green]Answer:[/green] {final_answer}")
            return final_answer

        if finish_reason == "tool_calls":
            current_span = None  # TODO: replace with the current LLM span
            for tool_call in message.get("tool_calls", []):
                name = tool_call["function"]["name"]
                args = json.loads(tool_call["function"]["arguments"])
                call_id = tool_call["id"]

                console.print(f"  [yellow]Tool:[/yellow] {name}({args})")
                result = call_tool_with_span(name, call_id, args, current_span)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
                })

    return "Max iterations reached"


if __name__ == "__main__":
    questions = [
        "What's the weather in Seattle and Tokyo? Which one is warmer?",
        "What is 2 to the power of 32?",
        "What is the weather in Paris? Convert the temperature to Fahrenheit (F = C * 9/5 + 32).",
    ]

    for q in questions:
        run_agent(q)
        console.print()

    console.print("[dim]Check console output above for OTel span JSON.[/dim]")
    console.print("[dim]In Task 2 you will redirect these spans to App Insights.[/dim]")
