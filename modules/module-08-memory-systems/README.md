# Module 08: Memory Systems

## Overview

LLMs are stateless. Every API call starts cold — the model has no memory of
prior interactions, no knowledge of what it learned last session, and no
awareness of facts you've told it before. Memory systems are the infrastructure
you build to give an AI agent continuity.

This module covers the four memory types your agents will need, how to implement
each, and how to choose among them. By the end, you will have implemented all
four types against Azure OpenAI and Azure AI Search, and you'll understand the
retrieval and eviction tradeoffs that determine whether memory helps or hurts
at scale.

---

## Concepts

### 1. The Four Memory Types

Cognitive scientists distinguish procedural, semantic, episodic, and working
memory in humans. The same taxonomy maps cleanly to AI agent design:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     AGENT MEMORY ARCHITECTURE                        │
│                                                                      │
│  ┌──────────────────┐    ┌──────────────────┐                       │
│  │   IN-CONTEXT     │    │    EPISODIC       │                       │
│  │  (working mem)   │    │  (session facts)  │                       │
│  │                  │    │                  │                        │
│  │  Conversation    │    │  JSON on disk    │                        │
│  │  history buffer  │    │  per session_id  │                        │
│  │  + summaries     │    │                  │                        │
│  └────────┬─────────┘    └────────┬─────────┘                       │
│           │                       │                                  │
│           └──────────┬────────────┘                                  │
│                      │                                               │
│                      ▼                                               │
│              ┌───────────────┐                                       │
│              │  LLM CONTEXT  │  ← assembled at call time             │
│              │    WINDOW     │                                       │
│              └───────┬───────┘                                       │
│                      │                                               │
│           ┌──────────┴────────────┐                                  │
│           │                       │                                  │
│  ┌────────┴─────────┐    ┌────────┴─────────┐                       │
│  │    SEMANTIC      │    │   PROCEDURAL      │                       │
│  │  (long-term KB)  │    │ (tool sequences)  │                       │
│  │                  │    │                  │                        │
│  │  Azure AI Search │    │  Cached task     │                        │
│  │  vector store    │    │  execution plans │                        │
│  └──────────────────┘    └──────────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘
```

#### In-Context Memory (Working Memory)

The simplest form: you include prior conversation turns directly in the
`messages` array. The model "remembers" because it can read the history.

**ConversationBuffer** — keeps the last N turns verbatim. Dead simple.
Problem: token cost grows linearly with conversation length. At 128k context
windows and GPT-4o-mini at $0.15/M input tokens, 100 turns of a chatty
conversation costs real money and adds latency.

**SummarizingBuffer** — when the buffer exceeds a threshold, you call the LLM
to compress the oldest turns into a summary message. The summary replaces the
original turns. Recent turns stay verbatim (for accuracy); older turns become
a compressed summary (for efficiency).

```
messages = [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "[SUMMARY OF TURNS 1-40] User asked about X,
     we established Y, key facts: ..."},     ← compressed history
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "..."},      ← recent turns verbatim
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "current message"},
]
```

When to use in-context memory:
- Conversational agents where sequential context matters
- Tasks where the model needs to reason across many prior turns
- Short-lived sessions (< 50 turns) where summarization overhead isn't worth it

When NOT to use it:
- Knowledge that needs to persist across sessions
- Facts that must be updated without re-processing all history
- Knowledge bases larger than a few thousand tokens

#### Episodic Memory (Per-Session Scratchpad)

The agent extracts and stores discrete facts during a session. Facts are
written to a JSON file keyed by `session_id`. When a relevant query arrives,
the agent loads the fact file and injects the relevant facts into context.

```python
# Session 1 — user tells agent their preferences
user: "I'm building a FastAPI app that talks to PostgreSQL"
agent extracts: ["user uses FastAPI", "user uses PostgreSQL"]
→ saved to ./memory/session-abc123.json

# Session 2 — facts are loaded and injected
context = load_episodic("session-abc123")
# → "Known facts: user uses FastAPI, user uses PostgreSQL"
```

The extraction step uses an LLM call. The recall step does simple keyword
matching or semantic search against the stored facts.

Key design decision: what counts as a "fact" worth storing? You need a clear
extraction prompt that tells the model what to capture (entities, preferences,
constraints, decisions made) and what to ignore (pleasantries, filler).

#### Semantic Memory (Vector Store)

Long-term knowledge that persists across sessions and can be searched by
meaning rather than exact keyword. Azure AI Search serves as the vector store.

The lifecycle:
1. **Ingestion**: text → embedding → upsert into search index
2. **Retrieval**: query → embedding → vector similarity search → top-k chunks
3. **Injection**: retrieved chunks → injected into LLM context as facts

```
Document/Fact
     │
     ▼
