# Module 18: AutoGen

## Overview

AutoGen is Microsoft Research's framework for multi-agent conversational AI.
Where Semantic Kernel models agent behavior as task execution (plugins,
planners, function invocation), AutoGen models it as conversation: agents
take turns speaking, and the conversation itself is the computation.

This framing makes AutoGen particularly powerful for tasks that benefit from
iterative refinement, code generation, and adversarial review — anywhere you
want agents to challenge and improve each other's outputs through dialogue.

AutoGen's killer feature is code execution. An AssistantAgent can write Python
code; a UserProxyAgent can execute it in a sandboxed environment and feed the
result back. This loop — write, execute, observe, revise — is remarkably
effective for data analysis, automation scripting, and problem-solving tasks.

---

## Why AutoGen's Model Is Different

In Semantic Kernel, the developer orchestrates the agents. You call the planner,
which calls functions, which return results, which go into a prompt. Control
flow is in your code.

In AutoGen, the agents orchestrate each other. You set up the agents and the
group chat, give them a task, and they converse until they solve it. Control
flow is in the conversation.

This distinction matters:

| | Semantic Kernel | AutoGen |
|---|---|---|
| Control flow | In your code (explicit) | In the conversation (emergent) |
| Best for | Structured pipelines, Azure enterprise | Exploratory tasks, code generation |
| Debuggability | High (explicit call graph) | Medium (conversation logs) |
| Production hardening | High | Medium (research origins) |
| Code execution | Manual (you execute) | First-class (agent executes) |

---

## Core Concepts

### 1. AssistantAgent

An AssistantAgent wraps an LLM and gives it a system message and optional tool
definitions. It generates responses — text, code, tool calls — but does not
execute anything itself.

```python
from autogen import AssistantAgent

assistant = AssistantAgent(
    name="Planner",
    system_message=(
        "You are a software architect. When given a problem, produce a "
        "step-by-step implementation plan. Be specific about what each "
        "function should do and what its inputs/outputs are."
    ),
    llm_config={
        "config_list": [{
            "model": "gpt-4o",
            "api_type": "azure",
            "base_url": "https://your-resource.openai.azure.com/",
            "api_key": "...",
            "api_version": "2024-02-01",
        }]
    },
)
```

The `llm_config` dict is AutoGen's way of passing Azure OpenAI configuration.
The `config_list` supports multiple model configurations with automatic
failover — useful for managing rate limits across deployments.

### 2. UserProxyAgent

The UserProxyAgent represents an entity that can execute code and tools on
behalf of the conversation. It bridges the gap between LLM output and real-
world execution.

Key parameters:
- `human_input_mode`: `"NEVER"` (fully automated), `"TERMINATE"` (only at
  end), `"ALWAYS"` (human approves every step)
- `code_execution_config`: controls how and where code is executed
- `is_termination_msg`: a function that returns True when the conversation
  should end

```python
from autogen import UserProxyAgent

user_proxy = UserProxyAgent(
    name="Executor",
    human_input_mode="NEVER",       # fully automated
    code_execution_config={
        "executor": "docker",       # safe: runs in Docker container
        "work_dir": "/tmp/autogen_work",
        "timeout": 60,
    },
    is_termination_msg=lambda msg: "TERMINATE" in msg.get("content", ""),
)
```

### 3. The Conversation Loop

When you call `user_proxy.initiate_chat(assistant, message="...")`, AutoGen
starts a conversation loop:

```
1. UserProxy sends the initial message to AssistantAgent
2. AssistantAgent generates a response (may include code blocks)
3. UserProxy checks: does this contain code? Execute it.
4. UserProxy sends the execution result back to AssistantAgent
5. AssistantAgent refines its response based on the result
6. Loop continues until is_termination_msg() returns True
```

This is the raw tool-calling loop from Module 3, generalized to arbitrary
agents. The "tool call" is now any code block the assistant generates, and the
"tool executor" is the UserProxyAgent.

### 4. GroupChat — Multi-Agent Conversations

