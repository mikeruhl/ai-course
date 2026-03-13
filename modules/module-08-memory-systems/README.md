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

**Goal:** Implement `ConversationBuffer` and `SummarizingBuffer` to see how sliding-window and summarization strategies trade off token cost versus context fidelity.

**What to do:**
1. Open `lab/src/memory_systems.py` and locate the `SummarizingBuffer` class
2. Implement `_summarize_older_turns()` (line ~136) — the `ConversationBuffer` class is already complete and serves as reference
3. The method must split `self._recent` into messages to compress and messages to keep, call Azure OpenAI via `_chat()` with `temperature=0`, store the summary in `self._summary`, and set `self._recent` to only the kept messages
4. Run the task:
   ```bash
   cd modules/module-08-memory-systems/lab
   uv run memory --task A
   ```

**Expected result:**
- A `ConversationBuffer(max_turns=3)` demo showing 6 messages retained after 7 turns, with oldest turns evicted
- A `SummarizingBuffer(max_recent=4)` demo showing 8 exchanges compressed into a summary + 4 recent messages
- A comparison table like:
  ```
  ┌─────────────────────────────────────┬─────────────────────┬────────────────┐
  │ Type                                │ Messages in context │ Token estimate │
  ├─────────────────────────────────────┼─────────────────────┼────────────────┤
  │ ConversationBuffer(max_turns=3)     │                   6 │             42 │
  │ SummarizingBuffer(max_recent=4)     │                   5 │             68 │
  └─────────────────────────────────────┴─────────────────────┴────────────────┘
  ```
- The summarizing buffer should have fewer messages but may have a higher token estimate because the summary itself contains compressed information

**Why this matters:**
In production chat agents, unbounded conversation history causes token cost to grow linearly per turn. The summarizing buffer is the standard pattern for long-running sessions — it preserves key facts (tech decisions, user preferences) while capping context size. Getting the summarization prompt right determines whether critical details survive compression.

**Run with:** `uv run memory --task A`

---

### Task B: Episodic Memory

**Goal:** Implement `EpisodicMemory` to extract discrete facts from conversation text and recall them by relevance query.

**What to do:**
1. Open `lab/src/memory_systems.py` and locate the `EpisodicMemory` class (line ~187)
2. Implement `extract_and_save(text)` (line ~216) — build a prompt that instructs the model to output a JSON array of standalone fact strings, call Azure OpenAI with `temperature=0`, parse the JSON, and call `self.save(fact)` for each
3. Implement `recall(query, top_k=3)` (line ~245) — load all stored facts, compute Jaccard similarity (`len(intersection) / len(union)` over word sets) between the query and each fact, return the top-k facts sorted by score
4. Run the task:
   ```bash
   cd modules/module-08-memory-systems/lab
   uv run memory --task B
   ```

**Expected result:**
- Five user messages are processed, each producing extracted facts:
  ```
  Input: I'm building a Python microservice on Azure Container Apps.
  Extracted: ["User is building a Python microservice", "User is using Azure Container Apps"]
  ```
- A recall table showing relevant facts matched to queries:
  ```
  ┌──────────────────────────────────────────────┬──────────────────────────────────────────────┐
  │ Query                                        │ Recalled Facts                               │
  ├──────────────────────────────────────────────┼──────────────────────────────────────────────┤
  │ What stack is the user using?                │ • User is building a Python microservice      │
  │                                              │ • User is using Azure Container Apps          │
  │                                              │ • User is using Azure Blob Storage            │
  ├──────────────────────────────────────────────┼──────────────────────────────────────────────┤
  │ Are there any security requirements?         │ • User handles medical data                   │
  │                                              │ • Encryption at rest is required              │
  └──────────────────────────────────────────────┴──────────────────────────────────────────────┘
  ```
- A JSON file created at `./memory/<session_id>.json` containing all extracted facts

**Why this matters:**
Episodic memory is how agents remember user-specific context across turns without re-asking. The extraction prompt quality directly determines what gets stored — too aggressive and you store noise, too conservative and you miss critical preferences. Jaccard recall is a cheap baseline; production systems upgrade to embedding-based recall for synonym handling.

**Run with:** `uv run memory --task B`

---

### Task C: Semantic Memory (Azure AI Search)

**Goal:** Build a vector memory store backed by Azure AI Search to demonstrate cross-session knowledge retrieval by semantic similarity.

