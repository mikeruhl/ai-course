"""
Module 18 Lab — AutoGen
========================
Tasks:
  1. AssistantAgent + UserProxyAgent: write code, execute it, self-correct
  2. GroupChat with Planner/Coder/Tester — round-robin vs auto speaker selection
  3. Docker executor: safe sandboxed code execution, timeout handling
  4. Research pipeline with simulated tool-calling agents
  5. Custom GroupChatManager: deterministic speaker routing

Run with:
    uv run python src/autogen_lab.py

Complete tasks in order. Comment out tasks you have already completed.

NOTE: AutoGen conversations print directly to stdout. Use the task separators
printed by this script to follow which task is executing.
"""

import os
from typing import Optional

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
# Shared: build the AutoGen LLM config for Azure OpenAI
# ---------------------------------------------------------------------------

def build_llm_config() -> dict:
    """
    Return an AutoGen-compatible llm_config dict for Azure OpenAI.

    AutoGen's llm_config format uses a config_list (supports failover):
        {
            "config_list": [
                {
                    "model": "<deployment name>",
                    "api_type": "azure",
                    "base_url": "<endpoint>",
                    "api_key": "<key>",
                    "api_version": "<version>",
                }
            ],
            "temperature": 0,
            "timeout": 60,
        }

    TODO: Fill in the config_list entry using env vars loaded above.
    Return the full config dict.
    """
    # TODO: implement this function
    raise NotImplementedError("build_llm_config() is not yet implemented")


# ---------------------------------------------------------------------------
# Task 1: AssistantAgent + UserProxyAgent — code write/execute loop
# ---------------------------------------------------------------------------

def task1_basic_code_loop():
    console.print(Rule("[bold blue]Task 1: AssistantAgent + UserProxyAgent"))

    llm_config = build_llm_config()

    # TODO: Create an AssistantAgent.
    # Import: from autogen import AssistantAgent
    # Name it "Coder". Give it a system message explaining it should write
    # Python code to solve problems, test the code, and say TERMINATE when done.

    # TODO: Create a UserProxyAgent.
    # Import: from autogen import UserProxyAgent
    # Name it "Executor".
    # human_input_mode="NEVER" (fully automated)
    # code_execution_config: use local subprocess for Task 1.
    #   {"work_dir": "/tmp/autogen_task1", "use_docker": False}
    # is_termination_msg: stop when the assistant says TERMINATE.

    task = (
        "Write a Python function called levenshtein_distance(s1: str, s2: str) -> int "
        "that computes the Levenshtein distance between two strings. "
        "Include 5 test cases. Run the tests. If all pass, print 'ALL TESTS PASSED' "
        "and then say TERMINATE."
    )

    # TODO: Call user_proxy.initiate_chat(assistant, message=task).
    # Watch the conversation loop in stdout.

    # TODO: After the conversation ends, print:
    #   - Total number of turns (len(user_proxy.chat_messages[assistant]))
    #   - Whether the conversation ended with TERMINATE or max_round

    console.print("[yellow]TODO: implement Task 1[/yellow]")


# ---------------------------------------------------------------------------
# Task 2: GroupChat — Planner, Coder, Tester
# ---------------------------------------------------------------------------

def task2_group_chat():
    console.print(Rule("[bold blue]Task 2: GroupChat — Planner, Coder, Tester"))

    llm_config = build_llm_config()

    # TODO: Create three AssistantAgents:
    #
    # PlannerAgent
    #   name: "Planner"
    #   system_message: "You are a software architect. Break the given problem
    #   into a clear implementation plan with numbered steps. Do NOT write code.
    #   Pass your plan to the Coder."
    #
    # CoderAgent
    #   name: "Coder"
    #   system_message: "You are a Python developer. Implement the plan provided
    #   by the Planner. Write complete, working Python code with docstrings."
    #
    # TesterAgent
    #   name: "Tester"
    #   system_message: "You are a QA engineer. Review the Coder's implementation
    #   for correctness, edge cases, and code quality. If it is acceptable, say
    #   APPROVED. Otherwise, provide specific numbered feedback."

    # TODO: Create a UserProxyAgent (Executor) with human_input_mode="NEVER"
    # and a termination condition that stops when the Tester says APPROVED.

    # TODO: Create a GroupChat with [user_proxy, planner, coder, tester].
    # Set max_round=15 and speaker_selection_method="round_robin" first.
    # Import: from autogen import GroupChat, GroupChatManager

    # TODO: Create a GroupChatManager backed by llm_config.

    # TODO: Run the group chat with the task below.
    task = (
        "Build and test a Python module with two functions: "
        "1) merge_sorted_lists(a: list, b: list) -> list that merges two sorted "
        "lists into one sorted list, and "
        "2) binary_search(arr: list, target) -> int that returns the index of "
        "target in arr or -1 if not found. Include docstrings and unit tests."
    )

    # TODO: After the round_robin run: switch to speaker_selection_method="auto"
    # and run again. Compare the two conversation traces.
    # Which produced better results? How many turns did each take?

    console.print("[yellow]TODO: implement Task 2[/yellow]")


# ---------------------------------------------------------------------------
# Task 3: Docker executor
# ---------------------------------------------------------------------------

