"""
Module 06 — Task 3 & 4: Multi-Source Research Agent + Scratchpad
=================================================================
Task 3: Research agent that consults multiple sources and cites them.
Task 4: Growing scratchpad that persists conclusions across questions.

Run with:
    uv run python src/research_agent.py
"""

import json
import os

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

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
MAX_STEPS = 15


# ---------------------------------------------------------------------------
# Simulated multi-source knowledge base
# Each source has slightly different framing on the same facts.
# ---------------------------------------------------------------------------

WIKIPEDIA_DB = {
    "first world war causes": (
        "The First World War (1914–1918) had multiple causes. Historians use "
        "the MAIN acronym: Militarism (arms race between European powers), "
        "Alliances (Triple Entente vs Triple Alliance), Imperialism (competition "
        "for colonies), Nationalism (particularly in the Balkans). The immediate "
        "trigger was the assassination of Archduke Franz Ferdinand in Sarajevo "
        "on 28 June 1914 by Gavrilo Princip, a Bosnian-Serb nationalist."
    ),
    "assassination franz ferdinand": (
        "Archduke Franz Ferdinand, heir to the Austro-Hungarian throne, was "
        "assassinated on 28 June 1914 in Sarajevo by Gavrilo Princip. The "
        "assassination set off a chain of diplomatic crises and ultimatums. "
        "Austria-Hungary issued a harsh ultimatum to Serbia. When Serbia "
        "partially refused, Austria-Hungary declared war on 28 July 1914."
    ),
    "schlieffen plan": (
        "The Schlieffen Plan was Germany's pre-war strategy to fight a two-front "
        "war. It called for a rapid defeat of France through Belgium before "
        "turning to Russia. Germany's invasion of neutral Belgium on 4 August "
        "1914 brought Britain into the war, dramatically widening the conflict."
    ),
    "us constitution framers": (
        "The US Constitution was framed at the Constitutional Convention of 1787 "
        "in Philadelphia. James Madison is often called the 'Father of the "
        "Constitution' for his preparation and influence. He drafted the Virginia "
        "Plan that formed the framework for debate. Other key figures: George "
        "Washington (presiding officer), Benjamin Franklin, Alexander Hamilton."
    ),
    "james madison writings": (
        "James Madison wrote extensively throughout his life. Key works include: "
        "The Federalist Papers (co-authored with Alexander Hamilton and John Jay, "
        "1787–1788), the Virginia Plan (framework for the Constitution), the "
        "Bill of Rights (first 10 amendments, 1789), and numerous letters and "
        "political essays. He was also the 4th President of the United States."
    ),
}

ENCYCLOPEDIA_DB = {
    "first world war": (
        "SOURCE: Britannica Encyclopedia. World War I began in 1914 following "
        "decades of tension in Europe. Three proximate causes: (1) The June 1914 "
        "assassination of Archduke Franz Ferdinand; (2) Austria-Hungary's "
        "declaration of war against Serbia; (3) Germany's invasion of Belgium "
        "triggering British entry. The war lasted until the Armistice of "
        "11 November 1918 and resulted in approximately 20 million deaths."
    ),
    "world war 1 triggers": (
        "SOURCE: Oxford Reference. The specific triggers of WWI are distinct "
        "from the underlying causes. The July Crisis of 1914 saw a cascade "
        "of mobilizations: Austria-Hungary mobilized against Serbia; Russia "
        "mobilized to defend Serbia; Germany declared war on Russia; France "
        "was drawn in by alliance; Britain entered when Germany violated "
        "Belgian neutrality."
    ),
    "james madison constitution": (
        "SOURCE: Britannica Encyclopedia. James Madison arrived at the "
        "Constitutional Convention with the Virginia Plan already drafted. "
        "His meticulous notes from the convention (published posthumously) "
        "remain the primary historical record of the proceedings. Madison's "
        "insistence on a Bill of Rights led to the first 10 amendments."
    ),
}

LINKED_ARTICLES = {
    "triple alliance": (
        "The Triple Alliance (1882) was a secret agreement between Germany, "
        "Austria-Hungary, and Italy. Italy later switched sides. The alliance "
        "created a complex web of obligations that turned a regional conflict "
        "into a world war once the assassination triggered it."
    ),
    "federalist papers": (
        "The Federalist Papers are a collection of 85 essays written in 1787–1788 "
        "by Alexander Hamilton, James Madison, and John Jay under the pseudonym "
        "'Publius'. They argued for ratification of the US Constitution. "
        "Federalist No. 10 (Madison) and No. 51 (Madison/Hamilton) are considered "
        "the most influential."
    ),
}


def tool_search_wikipedia(query: str) -> dict:
    """Search Wikipedia. Returns {'source': 'Wikipedia', 'content': '...'}"""
    key = query.lower().strip()
    for k, v in WIKIPEDIA_DB.items():
        if k in key or key in k or any(word in k for word in key.split()):
            return {"source": "Wikipedia", "title": k, "content": v}
    return {"source": "Wikipedia", "title": query, "content": f"No Wikipedia article for '{query}'."}


def tool_search_encyclopedia(query: str) -> dict:
    """Search Britannica/Oxford. Returns {'source': 'Encyclopedia', 'content': '...'}"""
    key = query.lower().strip()
    for k, v in ENCYCLOPEDIA_DB.items():
        if k in key or key in k or any(word in k for word in key.split()):
            return {"source": "Encyclopedia", "title": k, "content": v}
    return {"source": "Encyclopedia", "title": query, "content": f"No encyclopedia entry for '{query}'."}


