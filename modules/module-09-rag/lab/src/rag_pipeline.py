"""
Module 09 Lab — Retrieval-Augmented Generation
================================================
Build a full RAG pipeline: chunking, embedding, retrieval, generation, evaluation.

Tasks:
  A. Chunking      — fixed-size, sentence-aware, and recursive strategies
  B. Embedding     — embed chunks via Azure OpenAI, upsert to Azure AI Search
  C. Retrieval     — vector, keyword, and hybrid search
  D. RAG Pipeline  — end-to-end: chunk → embed → retrieve → prompt → generate
  E. Evaluation    — RAGAS-style metrics (faithfulness, relevancy, precision)

Run with:
    uv run rag --task A
    uv run rag --task B   # requires Azure AI Search
    uv run rag --task C   # requires Azure AI Search
    uv run rag --task D   # requires Azure AI Search
    uv run rag --task E
"""

import argparse
import asyncio
import json
import math
import os
import re
import time
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

# ---------------------------------------------------------------------------
# Azure OpenAI connection constants
# ---------------------------------------------------------------------------
ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
API_KEY = os.environ["AZURE_OPENAI_KEY"]
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
EMBEDDING_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

CHAT_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/chat/completions?api-version={API_VERSION}"
EMBED_URL = f"{ENDPOINT}/openai/deployments/{EMBEDDING_DEPLOYMENT}/embeddings?api-version={API_VERSION}"

SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
SEARCH_KEY = os.environ.get("AZURE_SEARCH_KEY", "")
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX", "rag-documents")

HEADERS = {"Content-Type": "application/json", "api-key": API_KEY}

console = Console()