Embedding Model (text-embedding-3-small)
     │ 1536-dimensional vector
     ▼
Azure AI Search Index
     │
     │  ← Query embedding at retrieval time
     ▼
HNSW similarity search
     │ top-k results
     ▼
Injected into LLM context
```

Why Azure AI Search vs. alternatives like Chroma or Pinecone?
- Managed service: no infrastructure to run
- Hybrid search: combines BM25 keyword search with vector search natively
- Integrated with Azure RBAC and Key Vault
- Production-grade SLAs and scaling

#### Procedural Memory (Tool Sequence Cache)

When an agent successfully completes a complex multi-step task, it saves the
sequence of tool calls that worked. On future similar queries, it retrieves the
cached sequence and replays it, skipping the planning overhead.

```python
# Agent completes task: "summarize all tickets in PROJECT-X"
# Tool sequence that worked:
[
    {"tool": "list_tickets", "args": {"project": "PROJECT-X"}},
    {"tool": "get_ticket", "args": {"id": "PROJ-1"}},
    {"tool": "get_ticket", "args": {"id": "PROJ-2"}},
    {"tool": "summarize", "args": {"tickets": [...]}},
]
# Saved to procedural memory under "summarize tickets PROJECT-X"

# Next time a similar task arrives, skip re-planning:
sequence = procedural_memory.find_similar("summarize tickets PROJECT-Y")
# → found! Replay with PROJECT-Y substituted
```

This is the memory type most specific to agentic (tool-using) systems. It
trades flexibility for speed — replaying a cached sequence is much faster and
cheaper than re-planning from scratch.

---

### 2. When to Use Each Type

| Memory Type | Scope | Speed | Cost | Best For |
|-------------|-------|-------|------|----------|
| In-Context (buffer) | Current session | Instant | Low-medium | Multi-turn chat, reasoning chains |
| In-Context (summary) | Current session | LLM call for summarize | Medium | Long chat sessions |
| Episodic | Per session, crosses turns | Fast (disk read) | Low | User preferences, session state |
| Semantic | Cross-session, large KB | Vector search latency | Medium (search + embedding) | Domain knowledge, documentation |
| Procedural | Cross-session | Fast (lookup) | Very low | Repeated task patterns |

The most common architecture combines all four:

1. **Semantic memory** holds the long-term knowledge base (documentation,
   company policies, domain facts)
2. **Episodic memory** tracks facts learned during this user's session
3. **In-context memory** holds the current conversation with a rolling summary
4. **Procedural memory** caches successful multi-step tool sequences

At inference time, the agent assembles context from all four layers:
```
[system prompt]
[semantic: top-3 relevant docs]
[episodic: known user facts]
[in-context: summary + recent turns]
[current user message]
```

---

### 3. Memory Lifecycle: Storage, Retrieval, Eviction

#### Storage

**In-context**: append to the messages list. No external storage needed.

**Episodic**: write to JSON on disk or to a lightweight database (SQLite,
Azure Table Storage). Key by `session_id`. Use atomic writes to avoid
corruption on concurrent access.

**Semantic**: embed the content, then upsert to Azure AI Search. Upsert
(not insert) is critical — if the same fact is updated, you want to overwrite
the old vector, not accumulate duplicates.

**Procedural**: write to JSON keyed by a normalized task description hash.
Simple key-value store is sufficient.

#### Retrieval

**In-context**: free — it's already in the messages list.

**Episodic**: load the session's JSON file, then optionally filter facts by
relevance. For simple cases, inject all facts. For large episodic stores, use
keyword matching or semantic search to inject only the top-k relevant facts.

**Semantic**: embed the query, run vector similarity search, return top-k
results. Azure AI Search's hybrid search combines vector similarity with BM25
keyword scoring — better recall than either alone.

**Procedural**: hash the task description, look up the cache. For fuzzy
matching, compute keyword overlap (Jaccard similarity) or use semantic search
against stored task descriptions.

#### Eviction

When memory grows unbounded, you need eviction policies:

| Memory Type | Eviction Strategy |
|-------------|-------------------|
| In-context buffer | Sliding window — drop oldest turns when over N |
| In-context summary | Compress turns beyond `max_recent` into a summary message |
| Episodic | TTL-based expiry; cap at N facts per session |
| Semantic | Explicit deletion API; importance scoring to drop low-value entries |
| Procedural | LRU cache; evict sequences not used in the last N days |

The hardest eviction problem is semantic memory: how do you know which stored
facts are still accurate? A vector store doesn't automatically invalidate
stale entries. In production, you need a metadata field (`updated_at`,
`expires_at`, `source_version`) and a background process to audit and prune.

---

### 4. Azure AI Search as Vector Store

Azure AI Search supports three search modes:
- **Full-text (BM25)**: keyword-based, fast, good for exact term matches
- **Vector search**: embedding-based, good for semantic similarity
- **Hybrid**: combines both with RRF (Reciprocal Rank Fusion) reranking

For memory systems, hybrid search almost always outperforms pure vector
search. It catches both "documents that use the exact same word" and
"documents that mean the same thing with different words."

#### Index Schema

```json
{
  "name": "memory-store",
  "fields": [
    { "name": "id",        "type": "Edm.String",               "key": true  },
    { "name": "content",   "type": "Edm.String",               "searchable": true },
    { "name": "embedding", "type": "Collection(Edm.Single)",
      "dimensions": 1536,  "vectorSearchProfile": "hnsw-profile" }
  ],
  "vectorSearch": {
    "algorithms": [{
      "name": "hnsw-config",
      "kind": "hnsw",
      "hnswParameters": {
        "m": 4,
        "efConstruction": 400,
        "efSearch": 500,
        "metric": "cosine"
      }
    }],
    "profiles": [{
      "name": "hnsw-profile",
      "algorithm": "hnsw-config"
    }]
  }
}
```

#### HNSW Parameters Explained

HNSW (Hierarchical Navigable Small World) is the approximate nearest neighbor
algorithm Azure AI Search uses for vector search.

- **m** (default 4): number of connections per node in the graph. Higher m =
  better recall but more memory. 4-16 is the typical range.
- **efConstruction** (default 400): candidate list size during index
  construction. Higher = better index quality but slower ingestion.
- **efSearch** (default 500): candidate list size during search. Higher =
  better recall but slower queries. Set this higher than m.
- **metric**: `cosine` for normalized embeddings (text-embedding-3-small
  outputs cosine-normalized vectors), `euclidean` or `dotProduct` for others.

For a memory system, m=4 and efConstruction=400 are fine. If recall matters
more than latency (common for semantic memory), increase efSearch to 1000.

#### Embedding Dimensions

| Model | Dimensions | Cost | Notes |
|-------|-----------|------|-------|
| text-embedding-3-small | 1536 | $0.02/M tokens | Good default |
| text-embedding-3-small | 512 | $0.02/M tokens | Truncated — lower quality |
| text-embedding-ada-002 | 1536 | $0.10/M tokens | Older, more expensive |
| text-embedding-3-large | 3072 | $0.13/M tokens | Highest quality |

For most memory applications, text-embedding-3-small at 1536 dimensions is
the right choice: low cost, good quality, widely available.

---

### 5. Common Memory Failure Modes

**Context stuffing**: injecting too much retrieved content. 10 semantic search
results at 300 tokens each = 3000 tokens burned before the conversation starts.
Always cap the number of retrieved chunks and truncate long ones.

**Stale episodic facts**: the user told the agent "I use PostgreSQL" in session
1. Three months later they switched to MySQL. The episodic store still says
PostgreSQL. Without TTL or explicit update logic, memory becomes a liability.

**Retrieval-relevance mismatch**: the vector search returns the top-5 docs by
cosine similarity, but they're all about adjacent topics, not the actual
question. If retrieval quality is poor, the model either ignores the context
or gets confused by it. Always log what was retrieved and whether the final
answer used it.

**Procedural hallucination**: the cached tool sequence worked for task A but
is retrieved for the similar-sounding but different task B. The agent replays
the wrong sequence. Mitigation: require higher similarity threshold for
procedural recall, and validate the sequence makes sense for the current task
before executing.

---

## Lab Tasks

### Setup

```bash
cd modules/module-08-memory-systems/lab
cp .env.example .env
# Edit .env — fill in Azure OpenAI and Azure AI Search credentials
# For Task C, first provision Azure AI Search:
#   cd ../terraform && terraform init && terraform apply
uv sync
```

---

### Task A: In-Context Memory

**Goal:** Implement `ConversationBuffer` and `SummarizingBuffer`.

1. Implement `ConversationBuffer` — a sliding window that keeps the last
   `max_turns` conversation exchanges. `get_messages()` returns the list
   ready to prepend to any LLM call.

2. Implement `SummarizingBuffer.summarize_older_turns()` — when the turn
   count exceeds `max_recent`, call Azure OpenAI to compress the older turns
   into a concise summary message. The summary becomes a single
   `{"role": "user", "content": "[SUMMARY] ..."}` entry.

3. Run a 15-turn simulated conversation. Compare token estimates between
   the raw buffer and the summarizing buffer after 15 turns.

**Run with:** `uv run memory --task A`

---

### Task B: Episodic Memory

**Goal:** Implement `EpisodicMemory` — extract and recall facts from session history.

1. Implement `extract_and_save(text)` — calls Azure OpenAI to identify key
   facts in the text (entities, preferences, decisions, constraints). Save
   each extracted fact to the session's JSON store.

2. Implement `recall(query, top_k=3)` — given a query string, return the
   most relevant stored facts. For the basic version, use keyword overlap
   (split query and facts into words, compute intersection). The advanced
   version uses embedding similarity.

3. Test: simulate 5 user messages that establish facts ("I'm building a
   Python service on Azure", "I prefer async patterns", etc.), then query
   "What stack is the user using?" and verify the right facts are recalled.

**Run with:** `uv run memory --task B`

---

### Task C: Semantic Memory (Azure AI Search)

**Goal:** Build a vector memory store backed by Azure AI Search.

1. Implement `create_index()` — create the Azure AI Search index with the
   HNSW vector search configuration. Use the schema shown in the Concepts
   section. Handle the case where the index already exists (HTTP 409 = ok).

2. Implement `embed_text(text)` — call the Azure OpenAI embeddings endpoint
   and return the 1536-dimensional vector.

3. Implement `upsert_memory(memory_id, content)` — embed the content and
   upload to the search index. Use the `@search.action: "mergeOrUpload"`
   action so repeated calls update rather than duplicate.

4. Implement `semantic_search(query, top_k=5)` — embed the query and run
   a vector search. Return a list of `{"content": str, "score": float}` dicts
   sorted by score descending.

5. Test the full cycle: upsert 5 memory documents, then run 3 queries and
   verify the right documents come back.

**Run with:** `uv run memory --task C`

---

### Task D: Procedural Memory

**Goal:** Cache and replay successful tool call sequences.

1. Implement `save_sequence(task_description, tool_calls)` — normalize the
   task description (lowercase, strip punctuation), hash it as the key, and
   persist the sequence to a JSON file.

2. Implement `find_similar(task_description, threshold=0.3)` — search all
   stored sequences for one where the Jaccard similarity between the query
   words and the stored task description words exceeds the threshold. Return
   the tool calls list, or None if no match.

3. Test: save a sequence for "list all open GitHub issues", then query for
   "show me open GitHub issues" and verify the sequence is retrieved. Query
   for "deploy to production" and verify None is returned.

**Advanced:** Replace keyword similarity with semantic search from Task C to
improve recall accuracy.

**Run with:** `uv run memory --task D`

---

## Conceptual Checkpoints

Answer these before moving to Module 09:

1. **Memory type selection**: A user is interacting with a code assistant.
   They ask 50 questions about the same codebase across 10 sessions. What
   combination of memory types would you use? What would you store in each?
   What eviction policy would each use?

2. **Eviction tradeoffs**: Your semantic memory index has grown to 500,000
   documents and search latency is climbing. You're considering two options:
   (a) increase the HNSW efSearch parameter to improve recall, or (b) prune
   old documents from the index. What are the tradeoffs of each? What metrics
   would you use to decide?

3. **Summarization accuracy**: The summarizing buffer compresses 40 turns of
   technical conversation into a 200-word summary. What information is most
   likely to be lost in compression? How would you design the summarization
   prompt to minimize loss of important technical context?

4. **Retrieval vs. injection**: For a customer support agent with a 10,000-
   document knowledge base, why is retrieval better than stuffing the full
   knowledge base into the system prompt? What are the failure modes specific
   to each approach?

5. **Procedural memory risks**: A cached tool sequence for "create a new
   user account" is retrieved for "create a new service account". Describe
   three specific ways this could go wrong. What would you add to the
   procedural memory schema to reduce this risk?

---

## Resources

- Azure AI Search vector search documentation:
  https://learn.microsoft.com/en-us/azure/search/vector-search-overview
- Azure AI Search index schema reference:
  https://learn.microsoft.com/en-us/azure/search/search-what-is-an-index
- HNSW algorithm paper (Malkov & Yashunin, 2018):
  https://arxiv.org/abs/1603.09320
- text-embedding-3-small model card:
  https://openai.com/blog/new-embedding-models-and-api-updates
- "MemGPT: Towards LLMs as Operating Systems" (hierarchical memory):
  https://arxiv.org/abs/2310.08560
