# Module 17: Semantic Kernel

## Overview

Semantic Kernel (SK) is Microsoft's open-source SDK for building AI-powered
applications. It sits at the intersection of production engineering and AI
orchestration — designed for teams that need to ship reliable, observable,
enterprise-grade AI systems on Azure.

SK is not a research framework. It is production-focused, with deep Azure
integration (Key Vault, App Insights, Azure AI Search, Managed Identity) and
first-class support for both C# and Python. For Azure-native shops, it is the
most pragmatic choice in the framework ecosystem.

This module covers SK's full architecture: how the Kernel acts as an IoC
container, how Plugins expose functions to the model, how Planners sequence
those functions into multi-step workflows, and how SK Agents coordinate
multi-agent conversations.

---

## Why Semantic Kernel Exists

The raw tool-calling loop you built in Module 3 works — but it does not scale.
As your application grows, you accumulate:

- Dozens of tool definitions scattered across files
- Ad-hoc retry logic duplicated everywhere
- No standard way to inject an Azure AI Search backend
- No observability hooks
- No separation between "what functions are available" and "how the LLM picks them"

SK solves these problems by providing a structured framework with:
- A Kernel that centralizes service configuration (IoC container pattern)
- Plugins as the standard unit of function registration
- Planner strategies for multi-step goal decomposition
- A consistent Agent abstraction with group chat support
- Built-in Azure integrations for memory, search, and monitoring

---

## Core Concepts

### 1. The Kernel — IoC Container for AI Services

The Kernel is the central object in any SK application. Think of it as your
application's dependency injection container, but for AI services.

```python
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

kernel = Kernel()

# Register services — SK handles routing, retry, and fallback
kernel.add_service(
    AzureChatCompletion(
        deployment_name="gpt-4o",
        endpoint="https://your-resource.openai.azure.com/",
        api_key="...",          # or use Managed Identity
        service_id="primary",
    )
)
```

The Kernel decouples your application logic from specific AI providers. You can
swap Azure OpenAI for another provider by changing the service registration,
not your business logic. This mirrors how a DI container decouples application
code from infrastructure.

**What the Kernel manages:**
- AI service connections (chat completion, embeddings, text-to-image)
- Memory store connections (Azure AI Search, Redis, in-memory)
- Plugin registry — all functions the model can call
- Filter pipeline — middleware for function invocation (like ASP.NET filters)
- Prompt execution settings

### 2. Plugins — Structured Tool Definitions

A Plugin is a class whose methods are decorated with `@kernel_function`. Each
decorated method becomes a tool the model can call — SK handles the JSON schema
generation, registration, and invocation automatically.

```python
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_function_decorator import KernelFunctionMetadata

class DocumentPlugin:
    """Plugin for document operations. SK exposes these to the LLM."""

    @kernel_function(
        name="search_documents",
        description="Search the document store for content relevant to a query. "
                    "Use this when you need to find information from the knowledge base.",
    )
    def search(self, query: str) -> str:
        # Real implementation would call Azure AI Search
        return f"Search results for: {query}"

    @kernel_function(
        name="summarize_document",
        description="Summarize a document given its ID. Returns a concise summary.",
    )
    def summarize(self, document_id: str) -> str:
        return f"Summary of document {document_id}"
```

Compare this to the raw tool-calling loop from Module 3:

| Raw approach | Semantic Kernel Plugin |
|---|---|
| Manually write JSON schema for each tool | Inferred from type hints and docstrings via decorator |
| Manually route tool calls in your loop | SK invokes the function automatically |
| No standard registration | Registered once on the Kernel, available everywhere |
| No filter pipeline | Pre/post invocation filters for logging, auth, validation |

### 3. Planners — Multi-Step Goal Decomposition

A Planner takes a user goal and creates a plan — a sequence of Plugin function
calls that, when executed, accomplish the goal.

SK v1 ships with two planners worth knowing:

