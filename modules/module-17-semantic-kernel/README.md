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

**Goal:** Build a configured Semantic Kernel with registered plugins and invoke plugin functions directly, demonstrating that SK plugins are callable by your code without requiring an LLM interaction.

**What to do:**
1. Open `lab/src/sk_lab.py` and locate `build_kernel()` (line 40). Import `Kernel` from `semantic_kernel` and `AzureChatCompletion` from `semantic_kernel.connectors.ai.open_ai`, instantiate the kernel, and add the Azure OpenAI service using `ENDPOINT`, `API_KEY`, and `DEPLOYMENT` variables.
2. In the `CoursePlugin` class (line 60), add `@kernel_function` decorators to the `search`, `summarize`, and `classify` methods. Each decorator needs a `name` and `description`. Implement each method as a stub returning a simple string that includes the input parameter so you can verify arguments are passed correctly.
3. In `task1_kernel_and_plugin()` (line 116), register `CoursePlugin` on the kernel with `kernel.add_plugin(CoursePlugin(), plugin_name="CoursePlugin")`, then invoke the `search` function directly via `await kernel.invoke(plugin_name="CoursePlugin", function_name="search", query="Azure Container Apps")`. Print the result.
4. List all registered functions on the kernel by iterating through `kernel.plugins`. Also invoke the `classify` function directly with sample text and print the result.
5. Run the lab:
   ```bash
   uv run python src/sk_lab.py
   ```

**Expected result:**
```
──────────── Task 1: Kernel and Plugin Setup ────────────
Search result: Found 3 documents about 'Azure Container Apps': [doc1, doc2, doc3]
Registered functions: CoursePlugin-search, CoursePlugin-summarize, CoursePlugin-classify
Classify result: technology
```
You should see the direct invocation return the stub string without any LLM call. The `kernel.plugins` output lists all three functions with their auto-generated schemas derived from the decorator metadata.

**Why this matters:**
SK plugins decouple function registration from invocation. In production systems, the same plugin serves both programmatic callers (your orchestration code) and the model's tool-calling loop. This architectural separation lets you unit-test plugin functions in isolation without mocking the LLM, and it ensures your tools work correctly before exposing them to the model.

### Task 2: ChatCompletionAgent with a Plugin

**Goal:** Build a multi-turn conversational agent using SK's ChatCompletionAgent that automatically calls plugin functions via the tool-calling loop you manually implemented in Module 3.

**What to do:**
1. Open `lab/src/sk_lab.py` and locate `task2_chat_completion_agent()` (line 144).
2. Register `CoursePlugin` on the kernel with `kernel.add_plugin(CoursePlugin(), plugin_name="CoursePlugin")`.
3. Import `ChatCompletionAgent` from `semantic_kernel.agents` and create an agent with `kernel=kernel`, `name="ResearchAssistant"`, and `instructions` containing a system prompt telling it to use the search tool to find information before answering questions.
4. Send the agent a first message: `"What do you know about Semantic Kernel's architecture?"` using the agent's chat invocation API. Print the response.
5. Follow up with a second message in the same conversation: `"Summarize what you found in 50 words or less."` This should trigger the `summarize` function. Print the response.
6. After the conversation completes, inspect and print the full message history. Look for `tool_calls` entries in the messages and observe the structure: AIMessage with tool_calls, followed by ToolMessage with results.
7. Run:
   ```bash
   uv run python src/sk_lab.py
   ```

**Expected result:**
```
──────────── Task 2: ChatCompletionAgent ────────────
[ResearchAssistant] Tool call: search(query="Semantic Kernel architecture")
[ResearchAssistant] Found 3 documents about 'Semantic Kernel architecture': [doc1, doc2, doc3]
[ResearchAssistant] Semantic Kernel is a framework that uses a Kernel as an IoC container...

[ResearchAssistant] Tool call: summarize(text="...", max_words=50)
[ResearchAssistant] Summary (50 words): SK centralizes AI services through a Kernel...
```
The message history will contain `tool_calls` entries in AIMessage objects followed by tool result messages, structurally identical to the raw loop from Module 3. SK automatically injected the tool schemas from the `@kernel_function` decorators—you wrote no JSON schemas manually.

