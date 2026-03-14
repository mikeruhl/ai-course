"""
Module 06 — Task 1 & 2: ReAct Agent Implementations
=====================================================
Two approaches to the ReAct (Reason + Act) pattern:

  Task 1 (run_react_prompt):   Text parsing loop — Thought/Action/Observation
                                in plain text, no tool_calls API.
  Task 2 (run_react_native):   Native tool_calls API + CoT system prompt.

Run with:
    uv run python src/react_agent.py

Complete each TODO in order. Read the README concept section before starting.
"""

import json
import os
import re
import time

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

MAX_STEPS = 10  # safety guard — never run more than this many ReAct cycles


# ---------------------------------------------------------------------------
# Simulated tool implementations
# These stand in for real APIs. Replace with actual calls in production.
# ---------------------------------------------------------------------------

FAKE_KNOWLEDGE_BASE = {
    "telephone": (
        "The telephone was invented by Alexander Graham Bell. Bell was awarded "
        "the first patent for the electric telephone in 1876. His design allowed "
        "voice to be transmitted over electrical wire."
    ),
    "alexander graham bell": (
        "Alexander Graham Bell (1847–1922) was a Scottish-American inventor and "
        "scientist. He is credited with patenting the first practical telephone in "
        "1876, though contemporaries Elisha Gray and Antonio Meucci also made "
        "significant contributions."
    ),
    "first world war": (
        "The First World War (1914–1918) was triggered by the assassination of "
        "Archduke Franz Ferdinand of Austria on 28 June 1914. Underlying causes "
        "included militarism, alliances, imperialism, and nationalism (MAIN). "
        "Major powers involved: Britain, France, Russia, Germany, Austria-Hungary."
    ),
    "light bulb": (
        "The incandescent light bulb was developed by Thomas Edison in 1879. "
        "Edison's design used a carbon filament and could burn for 13.5 hours. "
        "Warren de la Rue had demonstrated an earlier version in 1840 using platinum."
    ),
}


def tool_search(query: str) -> str:
    """Simulated Wikipedia search. Returns a short paragraph or 'not found'."""
    key = query.lower().strip()
    for k, v in FAKE_KNOWLEDGE_BASE.items():
        if k in key or key in k:
            return v
    return f"No Wikipedia article found for '{query}'. Try a more specific search."


def tool_lookup(term: str) -> str:
    """Look up a specific term in the knowledge base."""
    key = term.lower().strip()
    result = FAKE_KNOWLEDGE_BASE.get(key)
    if result:
        return result
    # Try partial match
    for k, v in FAKE_KNOWLEDGE_BASE.items():
        if key in k:
            return v
    return f"Term '{term}' not found in knowledge base."


def execute_tool(action_line: str) -> str:
    """
    Parse an action line like 'search[who invented the telephone]'
    and dispatch to the appropriate tool function.
    Returns the observation string.
    """
    # TODO (Task 1): Parse the action_line to extract tool_name and argument.
    # Format: tool_name[argument]
    # Example: "search[telephone invention]" -> tool="search", arg="telephone invention"
    # Handle edge cases: unknown tool names, malformed lines.
    #
    # Steps:
    # 1. Use a regex or str.split to extract the part before '[' as tool name
    # 2. Extract the content between '[' and ']' as the argument
    # 3. Dispatch to tool_search() or tool_lookup() based on tool name
    # 4. Return an error string for unknown tools (don't raise — agent handles it)
    raise NotImplementedError("TODO: implement execute_tool()")


def parse_react_output(text: str) -> tuple[str | None, str | None, bool]:
    """
    Parse a ReAct model output into (thought, action, is_finished).

    Expected format from the model:
        Thought: <reasoning>
        Action: tool_name[argument]

    Or for the final step:
        Thought: <reasoning>
        Action: finish[final answer here]

    Returns:
        thought:     The text after "Thought:" (stripped), or None if not found
        action:      The text after "Action:" (stripped), or None if not found
        is_finished: True if action starts with "finish["
    """
    # TODO (Task 1): Implement the parser.
    # Tips:
    # - Lines may have extra whitespace; strip() each line
    # - The model may sometimes output "Thought:" and "Action:" on the same line
    #   or across multiple lines — handle both
    # - "finish[..." should set is_finished=True and extract the answer from
    #   inside the brackets as the action content
    # - If the model outputs ONLY a Thought with no Action, return (thought, None, False)
    #   so the caller can prompt the model to continue
    raise NotImplementedError("TODO: implement parse_react_output()")


