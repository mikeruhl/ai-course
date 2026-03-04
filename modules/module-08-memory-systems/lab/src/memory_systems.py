"""
Module 08 Lab — Memory Systems
================================
Implement the four memory types used in AI agent architectures.

Tasks:
  A. In-Context Memory — ConversationBuffer and SummarizingBuffer
  B. Episodic Memory   — extract facts from session text, recall by query
  C. Semantic Memory   — Azure AI Search vector store (create, upsert, search)
  D. Procedural Memory — cache and replay successful tool call sequences

Run with:
    uv run memory --task A
    uv run memory --task B
    uv run memory --task C   # requires Azure AI Search (run terraform first)
    uv run memory --task D
"""

import asyncio
import hashlib
import json
import os
import re
import time
from collections import deque
from pathlib import Path

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

CHAT_URL = (
    f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}"
    f"/chat/completions?api-version={API_VERSION}"
)
EMBED_URL = (
    f"{ENDPOINT}/openai/deployments/{EMBEDDING_DEPLOYMENT}"
    f"/embeddings?api-version={API_VERSION}"
)
HEADERS = {"api-key": API_KEY, "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# Azure AI Search connection constants (Task C)
# ---------------------------------------------------------------------------
SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
SEARCH_KEY = os.environ.get("AZURE_SEARCH_KEY", "")
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX", "memory-store")
SEARCH_HEADERS = {"api-key": SEARCH_KEY, "Content-Type": "application/json"}
SEARCH_API_VERSION = "2024-07-01"

console = Console()


# ===========================================================================
# Task A: In-Context Memory
# ===========================================================================

class ConversationBuffer:
    """
    Sliding-window conversation buffer.

    Keeps the last `max_turns` exchanges (user + assistant pairs = 1 turn).
    Older turns are dropped once the limit is exceeded.
    """

    def __init__(self, max_turns: int = 10) -> None:
        self.max_turns = max_turns
        # Each item is {"role": str, "content": str}
        self._messages: deque[dict] = deque()

    def add(self, role: str, content: str) -> None:
        """Append a message. Evict oldest turn pair if over the limit."""
        self._messages.append({"role": role, "content": content})
        # Each "turn" is a user + assistant pair = 2 messages.
        # When we exceed max_turns * 2 messages, pop from the left.
        while len(self._messages) > self.max_turns * 2:
            self._messages.popleft()

    def get_messages(self) -> list[dict]:
        """Return current message history as a list, ready for the messages= parameter."""
        return list(self._messages)

    def token_estimate(self) -> int:
        """
        Rough token estimate: sum of all content character counts divided by 4.
        Rule of thumb: 1 token ≈ 4 characters for English text.
        """
        total_chars = sum(len(m["content"]) for m in self._messages)
        return total_chars // 4

    def __len__(self) -> int:
        return len(self._messages)


class SummarizingBuffer:
    """
    Conversation buffer that compresses old turns into a summary.

    Keeps the `max_recent` most recent messages verbatim.
    When total message count exceeds max_recent, the older messages
    are compressed into a single summary entry via an LLM call.

    The summary is stored as:
        {"role": "user", "content": "[SUMMARY OF PRIOR CONVERSATION] ..."}
    This is prepended to the recent turns when building the context.
    """

    def __init__(self, max_recent: int = 5) -> None:
        self.max_recent = max_recent
        self._recent: list[dict] = []
        self._summary: str | None = None  # compressed history

    async def add(self, role: str, content: str) -> None:
        """
        Add a message. If recent messages exceed max_recent, summarize the
        excess before adding the new one.
        """
        self._recent.append({"role": role, "content": content})

        if len(self._recent) > self.max_recent:
            await self._summarize_older_turns()

    async def _summarize_older_turns(self) -> None:
        """
        Compress messages beyond the keep window into a summary.

        TODO: implement this method.

        Steps:
        1. Split self._recent into:
           - to_compress: all but the last self.max_recent messages
           - to_keep:     the last self.max_recent messages
        2. Build a prompt that includes:
           - The existing summary (if self._summary is not None) as prior context
           - The to_compress messages formatted as a conversation transcript
           - Instruction: produce a concise factual summary in 3-5 sentences that
             preserves all technical details, decisions made, and user preferences
        3. Call Azure OpenAI (use the _chat() helper below) with temperature=0
        4. Store the response content in self._summary
        5. Set self._recent = to_keep
        """
        raise NotImplementedError(
            "Task A: implement _summarize_older_turns()\n"
            "See docstring above for the exact steps."
        )

    def get_messages(self) -> list[dict]:
        """
        Return the assembled context: summary (if any) + recent turns.

        If a summary exists, it is prepended as a user message so the model
        can read it naturally as part of the conversation history.
        """
        messages = []
        if self._summary:
            messages.append({
                "role": "user",
                "content": f"[SUMMARY OF PRIOR CONVERSATION]\n{self._summary}",
            })
        messages.extend(self._recent)
        return messages

    def token_estimate(self) -> int:
        """Rough token estimate for the assembled context."""
        summary_chars = len(self._summary) if self._summary else 0
        recent_chars = sum(len(m["content"]) for m in self._recent)
        return (summary_chars + recent_chars) // 4


# ===========================================================================
# Task B: Episodic Memory
# ===========================================================================

class EpisodicMemory:
    """
    Per-session fact store. Extracts discrete facts from conversation text
    and persists them to a JSON file for recall within and across sessions.

    Storage: ./memory/<session_id>.json
    Format:  {"session_id": str, "facts": [str, ...]}
    """

    def __init__(self, session_id: str, storage_dir: str = "./memory") -> None:
        self.session_id = session_id
        self.storage_path = Path(storage_dir) / f"{session_id}.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, fact: str) -> None:
        """Append a fact to the session's JSON store."""
        existing = self.load()
        if fact not in existing:  # deduplicate
            existing.append(fact)
        data = {"session_id": self.session_id, "facts": existing}
        self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> list[str]:
        """Load all facts for this session. Returns empty list if none stored."""
        if not self.storage_path.exists():
            return []
        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        return data.get("facts", [])

    async def extract_and_save(self, text: str) -> list[str]:
        """
        Use Azure OpenAI to extract key facts from `text`, then save them.

        TODO: implement this method.

        Steps:
        1. Build a prompt asking the model to extract factual statements from
           the text. Good facts to extract: technologies mentioned, decisions
           made, user preferences stated, constraints described, named entities.
           The prompt should instruct the model to output a JSON array of strings,
           one fact per string. Each fact should be a complete, standalone sentence.
           Example output: ["User is building a FastAPI application",
                            "The application stores data in PostgreSQL",
                            "User prefers async patterns over sync"]
        2. Call Azure OpenAI with temperature=0 (for determinism)
        3. Parse the JSON array from the response
        4. Call self.save(fact) for each extracted fact
        5. Return the list of extracted facts

        Edge cases:
        - If the model returns invalid JSON, log a warning and return []
        - If the text contains no extractable facts, expect the model to return []
        """
        raise NotImplementedError(
            "Task B: implement extract_and_save()\n"
            "See docstring above for the extraction approach."
        )

    async def recall(self, query: str, top_k: int = 3) -> list[str]:
        """
        Return the top_k most relevant facts for a given query.

        TODO: implement this method.

        Basic approach (implement this first):
        - Load all stored facts
        - Compute Jaccard similarity between query words and each fact's words:
            query_words = set(query.lower().split())
            fact_words  = set(fact.lower().split())
            score = len(query_words & fact_words) / len(query_words | fact_words)
        - Sort facts by score descending, return top_k

        Advanced approach (implement after basic works):
        - Use embed_text() to embed the query and each fact
        - Compute cosine similarity and rank by that instead

        Return the list of fact strings (not scores).
        """
        raise NotImplementedError(
            "Task B: implement recall()\n"
            "Start with Jaccard similarity — see docstring above."
        )


# ===========================================================================
# Task C: Semantic Memory (Azure AI Search)
# ===========================================================================

async def create_index() -> None:
    """
    Create the Azure AI Search index for semantic memory storage.

    TODO: implement this function.

    Steps:
    1. Build the index definition dict with this schema:
       - id (Edm.String, key=True, filterable=True)
       - content (Edm.String, searchable=True, retrievable=True)
       - embedding (Collection(Edm.Single), dimensions=1536,
                    vectorSearchProfile="hnsw-profile")
    2. Include a vectorSearch config block with:
       - algorithms: one entry, kind="hnsw", name="hnsw-config",
         hnswParameters: m=4, efConstruction=400, efSearch=500, metric="cosine"
       - profiles: one entry, name="hnsw-profile", algorithm="hnsw-config"
    3. PUT to {SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}?api-version={SEARCH_API_VERSION}
       (PUT is idempotent — it creates or updates)
    4. Log "Index created: <name>" on success
    5. On HTTP error: print the response body for debugging, then raise

    Reference schema shape:
    {
      "name": SEARCH_INDEX,
      "fields": [
        {"name": "id",        "type": "Edm.String", "key": True,  "filterable": True},
        {"name": "content",   "type": "Edm.String", "searchable": True, "retrievable": True},
        {"name": "embedding", "type": "Collection(Edm.Single)",
         "dimensions": 1536, "vectorSearchProfile": "hnsw-profile",
         "searchable": True, "retrievable": False},
      ],
      "vectorSearch": {
        "algorithms": [{"name": "hnsw-config", "kind": "hnsw",
          "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"}}],
        "profiles": [{"name": "hnsw-profile", "algorithm": "hnsw-config"}],
      }
    }
    """
    raise NotImplementedError(
        "Task C: implement create_index()\n"
        "See docstring above for the full index schema."
    )


async def embed_text(text: str) -> list[float]:
    """
    Get a 1536-dimensional embedding vector for `text` from Azure OpenAI.

    TODO: implement this function.

    Steps:
    1. POST to EMBED_URL with body: {"input": text}
    2. The response shape is:
       {"data": [{"embedding": [float, ...], "index": 0}], "usage": {...}}
    3. Return response["data"][0]["embedding"]

    Note: text-embedding-3-small returns cosine-normalized vectors, so cosine
    similarity is equivalent to dot product for these embeddings.
    """
    raise NotImplementedError(
        "Task C: implement embed_text()\n"
        "POST to EMBED_URL and extract response['data'][0]['embedding']."
    )


async def upsert_memory(memory_id: str, content: str) -> None:
    """
    Embed `content` and upsert the document into the Azure AI Search index.

    TODO: implement this function.

    Steps:
    1. Call embed_text(content) to get the embedding vector
    2. Build the upload payload:
       {
         "value": [{
           "@search.action": "mergeOrUpload",
           "id": memory_id,
           "content": content,
           "embedding": <vector>
         }]
       }
    3. POST to {SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/index
       ?api-version={SEARCH_API_VERSION}
    4. Check response status — 200 or 201 means success
    5. Log "Upserted: <memory_id>" on success
    """
    raise NotImplementedError(
        "Task C: implement upsert_memory()\n"
        "Embed content, then POST to the search index docs/index endpoint."
    )


async def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Run a vector similarity search and return the top-k most relevant memories.

    TODO: implement this function.

    Steps:
    1. Call embed_text(query) to get the query vector
    2. Build the search payload:
       {
         "vectorQueries": [{
           "kind": "vector",
           "vector": <query_vector>,
           "fields": "embedding",
           "k": top_k
         }],
         "select": "id,content",
         "top": top_k
       }
    3. POST to {SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search
       ?api-version={SEARCH_API_VERSION}
    4. The response shape is: {"value": [{"id": ..., "content": ..., "@search.score": ...}]}
    5. Map each result to {"content": doc["content"], "score": doc["@search.score"]}
    6. Return the list sorted by score descending

    Tip: '@search.score' for vector search is the cosine similarity (0.0-1.0).
    """
    raise NotImplementedError(
        "Task C: implement semantic_search()\n"
        "Embed the query, then POST to docs/search with vectorQueries."
    )


# ===========================================================================
# Task D: Procedural Memory (Tool Sequence Cache)
# ===========================================================================

class ProceduralMemory:
    """
    Cache for successful agent tool call sequences.

    When an agent completes a task successfully, it saves the sequence of
    (tool_name, args) pairs that worked. On future similar queries, the
    cached sequence is retrieved and can be replayed directly.

    Storage: ./memory/procedural.json
    Format: {
        "<normalized_task_hash>": {
            "description": str,
            "tool_calls": [{"tool": str, "args": dict}, ...]
        }
    }
    """

    def __init__(self, storage_path: str = "./memory/procedural.json") -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.storage_path.exists():
            return {}
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _normalize(self, text: str) -> str:
        """Lowercase and strip non-alphanumeric characters for consistent matching."""
        return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()

    def save_sequence(self, task_description: str, tool_calls: list[dict]) -> None:
        """
        Persist a successful tool call sequence.

        TODO: implement this method.

        Steps:
        1. Normalize task_description using self._normalize()
        2. Generate a storage key: hashlib.md5(normalized.encode()).hexdigest()[:12]
        3. Load existing data with self._load()
        4. Add or overwrite the entry:
           data[key] = {"description": normalized, "tool_calls": tool_calls}
        5. Save with self._save(data)
        6. Log: "Saved procedural sequence for: <task_description[:60]>"
        """
        raise NotImplementedError(
            "Task D: implement save_sequence()\n"
            "Normalize the description, hash it as the key, save to JSON."
        )

    def find_similar(
        self, task_description: str, threshold: float = 0.3
    ) -> list[dict] | None:
        """
        Find a cached tool sequence for a task similar to `task_description`.

        Returns the tool_calls list if a match above `threshold` is found,
        or None if no suitable match exists.

        TODO: implement this method.

        Steps:
        1. Normalize task_description
        2. Split into a set of words: query_words = set(normalized.split())
        3. Load all stored sequences with self._load()
        4. For each stored entry, compute Jaccard similarity:
             stored_words = set(entry["description"].split())
             intersection = query_words & stored_words
             union        = query_words | stored_words
             score = len(intersection) / len(union) if union else 0.0
        5. Find the entry with the highest score
        6. If highest score >= threshold: return entry["tool_calls"]
        7. Otherwise: return None

        Log the best match found (score and description) regardless of threshold.
        """
        raise NotImplementedError(
            "Task D: implement find_similar()\n"
            "Use Jaccard similarity over normalized word sets — see docstring."
        )

    def list_sequences(self) -> list[dict]:
        """Return all stored sequences as [{"description": str, "steps": int}, ...]."""
        data = self._load()
        return [
            {"description": v["description"], "steps": len(v["tool_calls"])}
            for v in data.values()
        ]


# ===========================================================================
# HTTP Helpers
# ===========================================================================

async def _chat(
    messages: list[dict],
    client: httpx.AsyncClient,
    temperature: float = 0,
    max_tokens: int = 800,
) -> str:
    """Call Azure OpenAI chat completions. Returns the assistant content string."""
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = await client.post(CHAT_URL, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ===========================================================================
# Task runners
# ===========================================================================

async def run_task_a() -> None:
    """Demonstrate in-context memory: ConversationBuffer and SummarizingBuffer."""
    console.rule("[bold cyan]Task A: In-Context Memory[/bold cyan]")

    # --- ConversationBuffer demo ---
    console.print("\n[bold]ConversationBuffer (max_turns=3)[/bold]")
    buf = ConversationBuffer(max_turns=3)
    for i in range(1, 8):
        buf.add("user", f"User message {i}")
        buf.add("assistant", f"Assistant reply {i}")

    msgs = buf.get_messages()
    console.print(f"Buffer holds {len(msgs)} messages after 7 turns (max=3 turns = 6 msgs):")
    for m in msgs:
        console.print(f"  [{m['role']}] {m['content']}")
    console.print(f"Token estimate: ~{buf.token_estimate()} tokens")

    # --- SummarizingBuffer demo ---
    console.print("\n[bold]SummarizingBuffer (max_recent=4)[/bold]")
    async with httpx.AsyncClient() as client:
        sbuf = SummarizingBuffer(max_recent=4)

        # Simulate a technical conversation
        exchanges = [
            ("user", "I'm building a FastAPI app that connects to PostgreSQL."),
            ("assistant", "Great choice. I can help with async SQLAlchemy patterns."),
            ("user", "I want to use async patterns throughout — no sync blocking."),
            ("assistant", "Then use asyncpg directly or SQLAlchemy with asyncio support."),
            ("user", "What about connection pooling?"),
            ("assistant", "asyncpg has a built-in pool. Recommended pool size is 10-20."),
            ("user", "Should I use Alembic for migrations?"),
            ("assistant", "Yes. Alembic is the standard for SQLAlchemy-based migrations."),
        ]

        for role, content in exchanges:
            await sbuf.add(role, content)
            console.print(
                f"  Added [{role}]: {content[:50]}... "
                f"(buffer size: {len(sbuf._recent)} msgs)"
            )

    assembled = sbuf.get_messages()
    console.print(f"\nFinal assembled context ({len(assembled)} messages):")
    for m in assembled:
        preview = m["content"][:80].replace("\n", " ")
        console.print(f"  [{m['role']}] {preview}...")
    console.print(f"Token estimate: ~{sbuf.token_estimate()} tokens")

    # Comparison table
    table = Table(title="Memory Buffer Comparison — 7 turns of conversation")
    table.add_column("Type")
    table.add_column("Messages in context", justify="right")
    table.add_column("Token estimate", justify="right")
    table.add_row(
        "ConversationBuffer(max_turns=3)",
        str(len(buf.get_messages())),
        str(buf.token_estimate()),
    )
    table.add_row(
        "SummarizingBuffer(max_recent=4)",
        str(len(assembled)),
        str(sbuf.token_estimate()),
    )
    console.print(table)


async def run_task_b() -> None:
    """Demonstrate episodic memory: extract facts, persist, and recall."""
    console.rule("[bold cyan]Task B: Episodic Memory[/bold cyan]")

    session_id = f"demo-{int(time.time())}"
    mem = EpisodicMemory(session_id=session_id)
    console.print(f"Session ID: {session_id}")

    async with httpx.AsyncClient() as client:
        # Simulate a user establishing context across 5 messages
        messages = [
            "I'm building a Python microservice on Azure Container Apps.",
            "The service needs to process images — I'm using Azure Blob Storage for that.",
            "I prefer async patterns throughout and hate callback-based code.",
            "We're a team of 3, and we use GitHub Actions for CI/CD.",
            "Security is critical — we handle medical data, so we need encryption at rest.",
        ]

        console.print("\n[bold]Extracting facts from session messages...[/bold]")
        all_facts: list[str] = []
        for msg in messages:
            console.print(f"\n  Input: {msg}")
            facts = await mem.extract_and_save(msg)
            console.print(f"  Extracted: {facts}")
            all_facts.extend(facts)

        console.print(f"\nTotal facts stored: {len(mem.load())}")

        # Recall queries
        console.print("\n[bold]Recall queries:[/bold]")
        queries = [
            "What stack is the user using?",
            "What are the user's deployment and CI preferences?",
            "Are there any security requirements?",
        ]

        table = Table(title="Episodic Memory Recall")
        table.add_column("Query", style="cyan")
        table.add_column("Recalled Facts")

        for q in queries:
            recalled = await mem.recall(q, top_k=3)
            table.add_row(q, "\n".join(f"• {f}" for f in recalled))

        console.print(table)


async def run_task_c() -> None:
    """Demonstrate semantic memory: create index, upsert, and vector search."""
    console.rule("[bold cyan]Task C: Semantic Memory (Azure AI Search)[/bold cyan]")

    if not SEARCH_ENDPOINT or not SEARCH_KEY:
        console.print(
            "[red]AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY are required for Task C.\n"
            "Run terraform apply in the terraform/ directory first, then set these "
            "environment variables in your .env file.[/red]"
        )
        return

    # Step 1: Create the index
    console.print("\n[bold]Step 1: Creating search index...[/bold]")
    await create_index()

    # Step 2: Upsert memory documents
    console.print("\n[bold]Step 2: Upserting memory documents...[/bold]")
    memories = {
        "mem-001": "Azure Container Apps is a serverless container hosting service that supports Dapr and KEDA for event-driven scaling.",
        "mem-002": "Azure Key Vault stores secrets, keys, and certificates with RBAC-based access control and HSM backing.",
        "mem-003": "Azure AI Search supports vector search using HNSW approximate nearest neighbor with cosine, euclidean, or dotProduct distance metrics.",
        "mem-004": "Managed Identity allows Azure services to authenticate to other Azure resources without storing credentials in application code.",
        "mem-005": "Azure OpenAI Service provides REST API access to GPT-4o, GPT-4o-mini, and embedding models deployed in your own Azure subscription.",
    }

    for mem_id, content in memories.items():
        await upsert_memory(mem_id, content)
        console.print(f"  Upserted: {mem_id}")

    # Wait briefly for index to refresh
    console.print("\n[dim]Waiting 2 seconds for index to refresh...[/dim]")
    await asyncio.sleep(2)

    # Step 3: Search
    console.print("\n[bold]Step 3: Semantic search queries...[/bold]")
    queries = [
        "How does Azure handle secrets and credentials?",
        "What options exist for vector similarity search?",
        "How do I avoid hardcoding passwords in my app?",
    ]

    for q in queries:
        console.print(f"\n  Query: [cyan]{q}[/cyan]")
        results = await semantic_search(q, top_k=3)
        for i, r in enumerate(results, 1):
            console.print(f"    {i}. (score={r['score']:.3f}) {r['content'][:80]}...")


async def run_task_d() -> None:
    """Demonstrate procedural memory: save and retrieve tool sequences."""
    console.rule("[bold cyan]Task D: Procedural Memory[/bold cyan]")

    mem = ProceduralMemory()

    # Save some known-good sequences
    console.print("\n[bold]Saving known-good tool sequences...[/bold]")

    sequences = [
        (
            "list all open GitHub issues in a repository",
            [
                {"tool": "github_list_issues", "args": {"state": "open", "repo": "{{repo}}"}},
                {"tool": "format_table", "args": {"fields": ["number", "title", "assignee"]}},
            ],
        ),
        (
            "deploy a Docker container to Azure Container Apps",
            [
                {"tool": "docker_build", "args": {"tag": "{{image_tag}}"}},
                {"tool": "acr_push", "args": {"registry": "{{acr_name}}", "tag": "{{image_tag}}"}},
                {"tool": "aca_update", "args": {"app": "{{app_name}}", "image": "{{image_tag}}"}},
            ],
        ),
        (
            "create a new Azure resource group and tag it",
            [
                {"tool": "az_group_create", "args": {"name": "{{rg_name}}", "location": "{{location}}"}},
                {"tool": "az_tag_resource", "args": {"resource": "{{rg_name}}", "tags": "{{tags}}"}},
            ],
        ),
    ]

    for desc, tool_calls in sequences:
        mem.save_sequence(desc, tool_calls)

    # Show stored sequences
    stored = mem.list_sequences()
    table = Table(title="Stored Procedural Sequences")
    table.add_column("Description", style="cyan")
    table.add_column("Steps", justify="right")
    for s in stored:
        table.add_row(s["description"][:70], str(s["steps"]))
    console.print(table)

    # Retrieval tests
    console.print("\n[bold]Retrieval tests:[/bold]")
    test_queries = [
        ("show me open GitHub issues", True),         # should match
        ("deploy container to Azure", True),           # should match
        ("summarize all closed pull requests", False), # should NOT match
        ("set up a new resource group", True),         # should match
    ]

    for query, expect_match in test_queries:
        result = mem.find_similar(query)
        status = "[green]MATCH[/green]" if result else "[yellow]NO MATCH[/yellow]"
        expected = "expected MATCH" if expect_match else "expected NO MATCH"
        ok = (result is not None) == expect_match
        icon = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        console.print(f"  {icon} {status} | {expected} | Query: '{query}'")
        if result:
            console.print(f"       Retrieved {len(result)} tool call(s): {result[0]['tool']}...")


# ===========================================================================
# Entry point
# ===========================================================================

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Module 08 — Memory Systems Lab")
    parser.add_argument(
        "--task",
        choices=["A", "B", "C", "D"],
        required=True,
        help=(
            "A=In-Context, B=Episodic, C=Semantic (requires Azure AI Search), "
            "D=Procedural"
        ),
    )
    args = parser.parse_args()

    task_map = {
        "A": run_task_a,
        "B": run_task_b,
        "C": run_task_c,
        "D": run_task_d,
    }
    asyncio.run(task_map[args.task]())


if __name__ == "__main__":
    main()
