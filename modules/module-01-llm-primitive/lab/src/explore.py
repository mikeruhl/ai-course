"""
Module 1 Lab — LLM as a Compute Primitive
==========================================
Starter file for Tasks 2–6. Each task has a clearly marked section.

Run with:
    uv run python src/explore.py <task_number>

Example:
    uv run python src/explore.py 2

Complete each task in order. The earlier tasks build context for later ones.
"""

import json
import os
import statistics
import sys
import time

import httpx
import tiktoken
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


def chat(messages: list[dict], temperature: float = 0, max_tokens: int = 200) -> dict:
    """Make a single chat completion call. Returns the full response dict."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = httpx.post(BASE_URL, headers=HEADERS, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Task 2: Log the full response object
# ---------------------------------------------------------------------------
def task2_raw_response():
    print("\n" + "=" * 60)
    print("TASK 2: Raw response object")
    print("=" * 60)

    messages = [{"role": "user", "content": "What is 2 + 2?"}]
    response = chat(messages)

    print(json.dumps(response, indent=2))

    # TODO: After running, answer these questions in a comment:
    # 1. What is response["choices"][0]["finish_reason"]?
    # 2. What does response["usage"] tell you?
    # 3. What model actually responded (response["model"])?


# ---------------------------------------------------------------------------
# Task 3: Token counting with tiktoken
# ---------------------------------------------------------------------------
def task3_token_counting():
    print("\n" + "=" * 60)
    print("TASK 3: Token counting")
    print("=" * 60)

    # gpt-4o and gpt-4o-mini use the o200k_base encoding
    enc = tiktoken.get_encoding("o200k_base")

    samples = {
        "short_sentence": "The quick brown fox jumps over the lazy dog.",
        "medium_text": "Azure OpenAI Service provides REST API access to OpenAI's " * 20,
        "python_snippet": '''
def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

for i in range(10):
    print(f"fib({i}) = {fibonacci(i)}")
        ''',
    }

    for name, text in samples.items():
        token_count = len(enc.encode(text))
        char_count = len(text)
        print(f"\n{name}:")
        print(f"  chars: {char_count:,}")
        print(f"  tokens (tiktoken): {token_count:,}")
        print(f"  ratio: {char_count / token_count:.1f} chars/token")

    # TODO: Now make an API call with one of these texts and compare
    # tiktoken count vs the actual usage.prompt_tokens in the response.
    # Do they match? (They should — tiktoken is the same tokenizer.)


# ---------------------------------------------------------------------------
# Task 4: Temperature experiment
# ---------------------------------------------------------------------------
def task4_temperature_experiment():
    print("\n" + "=" * 60)
    print("TASK 4: Temperature experiment")
    print("=" * 60)

    prompt = "Name one color that sounds like it could be from a fantasy novel. Respond with only the color name, nothing else."
    messages = [{"role": "user", "content": prompt}]

    print("\nTemperature 0.0 (10 runs):")
    temp0_results = []
    for i in range(10):
        resp = chat(messages, temperature=0.0, max_tokens=20)
        answer = resp["choices"][0]["message"]["content"].strip()
        temp0_results.append(answer)
        print(f"  Run {i+1:2d}: {answer}")

    unique_t0 = len(set(temp0_results))
    print(f"  Unique responses: {unique_t0}/10")

    print("\nTemperature 1.0 (10 runs):")
    temp1_results = []
    for i in range(10):
        resp = chat(messages, temperature=1.0, max_tokens=20)
        answer = resp["choices"][0]["message"]["content"].strip()
        temp1_results.append(answer)
        print(f"  Run {i+1:2d}: {answer}")

    unique_t1 = len(set(temp1_results))
    print(f"  Unique responses: {unique_t1}/10")

    # TODO: What do you observe? Add a note about which setting you'd
    # use for an agent's tool-selection step and why.


# ---------------------------------------------------------------------------
# Task 5: Latency profiling
# ---------------------------------------------------------------------------
def task5_latency_profiling():
    print("\n" + "=" * 60)
    print("TASK 5: Latency profiling")
    print("=" * 60)

    messages = [{"role": "user", "content": "Respond with exactly the word: PONG"}]
    latencies = []

    print("\nMaking 20 calls...")
    for i in range(20):
        start = time.perf_counter()
        resp = chat(messages, temperature=0, max_tokens=5)
        elapsed = time.perf_counter() - start
        latencies.append(elapsed)
        tokens_out = resp["usage"]["completion_tokens"]
        print(f"  Call {i+1:2d}: {elapsed*1000:.0f}ms  ({tokens_out} tokens out)")

    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)

    print(f"\nResults:")
    print(f"  p50: {sorted_latencies[n // 2] * 1000:.0f}ms")
    print(f"  p95: {sorted_latencies[int(n * 0.95)] * 1000:.0f}ms")
    print(f"  p99: {sorted_latencies[int(n * 0.99)] * 1000:.0f}ms")
    print(f"  min: {min(latencies) * 1000:.0f}ms")
    print(f"  max: {max(latencies) * 1000:.0f}ms")
    print(f"  std: {statistics.stdev(latencies) * 1000:.0f}ms")

    # TODO: Note the variance. How does this affect how you'd design
    # a user-facing feature that makes multiple sequential LLM calls?


# ---------------------------------------------------------------------------
# Task 6: Lost in the middle demo
# ---------------------------------------------------------------------------
def task6_lost_in_middle():
    print("\n" + "=" * 60)
    print("TASK 6: Lost in the middle")
    print("=" * 60)

    needle = "The secret code word is: ZEPHYR-7"
    filler = "The weather today is partly cloudy with a chance of rain. " * 100  # ~500 tokens

    def test_recall(padding_multiplier: int):
        padding = filler * padding_multiplier
        enc = tiktoken.get_encoding("o200k_base")

        # Needle buried in the middle of padding
        context = padding + "\n\n" + needle + "\n\n" + padding
        token_count = len(enc.encode(context))

        messages = [
            {"role": "user", "content": f"{context}\n\nWhat is the secret code word?"}
        ]

        try:
            resp = chat(messages, temperature=0, max_tokens=50)
            answer = resp["choices"][0]["message"]["content"].strip()
            found = "ZEPHYR-7" in answer
            print(f"  Padding ~{token_count:,} tokens: recalled={found}  answer={answer!r}")
        except httpx.HTTPStatusError as e:
            print(f"  Padding ~{token_count:,} tokens: FAILED ({e.response.status_code} — likely exceeds context window)")

    print("\nTesting recall at different context depths:")
    for multiplier in [1, 5, 20, 60]:
        test_recall(multiplier)

    # TODO: At what context length does recall start to fail?
    # What are the implications for RAG chunk retrieval and agent memory?


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
TASKS = {
    "2": task2_raw_response,
    "3": task3_token_counting,
    "4": task4_temperature_experiment,
    "5": task5_latency_profiling,
    "6": task6_lost_in_middle,
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python src/explore.py <task_number>")
        print(f"Available tasks: {', '.join(TASKS)}")
        sys.exit(1)

    task_num = sys.argv[1]
    if task_num not in TASKS:
        print(f"Unknown task: {task_num}")
        print(f"Available tasks: {', '.join(TASKS)}")
        sys.exit(1)

    TASKS[task_num]()
