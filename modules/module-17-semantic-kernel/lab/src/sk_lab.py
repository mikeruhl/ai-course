"""
Module 17 Lab — Semantic Kernel
================================
Tasks:
  1. Kernel + Plugin setup — register functions, invoke directly
  2. ChatCompletionAgent — multi-turn conversation with plugin
  3. Handlebars Planner — inspect generated plan, execute it
  4. AgentGroupChat — critic/writer collaboration loop
  5. RAG agent — Azure AI Search as SK memory store

Run with:
    uv run python src/sk_lab.py

Complete tasks in order. Each task builds on the previous one.
Comment out tasks you have already completed.
"""

import asyncio
import os

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

load_dotenv()

console = Console()

ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
API_KEY = os.environ["AZURE_OPENAI_KEY"]
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")


# ---------------------------------------------------------------------------
# Shared: build a configured Kernel
# ---------------------------------------------------------------------------

def build_kernel():
    """
    Create and return a configured Semantic Kernel instance.

    TODO: Import Kernel and AzureChatCompletion, instantiate the kernel,
    add the Azure OpenAI service using ENDPOINT, API_KEY, DEPLOYMENT.
    Return the configured kernel.

    Reference:
        from semantic_kernel import Kernel
        from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
    """
    # TODO: implement this function
    raise NotImplementedError("build_kernel() is not yet implemented")


# ---------------------------------------------------------------------------
# Shared: the course Plugin
# ---------------------------------------------------------------------------

class CoursePlugin:
    """
    A Semantic Kernel plugin with three functions the model can call.

    TODO: Decorate each method with @kernel_function.
    Provide a descriptive `name` and `description` for each — the model
    uses these descriptions to decide which function to call.

    Import:
        from semantic_kernel.functions import kernel_function
    """

    # TODO: add @kernel_function decorator with name and description
    def search(self, query: str) -> str:
        """
        Simulate searching a knowledge base.

        TODO: Implement a simple stub that returns a plausible search result
        string. Include the query in the response so you can verify the model
        passed the right argument.

        Example return value:
            "Found 3 documents about '{query}': [doc1, doc2, doc3]"
        """
        # TODO: implement stub
        raise NotImplementedError

    # TODO: add @kernel_function decorator with name and description
    def summarize(self, text: str, max_words: int = 100) -> str:
        """
        Return a stub summary (no LLM call needed for the stub).

        TODO: Return a string indicating what was summarized and the word limit.
        In a real implementation this would call the model or a summarization
        service.
        """
        # TODO: implement stub
        raise NotImplementedError

    # TODO: add @kernel_function decorator with name and description
    def classify(self, text: str) -> str:
        """
        Classify text into one of: technology, business, science, other.

        TODO: For the stub, pick a category based on simple keyword matching
        or always return a fixed category. The point is to have a callable
        function with a clear schema.
        """
        # TODO: implement stub
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Task 1: Kernel + Plugin setup
# ---------------------------------------------------------------------------

async def task1_kernel_and_plugin():
    console.print(Rule("[bold blue]Task 1: Kernel and Plugin Setup"))

    kernel = build_kernel()

    # TODO: Register CoursePlugin on the kernel.
    # Use kernel.add_plugin(CoursePlugin(), plugin_name="CoursePlugin")
    # Then invoke the search function directly (not through the model):
    #   result = await kernel.invoke(
    #       plugin_name="CoursePlugin",
    #       function_name="search",
    #       query="Azure Container Apps"
    #   )
    # Print the result.

    # TODO: Also list all registered functions on the kernel so you can see
    # what SK registers. Use kernel.plugins to iterate.

    # TODO: Invoke the classify function directly with some sample text.
    # Print the result.

    console.print("[yellow]TODO: implement Task 1[/yellow]")


# ---------------------------------------------------------------------------
# Task 2: ChatCompletionAgent with Plugin
# ---------------------------------------------------------------------------

async def task2_chat_completion_agent():
    console.print(Rule("[bold blue]Task 2: ChatCompletionAgent"))

    kernel = build_kernel()

    # TODO: Register the CoursePlugin on the kernel.

    # TODO: Create a ChatCompletionAgent.
    # Import: from semantic_kernel.agents import ChatCompletionAgent
    # The agent needs:
    #   - kernel=kernel
    #   - name="ResearchAssistant"
    #   - instructions: a system prompt that tells the agent to use the
    #     search tool to answer questions before responding

    # TODO: Create an AgentThread (or use the simple invoke approach).
    # Run the agent with a user message like:
    #   "What do you know about Semantic Kernel's architecture?"
    # Print the response.

    # TODO: Follow up with a second message that triggers the summarize function.
    # Example: "Summarize what you found in 50 words or less."

    # TODO: After the conversation, inspect and print the full message history.
    # Look for the tool_calls entries — compare to the raw loop in Module 3.

    console.print("[yellow]TODO: implement Task 2[/yellow]")


# ---------------------------------------------------------------------------
# Task 3: Handlebars Planner
# ---------------------------------------------------------------------------

