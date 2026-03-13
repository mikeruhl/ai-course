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

**Goal:** Observe AutoGen's write-execute-observe conversation loop, where the LLM generates code and the UserProxyAgent executes it.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-18-autogen\lab\src\autogen_lab.py` and locate `build_llm_config()` (line 42). Fill in the `config_list` entry using the environment variables `ENDPOINT`, `API_KEY`, `DEPLOYMENT`, and `API_VERSION` defined at the top of the file.
2. In `task1_basic_code_loop()` (line 72), create an `AssistantAgent` named `"Coder"` with a system_message instructing it to write Python code to solve problems, test the code, and say `TERMINATE` when done. Pass `llm_config` to the agent.
3. Create a `UserProxyAgent` named `"Executor"` with `human_input_mode="NEVER"`, `code_execution_config={"work_dir": "/tmp/autogen_task1", "use_docker": False}`, and `is_termination_msg=lambda msg: "TERMINATE" in msg.get("content", "")`.
4. Call `user_proxy.initiate_chat(assistant, message=task)` with the Levenshtein distance task already defined in the function (lines 90-95).
5. After the conversation, print the total turn count from `len(user_proxy.chat_messages[assistant])` and whether it ended with TERMINATE or hit max_round.
6. Run:
   ```bash
   uv run python src/autogen_lab.py
   ```

**Expected result:**
```
──────────── Task 1: AssistantAgent + UserProxyAgent ────────────
Coder (to Executor):
```python
def levenshtein_distance(s1: str, s2: str) -> int:
    ...
```

Executor (to Coder):
exitcode: 0 (execution succeeded)
ALL TESTS PASSED

Coder (to Executor):
TERMINATE

Total turns: 3
Ended with: TERMINATE
```
- The assistant writes the function with tests, the executor runs it, and the conversation ends on success.
- If the code has a bug, the executor returns the traceback and the assistant self-corrects — adding 1-2 extra turns.

**Why this matters:**
This is AutoGen's core value proposition: the conversation loop automates the write/run/fix cycle. In production, this pattern powers data analysis agents that write SQL or Python, execute it, observe errors, and iterate — without human intervention. The risk is unbounded iteration; the `is_termination_msg` function is your primary guard against runaway loops.

### Task 2: GroupChat — Planner, Coder, Tester

**Goal:** Compare round-robin vs. LLM-based speaker selection in a multi-agent group chat.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-18-autogen\lab\src\autogen_lab.py` and locate `task2_group_chat()` (line 111).
2. Create three `AssistantAgent` instances with `llm_config`: `Planner` (system_message: breaks problems into steps, does NOT write code), `Coder` (implements the plan in Python with docstrings), and `Tester` (reviews code for correctness, says `APPROVED` if acceptable or provides numbered feedback).
3. Create a `UserProxyAgent` named `"Executor"` with `human_input_mode="NEVER"` and a termination condition that stops when the Tester says `APPROVED`.
4. Import `GroupChat` and `GroupChatManager` from `autogen`. Create a `GroupChat` with `agents=[user_proxy, planner, coder, tester]`, `max_round=15`, and `speaker_selection_method="round_robin"`. Create a `GroupChatManager` backed by `llm_config`.
5. Run with the `merge_sorted_lists` / `binary_search` task already defined in the function (lines 145-151). Record the speaker sequence and turn count.
6. Switch to `speaker_selection_method="auto"` and run the same task again. Compare which approach produces better results and how many turns each took.
7. Run:
   ```bash
   uv run python src/autogen_lab.py
   ```

**Expected result:**
```
──────────── Task 2: GroupChat — Planner, Coder, Tester ────────────
[Round Robin] Speaker order: Executor → Planner → Coder → Tester → Coder → Tester → ...
[Round Robin] Total turns: 8, Tester approved: True

[Auto] Speaker order: Executor → Planner → Coder → Tester → Coder → Tester → ...
[Auto] Total turns: 6, Tester approved: True
```
- Round-robin forces every agent to speak in fixed order, even when a step is unnecessary (e.g., Planner re-planning after a minor code fix).
- Auto selection skips agents that have nothing to contribute, typically finishing in fewer turns.

**Why this matters:**
LLM-based speaker selection costs one extra API call per turn but produces more natural conversation flow. At 15 turns with `"auto"`, that is 15 additional LLM calls just for routing. For high-volume production workloads, deterministic routing (Task 5) eliminates this cost while maintaining predictability.

### Task 3: Docker Executor Configuration

**Goal:** Run LLM-generated code in a sandboxed Docker container with timeout enforcement, demonstrating the production safety pattern.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-18-autogen\lab\src\autogen_lab.py` and locate `task3_docker_executor()` (line 164).
2. Create the same `AssistantAgent` ("Coder") and `UserProxyAgent` ("Executor") pair as Task 1, but change `code_execution_config` to `{"executor": "docker", "docker_image": "python:3.11-slim", "work_dir": "/tmp/autogen_docker", "timeout": 30}`. Alternatively, use the newer `autogen.coding.DockerCommandLineCodeExecutor` API depending on your pyautogen version.
3. Re-run the Levenshtein distance task through Docker. Verify that execution completes successfully.
4. Test timeout handling: give the agent a task that involves code with an infinite loop (e.g., `"Write Python code that runs 'while True: pass' for 60 seconds."`). The Docker executor should kill it after 30 seconds. Observe how the agent responds to the timeout error—does it self-correct?
5. If the executor exposes the Docker container ID, print it to confirm code ran in Docker, not on the host.
6. Run:
   ```bash
   uv run python src/autogen_lab.py
   ```

