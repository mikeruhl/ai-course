"""
Module 24 Lab — Cost & Performance
=====================================
Understand token economics, implement caching, and profile agent pipelines.

Tasks:
  A. Token Counter     — count tokens, calculate costs at different price points
  B. Semantic Cache    — embedding-based cache for similar prompts
  C. Pipeline Profiler — instrument an agent pipeline, display latency waterfall

Run with:
    uv run costperf --task A
    uv run costperf --task B
    uv run costperf --task C
"""

import argparse
import asyncio
import json
import math
import os
import time
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.bar_chart import BarChart

load_dotenv()

PROVIDER = os.environ.get("LLM_PROVIDER", "azure")

# Azure-only: embedding endpoint (used regardless of LLM provider)
ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
API_KEY = os.environ["AZURE_OPENAI_KEY"]
EMBEDDING_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
EMBED_URL = f"{ENDPOINT}/openai/deployments/{EMBEDDING_DEPLOYMENT}/embeddings?api-version={API_VERSION}"
EMBED_HEADERS = {"Content-Type": "application/json", "api-key": API_KEY}

if PROVIDER == "vertex":
    import google.auth
    import google.auth.transport.requests
    GCP_PROJECT = os.environ["GCP_PROJECT_ID"]
    GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
    _credentials, _ = google.auth.default()
    _credentials.refresh(google.auth.transport.requests.Request())
    CHAT_URL = f"https://{GCP_REGION}-aiplatform.googleapis.com/v1/projects/{GCP_PROJECT}/locations/{GCP_REGION}/endpoints/openapi/chat/completions"
    HEADERS = {"Authorization": f"Bearer {_credentials.token}", "Content-Type": "application/json"}
    MODEL = os.environ.get("VERTEX_MODEL", "google/gemini-2.0-flash")
else:  # azure (default)
    DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    CHAT_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
    HEADERS = {"Content-Type": "application/json", "api-key": API_KEY}
    MODEL = DEPLOYMENT

console = Console()

# Pricing per 1M tokens (as of early 2025)
PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
}


