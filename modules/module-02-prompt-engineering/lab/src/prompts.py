"""
Module 2 Lab — Task 1: Prompt Contract Rewrite
================================================
Each function below contains a "bad" system prompt.
Rewrite it as a staff-level contract following the pattern:
  - ROLE
  - OUTPUT FORMAT (prefer JSON schema)
  - RULES / EDGE CASES

Run with:
    uv run python src/prompts.py
"""

import json
import os

import httpx
from dotenv import load_dotenv

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
else:  # ollama
    ENDPOINT = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
    BASE_URL = f"{ENDPOINT}/v1/chat/completions"
    HEADERS = {"Content-Type": "application/json"}
    MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")


def chat(system: str, user: str, response_format=None, temperature: float = 0) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 500,
    }
    if response_format:
        payload["response_format"] = response_format

    resp = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Prompt 1: Sentiment classifier
# BAD: vague output format, no edge case handling
# ---------------------------------------------------------------------------
BAD_SENTIMENT_PROMPT = """
You are a sentiment analysis assistant. Analyze the sentiment of text
and tell me if it's positive or negative.
"""

# TODO: Rewrite this prompt. Requirements:
# - Output must be JSON with fields: sentiment, confidence (0.0-1.0), reason
# - Handle neutral, mixed, and non-English text
# - Handle empty input gracefully
GOOD_SENTIMENT_PROMPT = """
TODO: write your improved prompt here
"""


# ---------------------------------------------------------------------------
# Prompt 2: Code language detector
# BAD: doesn't handle unknown languages, no structured output
# ---------------------------------------------------------------------------
BAD_LANGUAGE_PROMPT = """
You are a programming language detector. Tell me what programming language
the given code is written in.
"""

# TODO: Rewrite this prompt. Requirements:
# - Output: JSON with fields: language, confidence, reasoning
# - Handle: pseudocode, config files (YAML/JSON/TOML), unknown languages
# - Handle: empty input, plain English text submitted as code
GOOD_LANGUAGE_PROMPT = """
TODO: write your improved prompt here
"""


# ---------------------------------------------------------------------------
# Prompt 3: Bug summarizer
# BAD: no output format, no severity handling, ambiguous scope
# ---------------------------------------------------------------------------
BAD_BUG_PROMPT = """
You are a helpful assistant. Look at this error message and stack trace
and tell me what's wrong.
"""

# TODO: Rewrite this prompt. Requirements:
# - Output: JSON with fields: error_type, root_cause, suggested_fix, severity
# - Severity values: "runtime_error" | "logic_error" | "config_error" | "unknown"
# - Suggested fix should be a concrete code snippet where possible
# - Handle: malformed/truncated stack traces, non-English error messages
GOOD_BUG_PROMPT = """
TODO: write your improved prompt here
"""


# ---------------------------------------------------------------------------
# Test your rewrites
# ---------------------------------------------------------------------------
def test_sentiment():
    test_inputs = [
        "I absolutely love this product! Best purchase ever.",
        "It's okay, nothing special.",
        "This is completely broken and I want my money back.",
        "",  # edge case: empty input
        "C'est magnifique!",  # edge case: non-English
    ]

    print("\n--- Sentiment Classifier ---")
    for text in test_inputs:
        result = chat(GOOD_SENTIMENT_PROMPT, text)
        print(f"\nInput: {text!r}")
        print(f"Output: {result}")


def test_language():
    test_inputs = [
        "for i in range(10):\n    print(i)",
        "SELECT * FROM users WHERE id = 1;",
        "const x = () => { return 42; }",
        "This is just a paragraph of English text, not code.",
        "",
    ]

    print("\n--- Language Detector ---")
    for code in test_inputs:
        result = chat(GOOD_LANGUAGE_PROMPT, code)
        print(f"\nInput: {code[:50]!r}...")
        print(f"Output: {result}")


if __name__ == "__main__":
    test_sentiment()
    test_language()