GroupChat coordinates N agents taking turns. A GroupChatManager (itself an
LLM-backed agent) decides who speaks next based on the conversation history.

```python
from autogen import GroupChat, GroupChatManager

# Build individual agents
planner = AssistantAgent(name="Planner", ...)
coder = AssistantAgent(name="Coder", ...)
tester = AssistantAgent(name="Tester", ...)

# Wire them into a group chat
group_chat = GroupChat(
    agents=[planner, coder, tester],
    messages=[],
    max_round=20,
    speaker_selection_method="auto",   # LLM decides who speaks next
)

manager = GroupChatManager(
    groupchat=group_chat,
    llm_config=llm_config,
)

# Kick off the conversation
user_proxy.initiate_chat(manager, message="Build and test a binary search function.")
```

**Speaker selection methods:**
- `"auto"`: the GroupChatManager LLM decides who speaks next (most flexible,
  costs an extra LLM call per turn)
- `"round_robin"`: agents take turns in order (predictable, cheap)
- `"random"`: random selection (rarely useful)
- Custom function: you write the selection logic (deterministic, testable)

### 5. Code Execution Safety

AutoGen's code execution is powerful and dangerous. An LLM generating arbitrary
Python that runs on your machine is a significant attack surface.

**Local subprocess (default — not for production):**
```python
code_execution_config={
    "work_dir": "/tmp/work",
    "use_docker": False,   # runs directly in your Python process
}
```

**Docker executor (recommended for anything beyond local dev):**
```python
code_execution_config={
    "executor": "docker",
    "docker_image": "python:3.11-slim",
    "work_dir": "/tmp/work",
    "timeout": 30,          # seconds before execution is killed
}
```

The Docker executor runs each code block in a fresh container, isolated from
your host filesystem and network. This limits — but does not eliminate — the
blast radius of a misbehaving agent.

**Additional safeguards to implement:**
- Allowlist only specific Python packages in the Docker image
- Mount a read-only filesystem except for a specific work directory
- Set memory and CPU limits on the container
- Log all executed code for audit

### 6. Termination Conditions

Without a termination condition, AutoGen conversations run until `max_round`
is hit. Good termination conditions:

```python
# Terminate when any agent says TERMINATE
is_termination_msg=lambda msg: "TERMINATE" in msg.get("content", "")

# Terminate when a specific agent approves the output
is_termination_msg=lambda msg: (
    msg.get("name") == "Tester" and "APPROVED" in msg.get("content", "")
)

# Terminate after max turns (belt + suspenders with max_round)
# ... set max_round in GroupChat instead
```

---

## When to Choose AutoGen

Use AutoGen when:
- **Code generation is core to the task.** AutoGen's write/execute/observe loop
  is unmatched for data analysis, automation scripting, and exploratory coding.
- **You want emergent agent collaboration.** When you do not know the exact
  sequence of steps in advance, letting agents negotiate the approach via
  conversation often works better than explicit orchestration.
- **Prototyping and research.** AutoGen's flexibility and minimal boilerplate
  make it fast to experiment with new multi-agent patterns.

Avoid AutoGen when:
- **You need deterministic, auditable workflows.** Emergent conversation is
  hard to predict and test. Use LangGraph or SK for pipelines where the steps
  must be guaranteed.
- **Production enterprise requirements.** AutoGen does not have SK's Azure
  integration depth. Key Vault, Managed Identity, App Insights integration
  require custom work.
- **Security-sensitive environments.** Code execution by an LLM is a hard sell
  to a security team without significant additional safeguards.

---

## Lab Tasks

### Setup

```bash
cd modules/module-18-autogen/lab
cp .env.example .env
# fill in your Azure OpenAI values
uv sync
uv run python src/autogen_lab.py
```

### Task 1: AssistantAgent + UserProxyAgent Basics

Create an AssistantAgent and UserProxyAgent. Give the assistant a task that
requires writing code:
"Write a Python function that computes the Levenshtein distance between two
strings. Include a test case. Then say TERMINATE."

Let the UserProxy execute the generated code. Observe the conversation loop.