async def chat(client: httpx.AsyncClient, messages: list[dict], **kwargs) -> dict:
    resp = await client.post(
        CHAT_URL, headers=HEADERS,
        json={"messages": messages, "temperature": 0, **kwargs},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


async def embed(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    resp = await client.post(
        EMBED_URL, headers=EMBED_HEADERS,
        json={"input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [d["embedding"] for d in sorted(data, key=lambda x: x["index"])]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Task A — Token counter and cost calculator
# ---------------------------------------------------------------------------

# Simple token estimator (approximation: ~4 chars per token for English)
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def task_a():
    """Count tokens and calculate costs across models."""
    console.print(Panel("Task A — Token Counter & Cost Calculator", style="bold cyan"))

    test_prompts = [
        ("Simple", "What is 2+2?"),
        ("Medium", "Explain the difference between SQL and NoSQL databases in 3 paragraphs."),
        ("Long system prompt", (
            "You are an expert software architect specializing in distributed systems. "
            "You have 20 years of experience building microservices, event-driven architectures, "
            "and cloud-native applications. When analyzing code, consider: performance implications, "
            "security vulnerabilities, maintainability, testability, and operational complexity. "
            "Always provide specific, actionable recommendations with code examples. "
            "Reference industry standards (OWASP, 12-factor app, CNCF guidelines) where applicable."
        )),
        ("RAG context", "Context: " + "A" * 2000 + "\n\nQuestion: Summarize the above."),
    ]

    # Estimate costs
    table = Table(title="Token Estimates & Cost per Call")
    table.add_column("Prompt", width=20)
    table.add_column("Est. Input Tokens", width=18)
    table.add_column("Est. Output Tokens", width=18)
    for model in ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]:
        table.add_column(f"{model}", width=14)

    for name, prompt in test_prompts:
        input_tokens = estimate_tokens(prompt)
        output_tokens = input_tokens // 2  # rough estimate
        costs = []
        for model in ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]:
            p = PRICING[model]
            cost = (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
            costs.append(f"${cost:.6f}")
        table.add_row(name, str(input_tokens), str(output_tokens), *costs)

    console.print(table)

    # Make a real call and show actual usage
    console.print("\n[bold]Actual API usage from a real call:[/bold]")
    async with httpx.AsyncClient() as client:
        result = await chat(client, [{"role": "user", "content": "Explain event sourcing in 2 sentences."}])
        usage = result.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)

        table2 = Table(title="Actual Token Usage")
        table2.add_column("Metric", width=20)
        table2.add_column("Value", width=15)
        table2.add_column("Cost (gpt-4o-mini)", width=18)
        table2.add_column("Cost (gpt-4o)", width=18)

        p_mini = PRICING["gpt-4o-mini"]
        p_4o = PRICING["gpt-4o"]
        table2.add_row("Prompt tokens", str(prompt_tokens),
                        f"${prompt_tokens * p_mini['input'] / 1e6:.6f}",
                        f"${prompt_tokens * p_4o['input'] / 1e6:.6f}")
        table2.add_row("Completion tokens", str(completion_tokens),
                        f"${completion_tokens * p_mini['output'] / 1e6:.6f}",
                        f"${completion_tokens * p_4o['output'] / 1e6:.6f}")
        table2.add_row("Total", str(total),
                        f"${(prompt_tokens * p_mini['input'] + completion_tokens * p_mini['output']) / 1e6:.6f}",
                        f"${(prompt_tokens * p_4o['input'] + completion_tokens * p_4o['output']) / 1e6:.6f}")
        console.print(table2)

    # Monthly projection
    console.print("\n[bold]Monthly cost projection (1000 calls/day):[/bold]")
    calls_per_day = 1000
    avg_input = 500
    avg_output = 200
    days = 30
    table3 = Table(title="Monthly Cost @ 1K calls/day")
    table3.add_column("Model", width=25)
    table3.add_column("Monthly Cost", width=15)
    for model, p in PRICING.items():
        if "embedding" in model:
            continue
        monthly = calls_per_day * days * (avg_input * p["input"] + avg_output * p["output"]) / 1e6
        table3.add_row(model, f"${monthly:.2f}")
    console.print(table3)


# ---------------------------------------------------------------------------
# Task B — Semantic cache
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    prompt: str
    response: str
    embedding: list[float]
    hits: int = 0


class SemanticCache:
    """Cache that returns stored responses for semantically similar prompts."""

    def __init__(self, similarity_threshold: float = 0.92):
        self.entries: list[CacheEntry] = []
        self.threshold = similarity_threshold
        self.stats = {"hits": 0, "misses": 0}

    def lookup(self, query_embedding: list[float]) -> str | None:
        best_score = 0.0
        best_entry = None
        for entry in self.entries:
            score = cosine_similarity(query_embedding, entry.embedding)
            if score > best_score:
                best_score = score
                best_entry = entry
        if best_entry and best_score >= self.threshold:
            best_entry.hits += 1
            self.stats["hits"] += 1
            return best_entry.response
        self.stats["misses"] += 1
        return None

    def store(self, prompt: str, response: str, embedding: list[float]):
        self.entries.append(CacheEntry(prompt=prompt, response=response, embedding=embedding))


async def task_b():
    """Demonstrate semantic caching for LLM calls."""
    console.print(Panel("Task B — Semantic Cache", style="bold cyan"))

    cache = SemanticCache(similarity_threshold=0.90)

    queries = [
        "What is the capital of France?",
        "Tell me the capital city of France.",          # semantic duplicate
        "What's France's capital?",                     # semantic duplicate
        "What is the capital of Germany?",              # different
        "Explain quantum computing in simple terms.",
        "Can you explain quantum computing simply?",    # semantic duplicate
        "What is the weather like today?",              # different
    ]

    async with httpx.AsyncClient() as client:
        for query in queries:
            t0 = time.time()
            q_emb = (await embed(client, [query]))[0]
            cached = cache.lookup(q_emb)

            if cached:
                elapsed = (time.time() - t0) * 1000
                console.print(f"  [green]CACHE HIT[/green] ({elapsed:.0f}ms): {query}")
                console.print(f"    → {cached[:80]}...")
            else:
                result = await chat(client, [{"role": "user", "content": query}], max_tokens=100)
                response = result["choices"][0]["message"]["content"]
                cache.store(query, response, q_emb)
                elapsed = (time.time() - t0) * 1000
                console.print(f"  [yellow]CACHE MISS[/yellow] ({elapsed:.0f}ms): {query}")
                console.print(f"    → {response[:80]}...")

    console.print()
    table = Table(title="Cache Stats")
    table.add_column("Metric", width=20)
    table.add_column("Value", width=10)
    table.add_row("Entries", str(len(cache.entries)))
    table.add_row("Hits", str(cache.stats["hits"]))
    table.add_row("Misses", str(cache.stats["misses"]))
    hit_rate = cache.stats["hits"] / (cache.stats["hits"] + cache.stats["misses"]) if (cache.stats["hits"] + cache.stats["misses"]) else 0
    table.add_row("Hit rate", f"{hit_rate:.0%}")
    console.print(table)


# ---------------------------------------------------------------------------
# Task C — Pipeline profiler
# ---------------------------------------------------------------------------

@dataclass
class TimingEntry:
    step: str
    start: float
    end: float

    @property
    def duration_ms(self) -> float:
        return (self.end - self.start) * 1000


class PipelineProfiler:
    """Instrument and visualize latency in an agent pipeline."""

    def __init__(self):
        self.timings: list[TimingEntry] = []
        self._current: dict[str, float] = {}

    def start(self, step: str):
        self._current[step] = time.time()

    def stop(self, step: str):
        start = self._current.pop(step, time.time())
        self.timings.append(TimingEntry(step=step, start=start, end=time.time()))

    def report(self):
        total = sum(t.duration_ms for t in self.timings)
        table = Table(title=f"Pipeline Profile (total: {total:.0f}ms)")
        table.add_column("Step", width=25)
        table.add_column("Duration (ms)", width=15)
        table.add_column("% of Total", width=12)
        table.add_column("Waterfall", width=40)

        max_dur = max(t.duration_ms for t in self.timings) if self.timings else 1
        for t in self.timings:
            pct = (t.duration_ms / total * 100) if total else 0
            bar_len = int(t.duration_ms / max_dur * 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            table.add_row(t.step, f"{t.duration_ms:.0f}", f"{pct:.1f}%", bar)
        console.print(table)


async def task_c():
    """Profile a multi-step agent pipeline."""
    console.print(Panel("Task C — Pipeline Profiler", style="bold cyan"))

    profiler = PipelineProfiler()
    question = "What are the best practices for securing an AI agent in production?"

    async with httpx.AsyncClient() as client:
        # Step 1: Embed query
        profiler.start("embed_query")
        q_emb = (await embed(client, [question]))[0]
        profiler.stop("embed_query")

        # Step 2: Simulate retrieval (local cosine similarity)
        profiler.start("retrieve_docs")
        docs = [
            "Always validate tool outputs before executing side effects.",
            "Use content filtering to block prompt injection attempts.",
            "Implement rate limiting at the agent level, not just the API level.",
        ]
        doc_embs = await embed(client, docs)
        scores = [(cosine_similarity(q_emb, de), d) for de, d in zip(doc_embs, docs)]
        scores.sort(reverse=True)
        top_docs = [d for _, d in scores[:2]]
        profiler.stop("retrieve_docs")

        # Step 3: Construct prompt
        profiler.start("construct_prompt")
        context = "\n".join(f"- {d}" for d in top_docs)
        messages = [
            {"role": "system", "content": "Answer based on the provided context."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ]
        profiler.stop("construct_prompt")

        # Step 4: LLM call
        profiler.start("llm_generation")
        result = await chat(client, messages)
        answer = result["choices"][0]["message"]["content"]
        profiler.stop("llm_generation")

        # Step 5: Output validation
        profiler.start("output_validation")
        is_valid = len(answer) > 10 and not answer.startswith("I don't")
        profiler.stop("output_validation")

    console.print(f"\n[bold]Answer:[/bold] {answer[:200]}...\n")
    profiler.report()

    # Show where time is typically spent
    console.print("\n[dim]Typical breakdown: embedding ~10%, retrieval ~20%, LLM generation ~65%, other ~5%[/dim]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Module 24 — Cost & Performance Lab")
    parser.add_argument("--task", choices=["A", "B", "C"], required=True)
    args = parser.parse_args()

    dispatch = {"A": task_a, "B": task_b, "C": task_c}
    asyncio.run(dispatch[args.task]())


if __name__ == "__main__":
    main()