**Why this matters:**
Compare the code you just wrote to the manual tool-calling loop in Module 3. SK eliminated JSON schema authoring, the tool dispatch switch statement, and explicit message history management. The tradeoff: debugging now requires understanding SK's internal message flow and plugin execution pipeline rather than your own explicit loop. This abstraction accelerates development but adds a layer of indirection when troubleshooting.

### Task 3: Handlebars Planner

**Goal:** Use the Handlebars Planner to decompose a multi-step goal into an inspectable, serializable Handlebars template plan, then execute it and count the LLM calls.

**What to do:**
1. Open `lab/src/sk_lab.py` and locate `task3_handlebars_planner()` (line 177).
2. Register `CoursePlugin` on the kernel with `kernel.add_plugin(CoursePlugin(), plugin_name="CoursePlugin")`.
3. Import `HandlebarsPlanner` from `semantic_kernel.planners.handlebars_planner`, create an instance with `planner = HandlebarsPlanner(kernel)`, then call `await planner.create_plan(goal)` using the `goal` string already defined in the function (lines 188-191).
4. Print the raw Handlebars template plan before executing it. Inspect the template to see the exact function sequence the planner generated: which functions did it select and in what order?
5. Execute the plan with `await plan.invoke(kernel)` and print the final result.
6. Count and document how many LLM calls were made: 1 for plan generation + 1 for plan execution = 2 total. Add a comment explaining this count.
7. Run:
   ```bash
   uv run python src/sk_lab.py
   ```

**Expected result:**
```
──────────── Task 3: Handlebars Planner ────────────
Generated Plan (Handlebars template):
{{#with (CoursePlugin-search query="Azure Container Apps")}}
  {{#with (CoursePlugin-summarize text=this max_words=100)}}
    {{#with (CoursePlugin-classify text=this)}}
      Briefing: Category={{this}}, Summary={{../this}}
    {{/with}}
  {{/with}}
{{/with}}

Executing plan...
Result: Briefing: Category=technology, Summary=Azure Container Apps is a serverless...
LLM calls: 2 (1 plan generation + 1 plan execution)
```
The plan template shows the exact function sequence: search → summarize → classify. The planner selected these three functions and chained them with nested `{{#with}}` blocks for data flow. Two LLM calls total.

**Why this matters:**
The Handlebars planner makes the execution plan inspectable and serializable before it runs. In a production system processing 10,000 requests/day, the Function Calling Planner (single LLM call, native tool use) is more cost-efficient—half the API cost per request. The Handlebars planner is valuable in regulated industries where you need to show a human "here is exactly what I will do" before execution—an audit trail requirement. The tradeoff: extra latency and cost for inspectability.

### Task 4: AgentGroupChat — Critic and Writer

**Goal:** Build a multi-agent critique-and-revise loop using SK's AgentGroupChat with a custom termination strategy that stops when the critic approves the output.

**What to do:**
1. Open `lab/src/sk_lab.py` and locate `task4_agent_group_chat()` (line 210).
2. Build a kernel with `build_kernel()`. You can use a shared kernel instance for both agents or create separate instances—start with a shared kernel (simpler).
3. Create two `ChatCompletionAgent` instances:
   - `WriterAgent` with `name="WriterAgent"` and `instructions`: "You write clear, concise technical summaries. When given a topic, produce a polished draft. Respond with only your draft text."
   - `CriticAgent` with `name="CriticAgent"` and `instructions`: "You review technical writing. Evaluate the draft for clarity, accuracy, and completeness. If it is acceptable, respond with 'APPROVED'. If not, provide specific numbered feedback for improvement."
4. Import `AgentGroupChat` from `semantic_kernel.agents` and create a group chat with `agents=[writer_agent, critic_agent]`. Configure a termination strategy that stops when the critic says `APPROVED` or after 6 turns maximum. Look at `KernelFunctionTerminationStrategy` or `DefaultTerminationStrategy` in SK docs/samples for implementation guidance.
5. Add the task message (defined at line 238-241) as the initial user message and invoke the group chat. As responses come in, print each agent's output labeled with the agent's name.
6. After the conversation ends, print how many turns it took and whether the critic approved the output.
7. Run:
   ```bash
   uv run python src/sk_lab.py
   ```