**Function Calling Planner (Recommended)**
Uses the model's native tool-calling capability. The model selects and sequences
functions the same way it does in a raw tool loop — but SK handles the
orchestration. This is the most reliable planner because it leverages the
model's native capability rather than a separate planning LLM call.

```python
from semantic_kernel.planners.function_choice_behavior import FunctionChoiceBehavior

# Tell SK to let the model choose functions automatically
execution_settings = AzureChatPromptExecutionSettings()
execution_settings.function_choice_behavior = FunctionChoiceBehavior.Auto()
```

**Handlebars Planner**
Generates a Handlebars template plan (an explicit sequence of steps) before
execution. The plan is inspectable and can be serialized. Useful when you
want to show the user "here is what I'm going to do before I do it."

```python
from semantic_kernel.planners.handlebars_planner import HandlebarsPlanner

planner = HandlebarsPlanner(kernel)
plan = await planner.create_plan(goal="Research the topic and write a summary report")
result = await plan.invoke(kernel)
```

The Handlebars planner makes two LLM calls: one to generate the plan (as a
Handlebars template), one to execute it. The function calling planner is
typically more efficient for single-user goals.

### 4. SK Agents

SK v1 introduces a first-class Agent abstraction, separate from the raw Kernel.

**ChatCompletionAgent**
A single agent backed by a chat completion model. Has:
- Instructions (system prompt)
- A set of Plugins (tools it can use)
- Conversation thread management

```python
from semantic_kernel.agents import ChatCompletionAgent

agent = ChatCompletionAgent(
    kernel=kernel,
    name="ResearchAgent",
    instructions="You are a research assistant. Use the search tool to find "
                 "information, then synthesize a clear answer.",
)
```

**AgentGroupChat**
Multiple agents taking turns in a conversation. Supports:
- Custom termination strategies (stop when an agent produces an approved output)
- Custom selection strategies (who speaks next)
- Shared conversation history visible to all agents

```python
from semantic_kernel.agents import AgentGroupChat

chat = AgentGroupChat(
    agents=[writer_agent, critic_agent],
    termination_strategy=...,   # custom or built-in
    selection_strategy=...,     # round-robin, LLM-based, custom
)
```

### 5. SK Memory and Vector Stores

SK's memory abstraction connects to vector stores (Azure AI Search, Redis,
Qdrant, etc.) for semantic search over stored content.

```python
from semantic_kernel.connectors.memory.azure_ai_search import AzureAISearchCollection

# SK wraps Azure AI Search with a consistent memory interface
collection = AzureAISearchCollection(
    collection_name="course-docs",
    data_model_type=DocumentRecord,
)
```

Memory in SK is explicit — you call `kernel.memory.search(query)` rather than
having the model automatically retrieve context. This gives you control over
when and how retrieval happens, which is important for production systems where
retrieval cost and latency matter.

---

## When to Choose Semantic Kernel

Use SK when:
- **You are an Azure-native shop.** SK's Azure integrations (Key Vault for
  secrets, App Insights for telemetry, Azure AI Search for memory, Managed
  Identity for auth) are better than any other framework.
- **You have a .NET team.** SK's C# SDK is production-grade and widely used
  in enterprise. The Python SDK follows the same architecture.
- **Production reliability matters.** SK has enterprise-grade retry, circuit
  breaking, and observability hooks built in.
- **You want explicit control over agent behavior.** SK does not hide the
  tool-calling loop — you can see exactly what's happening.

Avoid SK when:
- You need complex graph-based conditional routing (use LangGraph instead).
- You are prototyping quickly and want minimal boilerplate (use AutoGen or raw code).
- You need best-in-class Python tracing tooling (LangSmith + LangGraph has an edge here).

---

## Lab Tasks

### Setup

```bash
cd modules/module-17-semantic-kernel/lab
cp .env.example .env
# fill in your Azure OpenAI values
uv sync
uv run python src/sk_lab.py
```

### Task 1: Kernel and Plugin Setup

Configure a Kernel with Azure OpenAI. Create a Plugin with three functions:
- `search(query: str) -> str` — simulate a knowledge base search
- `summarize(text: str, max_words: int) -> str` — call the model to summarize
- `classify(text: str) -> str` — classify text into a category