**What to do:**
1. Open `lab/src/memory_systems.py` and locate the four standalone functions starting at line ~275
2. Implement `create_index()` (line ~275) — PUT the index definition to `{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}` with HNSW vector config (m=4, efConstruction=400, efSearch=500, cosine metric)
3. Implement `embed_text(text)` (line ~319) — POST to `EMBED_URL` with `{"input": text}`, return `response["data"][0]["embedding"]`
4. Implement `upsert_memory(memory_id, content)` (line ~340) — call `embed_text`, then POST to `docs/index` with `@search.action: "mergeOrUpload"`
5. Implement `semantic_search(query, top_k=5)` (line ~368) — embed the query, POST to `docs/search` with `vectorQueries`, return `[{"content": str, "score": float}]`
6. Provision Azure AI Search first, then run:
   ```bash
   cd modules/module-08-memory-systems/terraform
   terraform init && terraform apply
   cd ../lab
   # Update .env with AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY
   uv run memory --task C
   ```

**Expected result:**
- Index creation confirmation: `Index created: memory-store`
- Five memory documents upserted (Azure services descriptions)
- Three semantic search queries returning ranked results:
  ```
  Query: How does Azure handle secrets and credentials?
    1. (score=0.842) Azure Key Vault stores secrets, keys, and certificates...
    2. (score=0.791) Managed Identity allows Azure services to authenticate...
    3. (score=0.623) Azure OpenAI Service provides REST API access...

  Query: How do I avoid hardcoding passwords in my app?
    1. (score=0.811) Managed Identity allows Azure services to authenticate...
    2. (score=0.789) Azure Key Vault stores secrets, keys, and certificates...
  ```
- The paraphrased query ("avoid hardcoding passwords") should still retrieve the Key Vault and Managed Identity documents despite no shared keywords

**Why this matters:**
Semantic memory is the foundation of RAG and long-term agent knowledge. The upsert pattern (`mergeOrUpload`) prevents duplicate entries when facts are updated — a common production bug when using insert-only. The HNSW parameters you configure here directly control the recall-vs-latency tradeoff at query time.

**Run with:** `uv run memory --task C`

---

### Task D: Procedural Memory

**Goal:** Cache and replay successful tool call sequences to skip re-planning for repeated task patterns.

**What to do:**
1. Open `lab/src/memory_systems.py` and locate the `ProceduralMemory` class (line ~405)
2. Implement `save_sequence(task_description, tool_calls)` (line ~438) — call `self._normalize()` on the description, generate an MD5 hash key (`hashlib.md5(normalized.encode()).hexdigest()[:12]`), store to JSON via `self._load()` / `self._save()`
3. Implement `find_similar(task_description, threshold=0.3)` (line ~458) — normalize the query, split into word sets, compute Jaccard similarity against each stored entry, return the `tool_calls` list if best score >= threshold, else `None`
4. Run the task:
   ```bash
   cd modules/module-08-memory-systems/lab
   uv run memory --task D
   ```

**Expected result:**
- Three tool sequences saved (GitHub issues, Docker deploy, resource group creation):
  ```
  ┌────────────────────────────────────────────────────────────────────┬───────┐
  │ Description                                                      │ Steps │
  ├────────────────────────────────────────────────────────────────────┼───────┤
  │ list all open github issues in a repository                      │     2 │
  │ deploy a docker container to azure container apps                │     3 │
  │ create a new azure resource group and tag it                     │     2 │
  └────────────────────────────────────────────────────────────────────┴───────┘
  ```
- Four retrieval tests with match/no-match verification:
  ```
  OK MATCH    | expected MATCH    | Query: 'show me open GitHub issues'
       Retrieved 2 tool call(s): github_list_issues...
  OK MATCH    | expected MATCH    | Query: 'deploy container to Azure'
  OK NO MATCH | expected NO MATCH | Query: 'summarize all closed pull requests'
  OK MATCH    | expected MATCH    | Query: 'set up a new resource group'
  ```
- A `./memory/procedural.json` file containing the cached sequences

**Why this matters:**
Procedural memory turns an agent's successful task completions into reusable plans. This avoids redundant LLM planning calls for repeated workflows, reducing both latency and cost. The Jaccard threshold is the safety valve — set it too low and the agent replays wrong sequences for loosely similar tasks, set it too high and it never reuses anything.

**Advanced:** Replace keyword similarity with semantic search from Task C to improve recall accuracy.

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