# ---------------------------------------------------------------------------
# Task 1: ReAct via prompt text parsing
# ---------------------------------------------------------------------------

REACT_SYSTEM_PROMPT = """You are a research agent that reasons step by step before each action.

You have access to these tools:
  search[query]       — search a knowledge base for information
  lookup[term]        — look up a specific term
  finish[answer]      — provide your final answer and stop

IMPORTANT: You must follow this exact format for every response:

Thought: <your reasoning about what to do next>
Action: <tool>[<argument>]

Rules:
- Always write a Thought before every Action
- After receiving an Observation, write a new Thought before the next Action
- Use finish[answer] when you are confident in your answer
- Never skip the Thought step
- Never call a tool you have already called with the same argument

Example:
Thought: I need to find out who invented the telephone. I'll search for it.
Action: search[telephone invention]
"""


def run_react_prompt(question: str) -> str:
    """
    Run the ReAct loop using plain text parsing (no tool_calls API).

    The loop:
    1. Build initial messages with the system prompt + user question
    2. Call the model
    3. Parse Thought + Action from the output
    4. Execute the action to get an Observation
    5. Append model output + Observation to messages
    6. Repeat until finish[] or MAX_STEPS

    Returns the final answer string.
    """
    console.print(Panel(f"[bold cyan]ReAct Prompt Loop[/bold cyan]\nQuestion: {question}"))

    messages = [
        {"role": "system", "content": REACT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    total_tokens = 0

    for step in range(1, MAX_STEPS + 1):
        console.print(f"\n[dim]--- Step {step} ---[/dim]")

        # TODO (Task 1): Call the model with the current messages list.
        # Use the chat() helper defined below. Set temperature=0 (deterministic).
        # Extract the assistant's text from response["choices"][0]["message"]["content"].
        response = None  # replace with actual call
        assistant_text = ""  # replace with actual extraction
        total_tokens += 0  # replace with response["usage"]["total_tokens"]

        console.print(f"[green]{assistant_text}[/green]")

        # TODO (Task 1): Call parse_react_output() to get (thought, action, is_finished).
        thought, action, is_finished = None, None, False

        if is_finished:
            # TODO (Task 1): Extract the final answer from the finish[] action.
            # The format is "finish[answer text here]"
            final_answer = action  # fix this to extract just the content
            console.print(f"\n[bold green]Final answer:[/bold green] {final_answer}")
            console.print(f"[dim]Total tokens used: {total_tokens}[/dim]")
            return final_answer

        if action is None:
            # Model output a thought but no action — prompt it to continue
            messages.append({"role": "assistant", "content": assistant_text})
            messages.append({
                "role": "user",
                "content": "Please continue with an Action."
            })
            continue

        # Execute the tool and get an observation
        # TODO (Task 1): Call execute_tool(action) and catch any exceptions.
        # If the tool raises, return a descriptive error string as the observation.
        observation = ""  # replace with execute_tool(action)

        console.print(f"[yellow]Observation: {observation}[/yellow]")

        # Append the assistant's output and the observation to messages
        # TODO (Task 1): Append the assistant message and an observation message.
        # The observation should be injected as a user message in the format:
        #   "Observation: <observation_text>"
        # This keeps the Thought/Action/Observation structure in the conversation.

    console.print("[red]Max steps reached without finishing.[/red]")
    return "Agent did not reach a conclusion within the step limit."


# ---------------------------------------------------------------------------
# Task 2: ReAct via native tool_calls + CoT system prompt
# ---------------------------------------------------------------------------

REACT_COT_SYSTEM_PROMPT = """You are a research agent.

CRITICAL: Before calling ANY tool, you MUST write your reasoning in your response
content field. Explain:
  1. What you know so far
  2. What you still need to find out
  3. Which tool you are about to call and why

Then call the tool. After receiving the result, again write your updated reasoning
before calling the next tool.

This reasoning trace is important — do not skip it.
"""

TOOLS_NATIVE = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Search a knowledge base for information about a topic. "
                "Use this when you need to find facts, dates, or descriptions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query — be specific",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": (
                "Look up a specific named term directly. Use this when you know "
                "exactly what you are looking for (e.g., a person's name)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "The exact term to look up",
                    }
                },
                "required": ["term"],
            },
        },
    },
]