**Expected result:**
```
──────────── Task 3: Docker Executor ────────────
Coder (to Executor):
```python
def levenshtein_distance(s1, s2): ...
```

Executor (to Coder):
exitcode: 0 (execution succeeded)
ALL TESTS PASSED

--- Timeout test ---
Executor (to Coder):
exitcode: 1 (execution failed)
Timeout: code execution exceeded 30 seconds.

Coder (to Executor):
The code timed out due to an infinite loop. Here is a corrected version...
```
- Code runs inside the Docker container, not on the host machine.
- The 30-second timeout kills the infinite loop. The agent sees the timeout error and attempts to self-correct.

**Why this matters:**
An LLM generating arbitrary Python that runs on your host is a security liability. Docker isolation limits the blast radius: no host filesystem access, no network access (if configured), and hard timeout enforcement. In production, combine Docker with CPU/memory limits and a package allowlist to further constrain the execution environment.

### Task 4: Research Pipeline with Tool-Calling Agents

**Goal:** Build a multi-agent pipeline that uses simulated tool calls (not code execution) to research a topic and produce a structured report.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-18-autogen\lab\src\autogen_lab.py` and locate `task4_research_pipeline()` (line 197). The `web_search` (line 203) and `fetch_article` (line 226) stub functions are already defined.
2. Register `web_search` and `fetch_article` as AutoGen tools. Use the `@assistant.register_for_llm` and `@user_proxy.register_for_execution` decorators, or the `FunctionCallingAgent` API depending on your installed pyautogen version. Check the AutoGen docs for your version.
3. Create a `ResearchAgent` (AssistantAgent) with instructions to: (1) use `web_search` to find information about the topic, (2) use `fetch_article` to get details from 2 articles, (3) synthesize findings and say TERMINATE when done.
4. Create a `WriterAgent` (AssistantAgent) that takes the ResearchAgent's findings and produces a structured report with: Executive Summary (2 sentences), Key Findings (3 bullet points), and Sources (URLs cited).
5. Run the pipeline with the topic `"Azure Container Apps architecture"`.
6. Run:
   ```bash
   uv run python src/autogen_lab.py
   ```

**Expected result:**
```
──────────── Task 4: Research Pipeline with Tools ────────────
ResearchAgent (to Executor):
[Tool call] web_search(query="Azure Container Apps architecture")
[Tool result] Azure Container Apps is a serverless container platform...

[Tool call] fetch_article(url="aca.example.com")
[Tool result] Content of aca.example.com: This is a detailed technical article...

WriterAgent:
Executive Summary: Azure Container Apps is a serverless platform for running
containerized workloads. It provides managed scaling and Azure service integration.

Key Findings:
- Serverless container hosting with automatic scaling
- Integrates with Azure services via managed control plane
- Supports event-driven architectures

Sources: aca.example.com, scale.example.com
```
- The ResearchAgent calls tools to gather data; the WriterAgent synthesizes it into the required format.
- Tool calls appear in the conversation history as structured function calls, not code blocks.

**Why this matters:**
This pattern separates research (tool-calling) from synthesis (writing). In production, the `web_search` stub would be replaced with Bing Search API or Azure AI Search. The structured report format ensures consistent output shape, which matters when downstream systems parse the agent's output programmatically.

### Task 5: Custom GroupChatManager Speaker Selection

**Goal:** Replace LLM-based speaker selection with a deterministic routing function and verify reproducible agent ordering.

**What to do:**
1. Open `C:\Users\MiRuh\source\learn\ai-course\modules\module-18-autogen\lab\src\autogen_lab.py` and locate `task5_custom_speaker_selection()` (line 262).
2. Implement `custom_speaker_selector(last_speaker, groupchat)` (line 273) with these routing rules: UserProxy → Planner, Planner → Coder, Coder → Tester, Tester → Coder (if not `APPROVED`) or END. Use `last_speaker.name` to identify the current speaker and `groupchat.messages[-1]["content"]` to check for `APPROVED`. Use a helper like `agent_by_name(name)` to look up agents from `groupchat.agents`.
3. Create Planner, Coder, and Tester agents (same as Task 2).
4. Create a `GroupChat` with `speaker_selection_method=custom_speaker_selector` and a `GroupChatManager` backed by `llm_config`.
5. Run the same task as Task 2 **twice** with identical input. Print the full sequence of speakers for each run and verify they are identical (deterministic).
6. Add a comment reflecting: in what scenarios does deterministic routing break down? (Hint: think about what happens when Tester gives feedback but there is no Planner re-plan step in the routing.)
7. Run:
   ```bash
   uv run python src/autogen_lab.py
   ```

**Expected result:**
```
──────────── Task 5: Custom Deterministic Speaker Selection ────────────
Run 1 speaker order: Executor → Planner → Coder → Tester → Coder → Tester(APPROVED)
Run 2 speaker order: Executor → Planner → Coder → Tester → Coder → Tester(APPROVED)
Deterministic: True (sequences match)
```
- The agent order is identical across both runs — no randomness from an LLM-based selector.
- No extra LLM calls for speaker selection (saves cost at scale).

**Why this matters:**
Deterministic routing makes agent behavior reproducible and testable. It eliminates the per-turn LLM call cost of `"auto"` selection. The failure mode: when the Tester gives feedback that requires re-planning (not just re-coding), the fixed Tester → Coder route skips the Planner. Deterministic routing works when the task structure is predictable; it breaks when agents need to dynamically adapt the workflow.

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