async def task3_handlebars_planner():
    console.print(Rule("[bold blue]Task 3: Handlebars Planner"))

    kernel = build_kernel()

    # TODO: Register the CoursePlugin on the kernel.

    # TODO: Create a HandlebarsPlanner.
    # Import: from semantic_kernel.planners.handlebars_planner import HandlebarsPlanner
    #   planner = HandlebarsPlanner(kernel)

    goal = (
        "Find information about Azure Container Apps, summarize the key features "
        "in 100 words, classify the technology category, then produce a briefing."
    )

    # TODO: Call planner.create_plan(goal) and print the generated plan.
    # The plan is a Handlebars template — inspect it before executing.
    # What functions did the planner select? In what order?

    # TODO: Execute the plan with plan.invoke(kernel).
    # Print the final result.

    # TODO: Count how many LLM calls were made (plan generation + execution).
    # Add a comment explaining the count.

    console.print("[yellow]TODO: implement Task 3[/yellow]")


# ---------------------------------------------------------------------------
# Task 4: AgentGroupChat — Critic and Writer
# ---------------------------------------------------------------------------

async def task4_agent_group_chat():
    console.print(Rule("[bold blue]Task 4: AgentGroupChat — Critic + Writer"))

    # TODO: Build two kernels (or share one — your choice).
    # Two approaches:
    #   a) Each agent gets its own kernel instance
    #   b) Agents share a kernel (simpler, but less isolation)
    # Start with approach (b).

    kernel = build_kernel()

    # TODO: Create WriterAgent.
    # Instructions: "You write clear, concise technical summaries. When given
    # a topic, produce a polished draft. Respond with only your draft text."

    # TODO: Create CriticAgent.
    # Instructions: "You review technical writing. Evaluate the draft for
    # clarity, accuracy, and completeness. If it is acceptable, respond with
    # 'APPROVED'. If not, provide specific numbered feedback for improvement."

    # TODO: Create an AgentGroupChat with both agents.
    # Import: from semantic_kernel.agents import AgentGroupChat
    # You need a termination strategy that stops when the critic says APPROVED
    # or after 6 turns maximum.
    #
    # Hint: look at KernelFunctionTerminationStrategy or
    # DefaultTerminationStrategy in the SK docs/samples.

    task = (
        "Write a 3-paragraph explanation of how Kubernetes handles pod "
        "scheduling for an audience of senior software engineers."
    )

    # TODO: Add the task as the initial user message and invoke the group chat.
    # Print each agent's response as it comes in, labeled with the agent name.

    # TODO: Print how many turns it took and whether the critic approved.

    console.print("[yellow]TODO: implement Task 4[/yellow]")


# ---------------------------------------------------------------------------
# Task 5: RAG Agent with Azure AI Search
# ---------------------------------------------------------------------------

async def task5_rag_agent():
    console.print(Rule("[bold blue]Task 5: RAG Agent with Azure AI Search"))

    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
    search_key = os.environ.get("AZURE_SEARCH_KEY", "")
    search_index = os.environ.get("AZURE_SEARCH_INDEX", "sk-module-docs")

    if not search_endpoint or not search_key:
        console.print(
            "[yellow]AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_KEY not set. "
            "Skipping Task 5.[/yellow]"
        )
        return

    # TODO: Build a kernel configured for both Azure OpenAI and Azure AI Search.
    # Azure AI Search memory connector:
    #   from semantic_kernel.connectors.memory.azure_ai_search import (
    #       AzureAISearchCollection,
    #   )
    # You will need to define a data model (a dataclass with @vectorstoremodel
    # decorator) or use SK's built-in TextMemoryPlugin.

    # TODO: Index sample documents. Read a few README.md files from this repo
    # and store them in the Azure AI Search index via SK's memory API.
    # Each document needs: id, text content, and an embedding vector.
    # SK can generate embeddings automatically if you add an embedding service.

    # TODO: Build a RAG agent that:
    #   1. Receives a user question
    #   2. Calls kernel.memory.search(query, collection=search_index, limit=3)
    #      to retrieve relevant chunks
    #   3. Formats retrieved chunks as context in the prompt
    #   4. Answers using only the retrieved content
    #   5. Cites which document each piece of information came from

    # TODO: Test with 3 questions:
    #   - "What is Semantic Kernel?"
    #   - "How does the agent loop work?"
    #   - "What is Azure Container Apps?"
    # Print the answer and the source citations for each.

    console.print("[yellow]TODO: implement Task 5[/yellow]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    console.print(Panel.fit(
        "[bold]Module 17 — Semantic Kernel Lab[/bold]\n"
        "Comment out tasks you have already completed.",
        border_style="blue",
    ))

    await task1_kernel_and_plugin()
    await task2_chat_completion_agent()
    await task3_handlebars_planner()
    await task4_agent_group_chat()
    await task5_rag_agent()


if __name__ == "__main__":
    asyncio.run(main())