**Expected result:**
```
──────────── Task 4: AgentGroupChat — Critic + Writer ────────────
[WriterAgent] Kubernetes scheduling is the process by which the kube-scheduler assigns pods...
[CriticAgent] Feedback: 1. Add mention of taints/tolerations. 2. Clarify resource requests vs limits.
[WriterAgent] (revised) The kube-scheduler evaluates nodes using predicates and priorities...
[CriticAgent] APPROVED
Total turns: 4
Critic approved: True
```
The writer revises based on the critic's numbered feedback. The loop terminates when `APPROVED` appears in the critic's message, not at the 6-turn max limit. The final draft is measurably better than the first draft.

**Why this matters:**
Without a termination condition, multi-agent loops run until `max_round`—burning tokens and budget on diminishing returns. The two-agent critic/writer pattern is production-grade for improving output quality: one agent generates, one evaluates, iterate until acceptable. The key design decision is the termination strategy: too strict and the loop ends before the output is good; too loose and you waste LLM calls after the output has already converged. Monitor turn counts in production to tune this threshold.

### Task 5: RAG Agent with Azure AI Search

**Goal:** Integrate SK with Azure AI Search as a memory store and build a retrieval-augmented generation (RAG) agent that cites sources, comparing SK's abstraction to the manual RAG pattern from Module 9.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-17-semantic-kernel\lab\src\sk_lab.py` and locate `task5_rag_agent()` (line 255). Set `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_KEY`, and `AZURE_SEARCH_INDEX` in your `.env` file. If these are not configured, the function will skip this task.
2. Build a kernel configured for both Azure OpenAI and Azure AI Search. Import `AzureAISearchCollection` from `semantic_kernel.connectors.memory.azure_ai_search`. Define a data model using a dataclass with the `@vectorstoremodel` decorator, or use SK's built-in `TextMemoryPlugin`.
3. Index sample documents: read 2-3 README.md files from this repo (e.g., module-17, module-03, module-09) and store them in the Azure AI Search index via SK's memory API. Each document needs an ID, text content, and an embedding vector. SK can generate embeddings automatically if you add an embedding service to the kernel.
4. Build a RAG agent with the following logic:
   - Receive a user question
   - Call `kernel.memory.search(query, collection=search_index, limit=3)` to retrieve relevant chunks
   - Format the retrieved chunks as context in the prompt
   - Generate an answer using only the retrieved content
   - Cite which source document each piece of information came from
5. Test with three queries: `"What is Semantic Kernel?"`, `"How does the agent loop work?"`, `"What is Azure Container Apps?"`. For each query, print the retrieved chunks with relevance scores, then print the agent's answer with source citations.
6. Run:
   ```bash
   uv run python src/sk_lab.py
   ```

**Expected result:**
```
──────────── Task 5: RAG Agent with Azure AI Search ────────────
Query: "What is Semantic Kernel?"
Retrieved 3 chunks from index 'sk-module-docs'
  [1] module-17/README.md (relevance: 0.92)
  [2] module-03/README.md (relevance: 0.71)
  [3] module-09/README.md (relevance: 0.65)
Answer: Semantic Kernel is Microsoft's open-source SDK for building AI-powered
applications with a Kernel-based IoC container pattern... [Source: module-17/README.md]
```
Each answer cites which source document the information came from. Compare to Module 9: SK abstracts the embedding call, index query, and prompt injection into a single `memory.search()` call. The tradeoff is reduced visibility into retrieval scores and chunk boundaries.

**Why this matters:**
SK's memory abstraction reduces RAG boilerplate significantly—no manual embedding generation, no direct Azure SDK calls, no prompt template management. But it hides retrieval details that matter in production: chunk overlap strategy, relevance score thresholds, hybrid search configuration (keyword + vector), and re-ranking logic. If your retrieval quality drops in production, you must debug inside SK's memory connector code, not just your application layer. Evaluate whether the development time savings justify the reduced observability and debugging complexity.

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