Questions to answer:
- How many turns did the conversation take?
- Did the assistant correct itself after seeing the execution result?
- What happens if the generated code has a bug? Does the agent self-correct?

### Task 2: GroupChat — Planner, Coder, Tester

Build a 3-agent group chat:
- **PlannerAgent**: breaks problems into subtasks, does not write code
- **CoderAgent**: implements the plan, writes Python code
- **TesterAgent**: reviews the code for correctness and says "APPROVED" when
  satisfied or provides specific feedback

Task: "Build and test a Python module with two functions: `merge_sorted_lists`
that merges two sorted lists into one sorted list, and `binary_search` that
finds a target in a sorted list. Include docstrings and unit tests."

Use `speaker_selection_method="round_robin"` first, then switch to `"auto"`.
Compare the results — does automatic selection produce better outcomes?

### Task 3: Docker Executor Configuration

Switch the code execution backend from local subprocess to Docker.

Configure the Docker executor with:
- A `python:3.11-slim` base image
- 30-second execution timeout
- A specific work directory

Re-run Task 1's conversation through Docker. Verify that:
- Code executes inside the container (not on the host)
- Timeout fires correctly for infinite loops (test with `while True: pass`)
- The conversation recovers gracefully when execution times out

### Task 4: Research Pipeline with Tool-Calling Agents

Build a pipeline where agents use simulated tool calls (not code execution)
to research a topic and produce a report.

Define two tools:
- `web_search(query: str) -> str` — returns a stub result with fake "articles"
- `fetch_article(url: str) -> str` — returns stub article content

Create a ResearchAgent that uses these tools to gather information and a
WriterAgent that synthesizes the results into a structured report.

The report must have: Executive Summary, Key Findings (3 bullets), Sources.

### Task 5: Custom GroupChatManager Speaker Selection

Replace AutoGen's LLM-based speaker selection with a deterministic router.

Rules:
- After UserProxy: always go to Planner
- After Planner: always go to Coder
- After Coder: always go to Tester
- After Tester: if APPROVED, end; otherwise go to Coder

Implement this as a custom `speaker_selection_method` function. Verify that
the routing is deterministic — run the same task twice and confirm the agent
order is identical both times.

Reflect: when does deterministic routing outperform LLM-based selection?
When does it fail?

---

## Conceptual Checkpoints

Answer these before moving to Module 19:

1. **Conversation as computation:** Explain AutoGen's model of agent interaction
   in one paragraph. What problem does it solve that explicit orchestration
   (like SK's planner) does not? What problem does it create?

2. **Code execution trust model:** Your AutoGen app runs in production.
   A user can provide arbitrary task descriptions. What are the top 3 security
   risks of allowing the LLM to generate and execute code? What controls would
   you require before approving this for production?

3. **GroupChat speaker selection:** You have a 4-agent group chat. The
   LLM-based manager costs one extra API call per turn. Your task takes an
   average of 15 turns. At $0.01/1k tokens and 500 tokens per manager call,
   what is the extra cost per task? Is that acceptable? When would you switch
   to deterministic routing?

4. **Termination design:** A poorly designed termination condition causes an
   AutoGen group chat to run for 200 turns. What are the operational
   consequences? Design a robust termination strategy that handles: (a) normal
   completion, (b) agent stuck in a loop, (c) code execution repeatedly failing.

5. **AutoGen vs Semantic Kernel for your use case:** You are building an AI
   feature for an internal developer portal that helps engineers debug CI/CD
   pipeline failures by reading logs and suggesting fixes. Which framework
   would you choose? Justify with at least three concrete reasons.

---

## Resources

- AutoGen documentation: https://microsoft.github.io/autogen/
- AutoGen GitHub: https://github.com/microsoft/autogen
- AutoGen with Azure OpenAI:
  https://microsoft.github.io/autogen/docs/topics/non-openai-models/cloud-azure-openai/
- Docker code executor:
  https://microsoft.github.io/autogen/docs/reference/coding/docker_commandline_code_executor/
- AutoGen research paper (helpful for understanding the design philosophy):
  https://arxiv.org/abs/2308.08155