def tool_follow_link(title: str) -> dict:
    """Follow a link to a related article."""
    key = title.lower().strip()
    for k, v in LINKED_ARTICLES.items():
        if k in key or key in k:
            return {"source": "Linked Article", "title": k, "content": v}
    return {"source": "Linked Article", "title": title, "content": f"Linked article '{title}' not found."}


# ---------------------------------------------------------------------------
# Tool definitions for the native tool_calls API
# ---------------------------------------------------------------------------

RESEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_wikipedia",
            "description": (
                "Search Wikipedia for information on a topic. Returns a paragraph "
                "with the source labeled. Call this first for any new topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_encyclopedia",
            "description": (
                "Search encyclopedia sources (Britannica/Oxford) for a topic. "
                "Use this after Wikipedia to get a second perspective or more detail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "follow_link",
            "description": (
                "Follow a link to a related article mentioned in search results. "
                "Use when you see a reference worth exploring further."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Article title to follow"}
                },
                "required": ["title"],
            },
        },
    },
]

RESEARCH_SYSTEM_PROMPT = """You are a research agent that synthesizes information from multiple sources.

RULES:
1. Before each tool call, write your reasoning in the content field.
2. You MUST consult at least TWO different sources before answering.
3. Your final answer MUST cite every source you used, by name (e.g., "[Wikipedia]", "[Encyclopedia]").
4. After gathering enough information, provide a comprehensive answer with inline citations.
5. Do not stop after the first source — always seek a second perspective.
"""


def run_research_agent(question: str, scratchpad: list[str] | None = None) -> tuple[str, list[str]]:
    """
    Run the multi-source research agent.

    Args:
        question:   The question to research
        scratchpad: Optional list of prior conclusions to inject as context

    Returns:
        (final_answer, updated_scratchpad)
    """
    # Build system prompt with optional scratchpad context
    system_content = RESEARCH_SYSTEM_PROMPT

    # TODO (Task 4): If scratchpad is not empty, inject it into the system prompt.
    # Format it as:
    #   "\n\nPrevious session notes:\n" + "\n".join(f"- {note}" for note in scratchpad)
    # This gives the agent access to prior conclusions without re-searching.
    if scratchpad:
        pass  # TODO: append scratchpad context to system_content

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]

    sources_consulted: list[str] = []
    final_answer = ""

    console.print(Panel(f"[bold blue]Research Agent[/bold blue]\nQuestion: {question}"))

    if scratchpad:
        console.print(f"[dim]Scratchpad has {len(scratchpad)} prior notes[/dim]")

    for step in range(1, MAX_STEPS + 1):
        console.print(f"\n[dim]--- Step {step} ---[/dim]")

        # TODO (Task 3): Call the model with RESEARCH_TOOLS.
        # Use the chat_with_tools() helper.
        response = None  # replace with actual call
        message = {}
        finish_reason = ""

        content = message.get("content") or ""
        if content:
            console.print(f"[green]Thought: {content}[/green]")

        # TODO (Task 3): Append assistant message to messages.

        if finish_reason == "stop":
            final_answer = content
            break

        if finish_reason == "tool_calls":
            for tool_call in message.get("tool_calls", []):
                name = tool_call["function"]["name"]
                args = json.loads(tool_call["function"]["arguments"])

                console.print(f"[cyan]Action: {name}({args})[/cyan]")

                # TODO (Task 3): Dispatch to the correct tool function.
                # tool_search_wikipedia, tool_search_encyclopedia, tool_follow_link
                # Each returns a dict with 'source', 'title', 'content'.
                # Record the source name in sources_consulted.
                result = {"source": "TODO", "title": "TODO", "content": "TODO: call the tool"}

                sources_consulted.append(result.get("source", name))

                observation = json.dumps(result)
                console.print(f"[yellow]Observation: {result.get('content', '')[:200]}...[/yellow]")

                # TODO (Task 3): Append the tool result message.
                # Role: "tool", tool_call_id: tool_call["id"], content: observation

    console.print(f"\n[bold green]Answer:[/bold green] {final_answer}")
    console.print(f"[dim]Sources consulted: {sources_consulted}[/dim]")

    # TODO (Task 4): Extract key conclusions from final_answer for the scratchpad.
    # A simple approach: add a note like:
    #   f"Q: {question[:60]}... -> Key facts: {final_answer[:150]}..."
    # Return the updated scratchpad alongside the answer.
    updated_scratchpad = list(scratchpad or [])
    # TODO: append a new note to updated_scratchpad

    return final_answer, updated_scratchpad


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0,
    max_tokens: int = 800,
) -> dict:
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
# Main: Task 3 and Task 4 demos
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Task 3: Multi-source research
    console.rule("[bold]Task 3: Multi-Source Research Agent[/bold]")
    question_3 = (
        "Explain the causes of the First World War and name three major triggering events."
    )
    answer_3, _ = run_research_agent(question_3)

    # Task 4: Scratchpad continuity across two questions
    console.rule("[bold]Task 4: Scratchpad Demo[/bold]")

    scratchpad: list[str] = []

    q1 = "Who was the primary architect of the US Constitution?"
    answer_q1, scratchpad = run_research_agent(q1, scratchpad)

    console.print(f"\n[bold yellow]Scratchpad after Q1:[/bold yellow]")
    for note in scratchpad:
        console.print(f"  [dim]- {note}[/dim]")

    # Q2 intentionally omits the person's name — agent must recall from scratchpad
    q2 = "What other important documents did that person write? (Use your notes from the previous question.)"
    answer_q2, scratchpad = run_research_agent(q2, scratchpad)

    console.print(f"\n[bold yellow]Final scratchpad ({len(scratchpad)} notes):[/bold yellow]")
    for note in scratchpad:
        console.print(f"  [dim]- {note}[/dim]")