def task3_docker_executor():
    console.print(Rule("[bold blue]Task 3: Docker Executor"))

    llm_config = build_llm_config()

    # TODO: Repeat Task 1's setup, but change code_execution_config to use Docker:
    #   code_execution_config={
    #       "executor": "docker",           # or use DockerCommandLineCodeExecutor
    #       "docker_image": "python:3.11-slim",
    #       "work_dir": "/tmp/autogen_docker",
    #       "timeout": 30,
    #   }
    # Alternatively, use the newer autogen.coding.DockerCommandLineCodeExecutor API.
    # Check the installed version of pyautogen to pick the right import.

    # TODO: Re-run the Levenshtein task through Docker. Verify it works.

    # TODO: Test the timeout. Give the agent a task that involves code with an
    # infinite loop:
    #   "Write Python code that runs `while True: pass` for 60 seconds."
    # The Docker executor should kill it after 30 seconds.
    # How does the agent respond to the timeout? Does it self-correct?

    # TODO: Print the Docker container ID that was used (if the executor exposes it).
    # This confirms code ran in Docker and not on the host.

    console.print("[yellow]TODO: implement Task 3[/yellow]")


# ---------------------------------------------------------------------------
# Task 4: Research pipeline with tool-calling agents
# ---------------------------------------------------------------------------

def task4_research_pipeline():
    console.print(Rule("[bold blue]Task 4: Research Pipeline with Tools"))

    llm_config = build_llm_config()

    # Simulated tool implementations — return stub data
    def web_search(query: str) -> str:
        """
        Simulate a web search. Returns stub results.
        In production this would call Bing Search API or similar.
        """
        stub_results = {
            "azure container apps": (
                "Azure Container Apps is a serverless container platform. "
                "Articles: [1] 'Getting Started with ACA' at aca.example.com, "
                "[2] 'Scaling ACA workloads' at scale.example.com"
            ),
            "kubernetes pod scheduling": (
                "Kubernetes scheduling assigns pods to nodes based on resource "
                "requests and affinity rules. "
                "Articles: [1] 'K8s Scheduler Deep Dive' at k8s.example.com"
            ),
        }
        query_lower = query.lower()
        for key, value in stub_results.items():
            if any(word in query_lower for word in key.split()):
                return value
        return f"No results found for query: {query}"

    def fetch_article(url: str) -> str:
        """
        Simulate fetching an article. Returns stub content.
        """
        return (
            f"Content of {url}: This is a detailed technical article. "
            "Key points: (1) The technology is scalable, (2) It integrates with "
            "Azure services, (3) It uses a managed control plane."
        )

    # TODO: Register web_search and fetch_article as AutoGen tools.
    # AutoGen tools are registered differently from SK plugins.
    # Use the @assistant.register_for_llm and @user_proxy.register_for_execution
    # decorators, or the FunctionCallingAgent API depending on your pyautogen version.
    # Check the AutoGen docs for your installed version.

    # TODO: Create a ResearchAgent (AssistantAgent) with instructions to:
    #   1. Use web_search to find information about the topic
    #   2. Use fetch_article to get details from 2 articles
    #   3. Synthesize findings and say TERMINATE when done

    # TODO: Create a WriterAgent that takes the ResearchAgent's findings and
    # produces a structured report with:
    #   - Executive Summary (2 sentences)
    #   - Key Findings (3 bullet points)
    #   - Sources (URLs cited)

    # TODO: Run the pipeline with the topic: "Azure Container Apps architecture"

    console.print("[yellow]TODO: implement Task 4[/yellow]")


# ---------------------------------------------------------------------------
# Task 5: Custom speaker selection (deterministic routing)
# ---------------------------------------------------------------------------

def task5_custom_speaker_selection():
    console.print(Rule("[bold blue]Task 5: Custom Deterministic Speaker Selection"))

    llm_config = build_llm_config()

    # Routing rules:
    # UserProxy -> Planner
    # Planner   -> Coder
    # Coder     -> Tester
    # Tester    -> Coder (if not APPROVED) or END

    def custom_speaker_selector(
        last_speaker,   # the agent that just spoke
        groupchat,      # the GroupChat object (has .agents and .messages)
    ):
        """
        Deterministic speaker routing function.

        AutoGen calls this after each turn to determine who speaks next.
        Return the next agent object (not its name).

        TODO: Implement the routing rules listed above.
        Use last_speaker.name to identify the current speaker.
        Use groupchat.agents to look up agents by name.
        Use groupchat.messages[-1]["content"] to check the last message content.

        Example of getting an agent by name:
            def agent_by_name(name):
                return next(a for a in groupchat.agents if a.name == name)
        """
        # TODO: implement routing logic
        raise NotImplementedError("custom_speaker_selector is not yet implemented")

    # TODO: Create Planner, Coder, Tester agents (same as Task 2).

    # TODO: Create a GroupChat with speaker_selection_method=custom_speaker_selector.

    # TODO: Create a GroupChatManager backed by llm_config.

    # TODO: Run the same task as Task 2.

    # TODO: Run it TWICE with identical input and verify:
    #   - The agent order is identical both times (deterministic)
    #   - Print the full sequence of speakers for each run

    # TODO: Reflect in a comment: in what scenarios does deterministic routing
    # break down? (Hint: think about what happens when Tester gives feedback
    # but there is no Planner re-plan step in the routing.)

    console.print("[yellow]TODO: implement Task 5[/yellow]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    console.print(Panel.fit(
        "[bold]Module 18 — AutoGen Lab[/bold]\n"
        "AutoGen conversations print directly to stdout.\n"
        "Comment out tasks you have already completed.",
        border_style="blue",
    ))

    task1_basic_code_loop()
    task2_group_chat()
    task3_docker_executor()
    task4_research_pipeline()
    task5_custom_speaker_selection()


if __name__ == "__main__":
    main()