def run_react_native(question: str) -> str:
    """
    Run the ReAct loop using native tool_calls + CoT system prompt.

    Key difference from run_react_prompt:
    - No text parsing — arguments come back as structured JSON
    - Reasoning appears in message["content"] before tool_calls
    - The finish signal is finish_reason == "stop" (no tool calls)

    Returns the final answer string.
    """
    console.print(Panel(f"[bold magenta]ReAct Native Tool Calls[/bold magenta]\nQuestion: {question}"))

    messages = [
        {"role": "system", "content": REACT_COT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    total_tokens = 0

    for step in range(1, MAX_STEPS + 1):
        console.print(f"\n[dim]--- Step {step} ---[/dim]")

        # TODO (Task 2): Call the model with tools=TOOLS_NATIVE, tool_choice="auto".
        # Use httpx directly (see chat_with_tools() helper below, or write inline).
        response = None  # replace with actual call
        message = {}    # replace with response["choices"][0]["message"]
        finish_reason = ""  # replace with response["choices"][0]["finish_reason"]
        total_tokens += 0  # replace with response["usage"]["total_tokens"]

        # Print the reasoning content if present
        content = message.get("content") or ""
        if content:
            console.print(f"[green]Thought: {content}[/green]")

        # TODO (Task 2): Append the full assistant message to messages.
        # (Include tool_calls if present — do not strip them.)

        if finish_reason == "stop":
            console.print(f"\n[bold green]Final answer:[/bold green] {content}")
            console.print(f"[dim]Total tokens: {total_tokens}[/dim]")
            return content

        if finish_reason == "tool_calls":
            for tool_call in message.get("tool_calls", []):
                name = tool_call["function"]["name"]
                args = json.loads(tool_call["function"]["arguments"])

                console.print(f"[cyan]Action: {name}({args})[/cyan]")

                # TODO (Task 2): Dispatch to the correct tool function.
                # name will be "search" or "lookup".
                # Extract the argument from args dict.
                # Call tool_search() or tool_lookup() as appropriate.
                observation = "TODO: call the tool"

                console.print(f"[yellow]Observation: {observation}[/yellow]")

                # TODO (Task 2): Append the tool result message.
                # Format:
                # {
                #   "role": "tool",
                #   "tool_call_id": tool_call["id"],
                #   "content": observation
                # }

    console.print("[red]Max steps reached.[/red]")
    return "Agent did not reach a conclusion."


# ---------------------------------------------------------------------------
# Helper: raw HTTP call
# ---------------------------------------------------------------------------

def chat(messages: list[dict], temperature: float = 0, max_tokens: int = 500) -> dict:
    """Plain chat completion — no tools."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0,
    max_tokens: int = 500,
) -> dict:
    """Chat completion with tool definitions."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_question = "Who invented the telephone and in what year did they receive the patent?"

    console.rule("[bold]Task 1: ReAct via Prompt Parsing[/bold]")
    answer_prompt = run_react_prompt(test_question)

    console.rule("[bold]Task 2: ReAct via Native tool_calls[/bold]")
    answer_native = run_react_native(test_question)

    # Token comparison table
    # TODO (Task 2): After implementing both approaches, add token counts here
    # and display a comparison table with rich.Table.
    table = Table(title="ReAct Approach Comparison")
    table.add_column("Approach")
    table.add_column("Answer")
    table.add_column("Notes")
    table.add_row("Prompt parsing", answer_prompt, "Text-based, brittle parsing")
    table.add_row("Native tool_calls", answer_native, "Structured, CoT in content")
    console.print(table)