Register the plugin on the kernel. Invoke a function directly (not through the
model) using `kernel.invoke()`. Observe how SK handles the invocation.

Goal: understand that plugins are just registered callables, and the model is
one consumer of them — not the only one.

### Task 2: ChatCompletionAgent with a Plugin

Create a `ChatCompletionAgent` backed by your plugin from Task 1. Run a
multi-turn conversation where the agent uses the search and summarize functions
to answer questions. Observe the tool call trace — compare it to the raw loop
you built in Module 3.

Questions to answer after completing:
- Where does SK inject the tool schemas into the prompt?
- Can you find where SK appends tool results to the message history?
- How does SK handle parallel tool calls?

### Task 3: Handlebars Planner

Give the Handlebars Planner a complex multi-step goal:
"Find information about Azure Container Apps, summarize the key features,
classify the technology category, then produce a briefing document."

Inspect the generated plan before executing it. Answer:
- Is the generated plan correct? Does it sequence the functions logically?
- What happens if you give it a goal that requires a function the kernel does
  not have? How does SK handle that?
- How many total LLM calls does this workflow make?

### Task 4: AgentGroupChat — Critic and Writer

Build an AgentGroupChat with two agents:

**WriterAgent** — instructions: "You write clear, concise technical summaries.
When asked to write something, produce a polished draft. Respond with your draft."

**CriticAgent** — instructions: "You review technical writing for clarity,
accuracy, and completeness. Review the writer's draft and either approve it by
saying APPROVED or provide specific feedback for improvement."

Termination strategy: stop when the critic says APPROVED or after 6 turns.

Task: give the group chat "Write a 3-paragraph explanation of how Kubernetes
handles pod scheduling." Observe the critique-revise loop.

### Task 5: RAG Agent with Azure AI Search

Connect SK to Azure AI Search as the memory store. Index 5-10 documents (use
course README files or any markdown content). Build an agent that:
1. Receives a user question
2. Uses `kernel.memory.search()` to retrieve relevant chunks
3. Includes retrieved chunks in the prompt context
4. Answers using only the retrieved content, citing sources

This is the same RAG pattern from Module 9, but now expressed in SK's
abstraction layer. Compare the two implementations: what did SK add? What
did it hide that you might need to see in production?

---

## Conceptual Checkpoints

Answer these before moving to Module 18:

1. **The Kernel as IoC container:** Explain how the Kernel's service registry
   decouples your application code from specific AI providers. What is the
   concrete benefit during a provider migration?

2. **Plugin vs raw tool schema:** You built raw JSON tool schemas in Module 3.
   What does SK's `@kernel_function` decorator add beyond what you wrote manually?
   What does it abstract away, and what does that abstraction cost you?

3. **Planner tradeoffs:** You ran both the Function Calling Planner and the
   Handlebars Planner. For a production agent that executes 10,000 requests/day,
   which would you choose and why? Consider LLM call count, plan inspectability,
   and error recovery.

4. **AgentGroupChat termination:** Your critic/writer group chat needs a
   termination condition. What happens without one? Describe two different
   termination strategies and the failure mode each protects against.

5. **SK vs LangGraph:** A colleague says "just use LangGraph, it handles
   conditional routing better." Under what circumstances is that colleague
   right? Under what circumstances would you push back and advocate for SK?

---

## Resources

- Semantic Kernel Python documentation:
  https://learn.microsoft.com/en-us/semantic-kernel/overview/
- SK GitHub (Python samples):
  https://github.com/microsoft/semantic-kernel/tree/main/python/samples
- SK Agents documentation:
  https://learn.microsoft.com/en-us/semantic-kernel/agents/
- SK memory / vector stores:
  https://learn.microsoft.com/en-us/semantic-kernel/memories/
- Azure AI Search connector:
  https://github.com/microsoft/semantic-kernel/tree/main/python/semantic_kernel/connectors/memory/azure_ai_search