# ---------------------------------------------------------------------------
# Sample documents (self-contained — no external files needed)
# ---------------------------------------------------------------------------
SAMPLE_DOCS = [
    {
        "id": "azure-openai-models",
        "title": "Azure OpenAI Models and Pricing",
        "content": """Azure OpenAI Service provides access to OpenAI's models including GPT-4o,
GPT-4o-mini, GPT-4 Turbo, and embedding models. GPT-4o is the flagship model
optimized for both quality and speed. It supports 128K token context windows
and multimodal inputs (text and images).

GPT-4o-mini is a cost-optimized variant designed for tasks where speed and cost
matter more than maximum capability. It costs approximately $0.15 per 1M input
tokens and $0.60 per 1M output tokens, making it 10-20x cheaper than GPT-4o.

For embeddings, text-embedding-3-small produces 1536-dimensional vectors at
$0.02 per 1M tokens. text-embedding-3-large produces up to 3072 dimensions
at $0.13 per 1M tokens. Both support shortening via the dimensions parameter.

Provisioned Throughput Units (PTU) provide guaranteed capacity for production
workloads. One PTU provides approximately 6 requests per minute for GPT-4o
or 25 RPM for GPT-4o-mini. PTU pricing starts at roughly $2/hour per PTU.""",
    },
    {
        "id": "azure-openai-rate-limits",
        "title": "Azure OpenAI Rate Limits and Quotas",
        "content": """Azure OpenAI enforces rate limits at the deployment level using two metrics:
Requests Per Minute (RPM) and Tokens Per Minute (TPM). When either limit is
exceeded, the API returns HTTP 429 with a Retry-After header.

Default rate limits for standard (pay-as-you-go) deployments:
- GPT-4o: 30 RPM, 150K TPM per deployment
- GPT-4o-mini: 60 RPM, 300K TPM per deployment
- text-embedding-3-small: 120 RPM, 350K TPM per deployment

Rate limits can be increased by requesting quota changes in the Azure portal.
Global deployments distribute traffic across regions and offer higher default
limits (up to 1500 RPM for GPT-4o-mini).

Best practices for handling rate limits:
1. Implement exponential backoff with jitter
2. Use the Retry-After header value when present
3. Batch embedding requests (up to 16 texts per call)
4. Consider provisioned throughput for sustained high-volume workloads
5. Monitor usage via Azure Monitor metrics""",
    },
    {
        "id": "azure-ai-search-overview",
        "title": "Azure AI Search Vector and Hybrid Search",
        "content": """Azure AI Search supports three retrieval modes: full-text (BM25 keyword),
vector (cosine/dot-product similarity), and hybrid (both combined with
Reciprocal Rank Fusion).

Vector search indexes store dense embeddings alongside traditional text fields.
To configure vector search, define a vector profile in the index schema that
specifies the algorithm (HNSW or exhaustive KNN) and the similarity metric.

HNSW (Hierarchical Navigable Small World) is the recommended algorithm for
production use. It builds a multi-layered graph for approximate nearest
neighbor search. Key parameters:
- m: 4-10 (bi-directional links per node; higher = better recall, more memory)
- efConstruction: 400 (build-time search width)
- efSearch: 500 (query-time search width)

Hybrid search combines BM25 keyword scores with vector similarity scores
using Reciprocal Rank Fusion (RRF). RRF is parameter-free — it merges ranked
lists by computing 1/(k+rank) for each result in each list, then summing.
This consistently outperforms either method alone.

Semantic ranker is an optional L2 reranker that uses a cross-encoder model
to re-score the top results from the L1 retrieval stage. It improves precision
at the cost of latency (~200ms added per query).""",
    },
    {
        "id": "rag-patterns",
        "title": "RAG Architecture Patterns",
        "content": """The standard RAG pipeline has five stages: chunk, embed, index, retrieve,
generate. Each stage has multiple design choices that affect quality.

Naive RAG retrieves the top-k most similar chunks and stuffs them into the
prompt. This fails when: (a) relevant information spans multiple chunks,
(b) the query is ambiguous, or (c) the chunks are too long/short.

Advanced RAG patterns address these failures:

1. Query transformation: rewrite the user query for better retrieval.
   - HyDE: generate a hypothetical answer, embed that instead of the query
   - Multi-query: generate 3-5 query variations, retrieve for each, deduplicate
   - Step-back: ask a more general question first to establish context

2. Hierarchical retrieval: use summaries for coarse filtering, then full
   chunks for detail. Parent-child chunking stores small chunks for retrieval
   but expands to parent chunks for generation context.

3. Self-RAG: the model decides whether to retrieve, generates citations,
   and self-evaluates whether the retrieved context actually supports the
   answer. If not, it re-retrieves or abstains.

4. Corrective RAG (CRAG): after retrieval, a grader model scores each
   document for relevance. Irrelevant documents are discarded. If no
   documents pass the threshold, the system falls back to web search.

Evaluation uses three RAGAS metrics:
- Faithfulness: fraction of answer claims supported by retrieved context
- Answer Relevancy: does the answer actually address the question?
- Context Precision: are the retrieved chunks actually relevant?""",
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def chat(client: httpx.AsyncClient, messages: list[dict], temperature: float = 0.0) -> str:
    resp = await client.post(
        CHAT_URL,
        headers=HEADERS,
        json={"messages": messages, "temperature": temperature},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def embed(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    resp = await client.post(
        EMBED_URL,
        headers=HEADERS,
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
# Task A — Chunking strategies
# ---------------------------------------------------------------------------

def chunk_fixed(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """Fixed-size character chunking with overlap."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def chunk_sentence(text: str, max_size: int = 500, overlap_sentences: int = 1) -> list[str]:
    """Sentence-aware chunking — never splits mid-sentence."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current: list[str] = []
    current_len = 0
    for s in sentences:
        if current_len + len(s) > max_size and current:
            chunks.append(" ".join(current))
            keep = current[-overlap_sentences:] if overlap_sentences else []
            current = list(keep)
            current_len = sum(len(x) for x in current)
        current.append(s)
        current_len += len(s)
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_recursive(text: str, max_size: int = 500, separators: list[str] | None = None) -> list[str]:
    """Recursive chunking — try paragraph, then sentence, then character boundaries."""
    if separators is None:
        separators = ["\n\n", "\n", ". ", " "]
    if len(text) <= max_size:
        return [text]
    sep = separators[0] if separators else ""
    parts = text.split(sep) if sep else [text[i:i + max_size] for i in range(0, len(text), max_size)]
    chunks = []
    current = ""
    for part in parts:
        candidate = current + sep + part if current else part
        if len(candidate) <= max_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(part) > max_size and len(separators) > 1:
                chunks.extend(chunk_recursive(part, max_size, separators[1:]))
                current = ""
            else:
                current = part
    if current:
        chunks.append(current)
    return chunks


async def task_a():
    """Demonstrate three chunking strategies on sample documents."""
    console.print(Panel("Task A — Chunking Strategies", style="bold cyan"))
    doc = SAMPLE_DOCS[0]["content"]
    console.print(f"\n[bold]Source document:[/bold] {SAMPLE_DOCS[0]['title']}")
    console.print(f"Length: {len(doc)} chars\n")

    for name, fn in [("Fixed-Size", chunk_fixed), ("Sentence-Aware", chunk_sentence), ("Recursive", chunk_recursive)]:
        chunks = fn(doc)
        table = Table(title=f"{name} Chunking ({len(chunks)} chunks)")
        table.add_column("#", style="dim", width=4)
        table.add_column("Length", width=8)
        table.add_column("Preview", max_width=70)
        for i, c in enumerate(chunks):
            table.add_row(str(i), str(len(c)), c[:70].replace("\n", " ") + "...")
        console.print(table)
        console.print()


# ---------------------------------------------------------------------------
# Task B — Embedding + Ingestion
# ---------------------------------------------------------------------------

@dataclass
class ChunkRecord:
    id: str
    doc_id: str
    text: str
    embedding: list[float] = field(default_factory=list)


async def task_b():
    """Embed chunks and upsert to Azure AI Search."""
    console.print(Panel("Task B — Embedding + Ingestion", style="bold cyan"))

    if not SEARCH_ENDPOINT:
        console.print("[yellow]AZURE_SEARCH_ENDPOINT not set — running in local-only mode.[/yellow]")
        console.print("Embeddings will be generated but not uploaded.\n")

    all_chunks: list[ChunkRecord] = []
    for doc in SAMPLE_DOCS:
        texts = chunk_recursive(doc["content"], max_size=400)
        for i, t in enumerate(texts):
            all_chunks.append(ChunkRecord(id=f"{doc['id']}-{i}", doc_id=doc["id"], text=t))

    console.print(f"Total chunks to embed: {len(all_chunks)}")

    async with httpx.AsyncClient() as client:
        batch_size = 16
        for start in range(0, len(all_chunks), batch_size):
            batch = all_chunks[start:start + batch_size]
            texts = [c.text for c in batch]
            embeddings = await embed(client, texts)
            for chunk, emb in zip(batch, embeddings):
                chunk.embedding = emb
            console.print(f"  Embedded batch {start // batch_size + 1}: {len(batch)} chunks, dim={len(embeddings[0])}")

    if SEARCH_ENDPOINT and SEARCH_KEY:
        await _upsert_to_search(all_chunks)
    else:
        console.print("\n[dim]Skipping upload — set AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY to upload.[/dim]")

    console.print(f"\n[green]Embedded {len(all_chunks)} chunks successfully.[/green]")
    return all_chunks


async def _upsert_to_search(chunks: list[ChunkRecord]):
    """Create index if needed and upload documents to Azure AI Search."""
    search_headers = {"Content-Type": "application/json", "api-key": SEARCH_KEY}
    api = "2024-07-01"

    index_url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}?api-version={api}"
    docs_url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/index?api-version={api}"

    dim = len(chunks[0].embedding)
    index_def = {
        "name": SEARCH_INDEX,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "doc_id", "type": "Edm.String", "filterable": True},
            {"name": "text", "type": "Edm.String", "searchable": True},
            {
                "name": "embedding",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "vectorSearchDimensions": dim,
                "vectorSearchProfileName": "default-profile",
            },
        ],
        "vectorSearch": {
            "algorithms": [{"name": "hnsw-algo", "kind": "hnsw", "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"}}],
            "profiles": [{"name": "default-profile", "algorithmConfigurationName": "hnsw-algo"}],
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.put(index_url, headers=search_headers, json=index_def, timeout=30)
        if resp.status_code in (200, 201, 204):
            console.print(f"  Index '{SEARCH_INDEX}' created/updated.")
        else:
            console.print(f"  [yellow]Index create returned {resp.status_code}: {resp.text[:200]}[/yellow]")

        documents = [
            {"@search.action": "mergeOrUpload", "id": c.id, "doc_id": c.doc_id, "text": c.text, "embedding": c.embedding}
            for c in chunks
        ]
        resp = await client.post(docs_url, headers=search_headers, json={"value": documents}, timeout=30)
        resp.raise_for_status()
        console.print(f"  Uploaded {len(documents)} documents to index.")


# ---------------------------------------------------------------------------
# Task C — Retrieval
# ---------------------------------------------------------------------------

async def task_c():
    """Demonstrate vector, keyword, and hybrid retrieval."""
    console.print(Panel("Task C — Retrieval Modes", style="bold cyan"))

    queries = [
        "What are the rate limits for GPT-4o-mini?",
        "How does hybrid search work in Azure AI Search?",
        "What is CRAG and how does it improve RAG?",
    ]

    async with httpx.AsyncClient() as client:
        if SEARCH_ENDPOINT and SEARCH_KEY:
            for query in queries:
                console.print(f"\n[bold]Query:[/bold] {query}\n")
                for mode in ["keyword", "vector", "hybrid"]:
                    results = await _search(client, query, mode=mode, top=3)
                    table = Table(title=f"{mode.upper()} results")
                    table.add_column("Score", width=8)
                    table.add_column("ID", width=25)
                    table.add_column("Text", max_width=60)
                    for r in results:
                        table.add_row(f"{r['score']:.4f}", r["id"], r["text"][:60] + "...")
                    console.print(table)
        else:
            console.print("[yellow]No Azure AI Search configured — running local vector search.[/yellow]\n")
            all_chunks = []
            for doc in SAMPLE_DOCS:
                texts = chunk_recursive(doc["content"], max_size=400)
                for i, t in enumerate(texts):
                    all_chunks.append(ChunkRecord(id=f"{doc['id']}-{i}", doc_id=doc["id"], text=t))

            texts = [c.text for c in all_chunks]
            embeddings = await embed(client, texts)
            for c, e in zip(all_chunks, embeddings):
                c.embedding = e

            for query in queries:
                console.print(f"\n[bold]Query:[/bold] {query}")
                q_emb = (await embed(client, [query]))[0]
                scored = [(cosine_similarity(q_emb, c.embedding), c) for c in all_chunks]
                scored.sort(key=lambda x: x[0], reverse=True)
                table = Table(title="Local vector search (top 3)")
                table.add_column("Score", width=8)
                table.add_column("ID", width=25)
                table.add_column("Text", max_width=60)
                for score, c in scored[:3]:
                    table.add_row(f"{score:.4f}", c.id, c.text[:60].replace("\n", " ") + "...")
                console.print(table)


async def _search(client: httpx.AsyncClient, query: str, mode: str = "hybrid", top: int = 5) -> list[dict]:
    """Search Azure AI Search in keyword, vector, or hybrid mode."""
    api = "2024-07-01"
    url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version={api}"
    headers = {"Content-Type": "application/json", "api-key": SEARCH_KEY}

    body: dict = {"top": top}

    if mode in ("vector", "hybrid"):
        q_emb = (await embed(client, [query]))[0]
        body["vectorQueries"] = [{"vector": q_emb, "fields": "embedding", "kind": "vector", "k": top}]

    if mode in ("keyword", "hybrid"):
        body["search"] = query
        body["queryType"] = "simple"

    resp = await client.post(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("value", [])
    return [{"id": r.get("id", ""), "text": r.get("text", ""), "score": r.get("@search.score", 0)} for r in results]


# ---------------------------------------------------------------------------
# Task D — Full RAG pipeline
# ---------------------------------------------------------------------------

async def task_d():
    """End-to-end RAG: retrieve → construct prompt → generate with citations."""
    console.print(Panel("Task D — Full RAG Pipeline", style="bold cyan"))

    questions = [
        "What is the cost difference between GPT-4o and GPT-4o-mini?",
        "How should I configure HNSW parameters for production?",
        "What are the advanced RAG patterns beyond naive RAG?",
    ]

    async with httpx.AsyncClient() as client:
        for question in questions:
            console.print(f"\n[bold yellow]Question:[/bold yellow] {question}\n")

            # Retrieve
            if SEARCH_ENDPOINT and SEARCH_KEY:
                results = await _search(client, question, mode="hybrid", top=3)
                context_chunks = [r["text"] for r in results]
            else:
                all_chunks = []
                for doc in SAMPLE_DOCS:
                    texts = chunk_recursive(doc["content"], max_size=400)
                    for i, t in enumerate(texts):
                        all_chunks.append(ChunkRecord(id=f"{doc['id']}-{i}", doc_id=doc["id"], text=t))
                texts_list = [c.text for c in all_chunks]
                embeddings = await embed(client, texts_list)
                for c, e in zip(all_chunks, embeddings):
                    c.embedding = e
                q_emb = (await embed(client, [question]))[0]
                scored = [(cosine_similarity(q_emb, c.embedding), c) for c in all_chunks]
                scored.sort(key=lambda x: x[0], reverse=True)
                context_chunks = [c.text for _, c in scored[:3]]

            # Construct RAG prompt
            context_block = "\n\n---\n\n".join(f"[Source {i+1}]\n{chunk}" for i, chunk in enumerate(context_chunks))
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Answer the user's question based ONLY on the provided context. "
                        "Cite sources as [Source N]. If the context doesn't contain the answer, say so."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context_block}\n\nQuestion: {question}",
                },
            ]

            # Generate
            answer = await chat(client, messages)
            console.print(Panel(answer, title="Answer", border_style="green"))
            console.print(f"[dim]Sources used: {len(context_chunks)} chunks[/dim]\n")


# ---------------------------------------------------------------------------
# Task E — RAGAS-style evaluation
# ---------------------------------------------------------------------------

async def task_e():
    """Evaluate RAG quality with faithfulness, relevancy, and precision metrics."""
    console.print(Panel("Task E — RAG Evaluation (RAGAS-style)", style="bold cyan"))

    eval_cases = [
        {
            "question": "What is the cost of GPT-4o-mini per million input tokens?",
            "expected": "GPT-4o-mini costs approximately $0.15 per 1M input tokens.",
            "context": SAMPLE_DOCS[0]["content"],
        },
        {
            "question": "What algorithm does Azure AI Search recommend for vector search?",
            "expected": "HNSW (Hierarchical Navigable Small World) is the recommended algorithm.",
            "context": SAMPLE_DOCS[2]["content"],
        },
        {
            "question": "What is Self-RAG?",
            "expected": "Self-RAG is a pattern where the model decides whether to retrieve, generates citations, and self-evaluates.",
            "context": SAMPLE_DOCS[3]["content"],
        },
    ]

    async with httpx.AsyncClient() as client:
        for case in eval_cases:
            console.print(f"\n[bold]Q:[/bold] {case['question']}")

            # Generate answer from context
            messages = [
                {"role": "system", "content": "Answer based ONLY on the context. Be concise."},
                {"role": "user", "content": f"Context:\n{case['context']}\n\nQuestion: {case['question']}"},
            ]
            answer = await chat(client, messages)
            console.print(f"[green]A:[/green] {answer}")

            # Faithfulness — ask LLM to extract claims and verify against context
            faith_prompt = (
                f"Extract factual claims from this answer, then for each claim state whether "
                f"it is SUPPORTED or NOT SUPPORTED by the context.\n\n"
                f"Answer: {answer}\n\nContext: {case['context']}\n\n"
                f"Respond as JSON: {{\"claims\": [{{\"claim\": \"...\", \"supported\": true/false}}]}}"
            )
            faith_resp = await chat(client, [{"role": "user", "content": faith_prompt}])
            try:
                cleaned = re.sub(r"```json\s*|\s*```", "", faith_resp)
                faith_data = json.loads(cleaned)
                claims = faith_data.get("claims", [])
                supported = sum(1 for c in claims if c.get("supported"))
                faithfulness = supported / len(claims) if claims else 0
            except (json.JSONDecodeError, KeyError):
                faithfulness = -1
                claims = []

            # Answer relevancy — embedding similarity between question and answer
            q_emb, a_emb = await embed(client, [case["question"], answer])
            relevancy = cosine_similarity(q_emb, a_emb)

            # Context precision — embedding similarity between question and context
            ctx_emb = (await embed(client, [case["context"]]))[0]
            precision = cosine_similarity(q_emb, ctx_emb)

            table = Table(title="Metrics")
            table.add_column("Metric", width=25)
            table.add_column("Score", width=10)
            table.add_column("Detail", max_width=50)
            table.add_row("Faithfulness", f"{faithfulness:.2f}" if faithfulness >= 0 else "error", f"{supported}/{len(claims)} claims supported" if claims else "parse error")
            table.add_row("Answer Relevancy", f"{relevancy:.4f}", "cosine(question, answer)")
            table.add_row("Context Precision", f"{precision:.4f}", "cosine(question, context)")
            console.print(table)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Module 09 — RAG Pipeline Lab")
    parser.add_argument("--task", choices=["A", "B", "C", "D", "E"], required=True)
    args = parser.parse_args()

    dispatch = {"A": task_a, "B": task_b, "C": task_c, "D": task_d, "E": task_e}
    asyncio.run(dispatch[args.task]())


if __name__ == "__main__":
    main()
