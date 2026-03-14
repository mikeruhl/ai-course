# Module 09: Retrieval-Augmented Generation (RAG)

## Overview

LLMs have two fundamental limitations for knowledge-intensive tasks: their
training data has a cutoff date, and they hallucinate — generating plausible-
sounding but incorrect facts when they don't have reliable knowledge. RAG
(Retrieval-Augmented Generation) addresses both by connecting the model to an
external knowledge store at inference time.

The core idea is simple: before calling the LLM, retrieve relevant documents
from your knowledge base and inject them into the prompt. The model answers
based on the provided context rather than parametric memory. This makes
factual errors auditable (wrong answer = wrong retrieval) and the knowledge
base updatable without retraining.

By the end of this module you will have built a full RAG pipeline: document
chunking, embedding and ingestion, three retrieval modes (vector, keyword,
hybrid), RAG prompt construction, and RAGAS-style evaluation metrics.

---

## Concepts

### 1. Why RAG Exists

The failure mode RAG solves is *retrieval-answer mismatch* — when the model's
parametric knowledge is out of date, domain-specific, or simply wrong:

```
Without RAG:
  User: "What are the rate limits for Azure OpenAI gpt-4o-mini in March 2025?"
  Model: [Generates plausible-sounding limits that may be months out of date]

With RAG:
  Step 1: Retrieve from your documentation index
    → "As of 2025-03, gpt-4o-mini rate limits: 200 RPM, 2M TPM (standard)"
  Step 2: Inject as context, model answers from the retrieved text
  → Grounded, auditable answer
```

Three scenarios where RAG consistently beats a standalone LLM:
- **Private knowledge**: internal documentation, proprietary data, customer
  records the model has never seen
- **Freshness**: anything that changes faster than the model's training cutoff
  (pricing, API specs, news, policy documents)
- **Long documents**: when the relevant content is buried in a 200-page PDF
  that won't fit in a single context window

### 2. Chunking Strategies

Documents must be split into chunks before embedding. The chunk is the unit
of retrieval — what you get back from search is a chunk, not the full document.
Chunk size is one of the highest-leverage parameters in a RAG system.

```
Original document (10,000 chars)
         │
         ▼
   ┌───────────┐
   │  Chunker  │
   └───────────┘
         │
   ┌─────┼─────┐
   ▼     ▼     ▼
[c1]  [c2]  [c3]  ...  [cN]    ← each chunk ~500 chars with 50 char overlap
```

**Overlap** is essential: without it, a sentence that spans a chunk boundary
is split in half, and neither half is retrievable. With 50-100 char overlap,
the same sentence appears (partially) in two adjacent chunks.

#### Fixed-Size Chunking

Split every N characters with M characters of overlap. Fast, simple, no NLP
required. Problem: completely ignores sentence and paragraph boundaries. A
chunk may start mid-sentence or cut a table in half.

Best for: raw text logs, structured data where sentence semantics don't apply.

#### Sentence Boundary Chunking

Split on sentence boundaries (`.`, `!`, `?`), then greedily group sentences
until you hit `max_chunk_chars`. Clean semantic units. Problem: code blocks,
headers, and list items confuse the sentence detector.

Best for: prose documents (blog posts, documentation prose sections).

#### Recursive Character Splitting

Try separators in order of preference: `\n\n` (paragraph), `\n` (line),
`. ` (sentence), ` ` (word). At each level, if a piece is still too large,
recurse into the next separator level.

```
text.split("\n\n") → if piece > max: piece.split("\n") → if piece > max: piece.split(". ")
```

This is the default strategy in LangChain's RecursiveCharacterTextSplitter and
is the best general-purpose chunker. It respects natural document structure as
much as possible.

Best for: mixed content (markdown docs, code comments + prose).

#### Semantic Chunking

Embed each sentence, then group consecutive sentences that are semantically
similar (cosine similarity above a threshold). Start a new chunk when there
is a large semantic jump.

```
sentence 1 ─────────────────────────► embedding
sentence 2 ─────────────────────────► embedding
cosine(embed1, embed2) = 0.92  → same chunk

sentence 3 ─────────────────────────► embedding
cosine(embed2, embed3) = 0.41  → NEW CHUNK
```

Best for: long documents where topics shift abruptly (research papers, books).
Most expensive — requires N embedding calls just to chunk.

#### Chunking Tradeoffs

| Strategy | Speed | Boundary Quality | Cost | Best For |
|----------|-------|-----------------|------|----------|
| Fixed-size | Fastest | Poor | None | Logs, structured data |
| Sentence boundary | Fast | Good for prose | None | Documentation, articles |
| Recursive | Fast | Good for mixed | None | General purpose (default) |
| Semantic | Slow | Excellent | N embeddings | Long topic-shifting docs |

**Chunk size tradeoffs:**
- Too small (< 100 chars): individual sentences lack context; retrieved chunks
  may not contain enough information to answer the question
- Too large (> 1500 chars): you include irrelevant content adjacent to the
  relevant sentence, diluting the signal; you can fit fewer chunks in context
- Sweet spot for dense technical docs: 300-600 chars with 50-100 char overlap

---

### 3. Embedding Models

An embedding model maps text to a dense vector in a high-dimensional space,
where semantically similar texts are geometrically close.

```
"Azure Key Vault stores secrets"
    │
    ▼
text-embedding-3-small
    │
    ▼
[0.023, -0.147, 0.891, ..., 0.034]   ← 1536 floats
```

#### Model Comparison

| Model | Dimensions | Cost (per 1M tokens) | Notes |
|-------|-----------|---------------------|-------|
| text-embedding-3-small | 1536 | $0.02 | Best cost/quality ratio |
| text-embedding-ada-002 | 1536 | $0.10 | Older, 5x more expensive |
| text-embedding-3-large | 3072 | $0.13 | Best quality, 6.5x more expensive |

For most RAG applications, text-embedding-3-small at 1536 dimensions is the
right default. The quality gap versus 3-large is measurable on benchmarks
but often not noticeable in production retrieval quality.

**Dimension reduction**: text-embedding-3-small supports outputting fewer
dimensions (e.g., 512) via the `dimensions` parameter. Lower dimensions mean
smaller storage and faster search at some quality cost. For memory-constrained
deployments, 512-768 dimensions are viable.

---

### 4. Dense vs. Sparse Retrieval

Two fundamentally different approaches to "find relevant documents for this query":

#### Sparse Retrieval (BM25 / Keyword)

BM25 (Best Match 25) is a bag-of-words ranking algorithm. For each document,
it computes a score based on term frequency (how often the query word appears
in the document) and inverse document frequency (how rare that word is across
all documents). The "25" refers to the 25th version of this tuning family.

```
BM25 score for doc D and query Q:
  score(D, Q) = Σ IDF(qi) * (tf(qi, D) * (k1+1)) / (tf(qi, D) + k1*(1-b+b*|D|/avgdl))

where: tf = term frequency, IDF = inverse document frequency,
       k1 = 1.2 (term saturation), b = 0.75 (length normalization)
```

When BM25 wins:
- The query uses exact domain-specific terminology ("HNSW", "efConstruction")
- The user is searching for a specific code snippet, error message, or ID
- The answer is a direct quote that must contain the exact query words

When BM25 fails:
- The document uses synonyms or paraphrases of the query terms
- Cross-language search (query in English, doc in German)
- Conceptual queries ("how do I authenticate?") where the relevant doc says
  "using Managed Identity" not "authenticate"

#### Dense Retrieval (Vector / Semantic)

Embed both the query and documents into the same vector space. Retrieve
documents whose embedding vectors are most similar to the query vector.
Similarity is typically measured with cosine similarity.

When vector search wins:
- Synonyms and paraphrases: "IAM" and "identity management" land near each
  other in embedding space even without shared words
- Conceptual queries: "how do I secure my app?" retrieves docs about auth,
  encryption, and RBAC even without those exact words in the query
- Cross-language retrieval (with multilingual embedding models)

When vector search fails:
- Rare terms and proper nouns the embedding model hasn't seen often: exact
  error codes, internal product names, version numbers
- Very long documents: averaging or pooling token embeddings loses fine-grained
  term information
- Queries where exact keyword match is essential (legal, compliance contexts)

---

### 5. Hybrid Search with RRF

Neither BM25 nor vector search dominates across all query types. Hybrid
search combines both and almost always outperforms either alone.

The standard merging algorithm is **Reciprocal Rank Fusion (RRF)**:

```
RRF score for document D given N ranked lists:
  score(D) = Σ  1 / (k + rank_i(D))
            i=1..N

where: k = 60 (constant to reduce the impact of high-ranking outliers),
       rank_i(D) = rank of document D in list i (1-indexed)
                   = infinity if D does not appear in list i
```

Example with k=60:
```
               Vector Rank   BM25 Rank   RRF Score
Doc A              1            4         1/61 + 1/64 = 0.0320
Doc B              2            1         1/62 + 1/61 = 0.0326  ← winner
Doc C              3           10         1/63 + 1/70 = 0.0301
Doc D             12            2         1/72 + 1/62 = 0.0300
```

Doc B wins because it ranked well in both lists. Doc A ranked #1 in vector
search but only #4 in BM25, so it scores lower than Doc B which was
consistently strong in both.

The k=60 constant dampens the advantage of rank 1 vs. rank 2. Without it
(k=0), the first-place rank would dominate entirely.

Azure AI Search supports hybrid search natively: pass both `search` (text)
and `vectorQueries` in the same request, and the service applies RRF internally.

---

### 6. Reranking

First-stage retrieval (BM25 or vector search) is fast but approximate. A
reranker takes the top-K first-stage results and re-scores them with a more
expensive but more accurate model.

```
Query + top-20 retrieved chunks
         │
         ▼
  Cross-encoder reranker
  (reads query + chunk together, outputs relevance score)
         │
         ▼
  Re-sorted top-5 ─────────────────► LLM context
```

A **bi-encoder** (standard embedding model) embeds query and document
separately and computes similarity. It's fast because document embeddings
can be precomputed.

A **cross-encoder** reads the query and document together in one pass,
allowing full attention between them. It produces higher-quality relevance
scores but is much slower — you can't precompute anything.

Typical pipeline: bi-encoder retrieves top-20, cross-encoder reranks to top-5.
This gives you the speed of approximate retrieval with near-exact reranking
quality.

Azure AI Search has a built-in semantic reranker (the "semantic" configuration)
that applies a cross-encoder-style model trained on retrieval tasks.

---

### 7. RAGAS Evaluation Metrics

How do you measure whether your RAG system is good? RAGAS (RAG Assessment)
defines four metrics that together cover the main failure modes:

```
                    ┌─────────────────────────────────────┐
                    │           RAG PIPELINE               │
  Question ─────────┤─► Retrieval ─► Context ─► Answer    │
                    └──────┬──────────────┬────────────────┘
                           │              │
            ┌──────────────┴──────┐  ┌───┴────────────────────┐
            │  Context metrics    │  │   Answer metrics        │
            │                     │  │                         │
            │ Context Precision   │  │ Faithfulness            │
            │ (% of retrieved     │  │ (% of answer claims     │
            │  chunks that are    │  │  supported by context)  │
            │  relevant)          │  │                         │
            │                     │  │ Answer Relevance        │
            │ Context Recall      │  │ (does the answer        │
            │ (% of needed facts  │  │  address the question?) │
            │  that were          │  │                         │
            │  retrieved)         │  └─────────────────────────┘
            └─────────────────────┘
```

#### Faithfulness (0.0 – 1.0)

What fraction of the claims in the generated answer are supported by the
retrieved context? 1.0 = every claim is grounded. 0.0 = fully hallucinated.

Measurement approach:
1. Use an LLM to extract atomic claims from the answer
   ("The rate limit is 200 RPM", "This applies to gpt-4o-mini")
2. For each claim, ask an LLM: "Is this claim supported by the context?"
3. Faithfulness = (number of supported claims) / (total claims)

This is the most important metric. A system with faithfulness < 0.7 is
unreliable for production use — users can't trust the answers.

#### Answer Relevance (0.0 – 1.0)

Does the answer actually address the question asked? High faithfulness but
low answer relevance means the model answered accurately but answered a
different question than was asked.

Measurement approach:
1. Use an LLM to generate N paraphrase questions that the given answer
   would answer (reverse-engineer the question from the answer)
2. Embed the original question and each paraphrase question
3. Compute cosine similarity between original and each paraphrase
4. Answer relevance = mean cosine similarity

If the answer is on-topic, the reverse-engineered questions will be
semantically similar to the original. If the answer is off-topic, they won't.

#### Context Precision (0.0 – 1.0)

Of all the chunks you retrieved, what fraction were actually relevant to
answering the question? Low precision = you're retrieving a lot of noise
and stuffing the model's context with irrelevant content.

Requires ground-truth labels (which chunks should have been retrieved) and
is typically evaluated on a curated test set.

#### Context Recall (0.0 – 1.0)

Of all the chunks needed to answer the question correctly, what fraction
did you actually retrieve? Low recall = you're missing key facts, and the
model may hallucinate to fill the gaps.

Also requires ground-truth labels.

#### Practical Evaluation Strategy

For production systems, faithfulness and answer relevance can be computed
automatically without ground-truth labels. Context precision and recall
require a labeled evaluation set (expensive to build but worth it for
high-stakes applications).

Start with automated faithfulness and answer relevance on 50-100 representative
questions. If faithfulness < 0.8, debug retrieval. If answer relevance < 0.7,
debug the RAG prompt.

---

### 8. RAG Failure Modes

#### Context Stuffing

Injecting too many retrieved chunks overwhelms the model. "Lost in the middle"
is a documented phenomenon: LLMs pay more attention to the beginning and end
of long contexts and tend to ignore content in the middle.

Mitigation: keep the total retrieved context under 2000 tokens. Use reranking
to ensure the top-3 chunks are genuinely the most relevant, not just the most
similar.

#### Retrieval-Answer Mismatch

The retrieved chunks are topically related but don't actually contain the answer.
The model may then hallucinate an answer that sounds like it comes from the context
but doesn't.

Mitigation: add a retrieval quality check before calling the LLM. Ask a smaller
model: "Does this context contain information relevant to answering: <question>?
Answer yes or no." Only proceed if yes.

#### Stale Index

Your knowledge base gets updated but the search index isn't refreshed. The model
answers from outdated content.

Mitigation: implement document versioning in your index (store `updated_at`
metadata), and use date-filtering in retrieval to prefer recent documents.

#### Verbatim Retrieval Trap

The retrieved chunk is retrieved precisely because it contains the exact
words from the query, but the query is asking about a related concept, not
the retrieved fact. The model then gives a technically correct but
contextually wrong answer.

Example: query is "how do I handle Azure rate limit errors?", retrieved chunk
is "Azure rate limits: 200 RPM". The chunk is retrieved correctly, but the
user wanted retry strategies, not the limit number.

Mitigation: hybrid search with semantic component. The semantic component
understands "handle rate limit errors" and "retry strategies" are related.

---

## Lab Tasks

### Setup

```bash
cd modules/module-09-rag/lab
cp .env.example .env
# Edit .env — fill in Azure OpenAI and Azure AI Search credentials
# Azure AI Search can be reused from Module 08 terraform
# Or provision a new index with a different name (AZURE_SEARCH_INDEX=rag-documents)
uv sync
```

### Option B: Google Vertex AI

Use Vertex AI's OpenAI-compatible endpoint instead of Azure OpenAI for the
LLM calls. Azure-specific services (AI Search, embeddings) still require Azure.

1. Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
2. Authenticate:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
3. Enable the Vertex AI API:
   ```bash
   gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
   ```
4. Set `LLM_PROVIDER=vertex` in your `.env` file and fill in `GCP_PROJECT_ID`.

---

### Task A: Chunking Strategies

**Goal:** Implement and compare three chunking approaches on the same document to see how chunk boundaries affect retrieval unit quality.

**What to do:**
1. Open `lab/src/rag_pipeline.py` and locate the three chunking functions (lines ~206-260)
2. Review the implementations: `chunk_fixed()`, `chunk_sentence()`, and `chunk_recursive()` — all three are already implemented
3. Study how `chunk_recursive()` uses the separator hierarchy (`["\n\n", "\n", ". ", " "]`) and recurses when a piece exceeds `max_size`
4. The `task_a()` runner (line ~263) applies all three strategies to the first sample document ("Azure OpenAI Models and Pricing")
5. Run the task:
   ```bash
   cd modules/module-09-rag/lab
   uv run rag --task A
   ```

**Expected result:**
- The source document is ~900 chars, and each strategy produces a different number of chunks:
  ```
  Source document: Azure OpenAI Models and Pricing
  Length: 916 chars

  ┌─ Fixed-Size Chunking (3 chunks) ─────────────────────────────────────┐
  │  #  │ Length │ Preview                                               │
  │  0  │    500 │ Azure OpenAI Service provides access to OpenAI's...   │
  │  1  │    500 │ tokens and multimodal inputs (text and images). G...   │
  │  2  │    366 │ at $0.13 per 1M tokens. Both support shortening...    │
  └──────────────────────────────────────────────────────────────────────┘

  ┌─ Sentence-Aware Chunking (2 chunks) ─────────────────────────────────┐
  │  #  │ Length │ Preview                                               │
  │  0  │    487 │ Azure OpenAI Service provides access to OpenAI's...   │
  │  1  │    429 │ For embeddings, text-embedding-3-small produces...    │
  └──────────────────────────────────────────────────────────────────────┘

  ┌─ Recursive Chunking (3 chunks) ──────────────────────────────────────┐
  │  #  │ Length │ Preview                                               │
  │  0  │    342 │ Azure OpenAI Service provides access to OpenAI's...   │
  │  1  │    289 │ GPT-4o-mini is a cost-optimized variant designed...   │
  │  2  │    285 │ For embeddings, text-embedding-3-small produces...    │
  └──────────────────────────────────────────────────────────────────────┘
  ```
- Fixed-size chunks cut mid-sentence; sentence-aware chunks respect sentence boundaries but produce fewer, larger chunks; recursive chunks respect paragraph boundaries first

**Why this matters:**
Chunk quality is the highest-leverage parameter in a RAG system. A chunk that splits a key sentence in half means neither half is retrievable for the right query. Recursive chunking is the general-purpose default because it preserves natural document structure (paragraphs > lines > sentences) without requiring NLP.

**Run with:** `uv run rag --task A`

---

### Task B: Ingestion Pipeline

**Goal:** Chunk, embed, and upload documents to Azure AI Search to build a searchable knowledge base.

**What to do:**
1. Open `lab/src/rag_pipeline.py` and locate `task_b()` (line ~294) and the helper functions `embed()` (line ~183), `_upsert_to_search()` (line ~329)
2. Review how the pipeline works: `SAMPLE_DOCS` are chunked with `chunk_recursive(max_size=400)`, each chunk gets a `ChunkRecord` with `id`, `doc_id`, and `text`
3. Embeddings are generated in batches of 16 via `embed()`, which calls the Azure OpenAI embeddings endpoint
4. If `AZURE_SEARCH_ENDPOINT` is set, `_upsert_to_search()` creates the index and uploads documents; otherwise it runs in local-only mode (embeddings generated but not uploaded)
5. Run the task:
   ```bash
   cd modules/module-09-rag/lab
   uv run rag --task B
   ```

**Expected result:**
- The four `SAMPLE_DOCS` are chunked into ~12-16 chunks total:
  ```
  Total chunks to embed: 14
    Embedded batch 1: 14 chunks, dim=1536
  ```
- If Azure AI Search is configured:
  ```
    Index 'rag-documents' created/updated.
    Uploaded 14 documents to index.
  ```
- If not configured, a message indicating local-only mode with embeddings still generated
- Final confirmation: `Embedded 14 chunks successfully.`

**Why this matters:**
The ingestion pipeline is the offline half of RAG. Batch embedding (16 texts per call) reduces API round-trips by 16x compared to single-text calls. The `mergeOrUpload` action in the upsert ensures re-running ingestion updates existing chunks rather than creating duplicates — essential for incremental index updates in production.

**Run with:** `uv run rag --task B`

---

### Task C: Retrieval — Three Modes

**Goal:** Implement and compare vector search, keyword search, and hybrid search to see how each handles different query types.

**What to do:**
1. Open `lab/src/rag_pipeline.py` and locate `task_c()` (line ~378) and the `_search()` helper (line ~428)
2. Review how `_search()` builds the request body differently per mode:
   - `keyword`: sets `body["search"]` with `queryType: "simple"` (BM25 only)
   - `vector`: embeds the query and sets `body["vectorQueries"]` (semantic only)
   - `hybrid`: sets both fields, letting Azure AI Search apply RRF internally
3. Without Azure AI Search configured, the task falls back to local vector search using `cosine_similarity()` over in-memory embeddings
4. Three test queries are pre-configured: rate limits, hybrid search mechanics, and CRAG
5. Run the task:
   ```bash
   cd modules/module-09-rag/lab
   uv run rag --task C
   ```

**Expected result:**
- For each query, three tables showing top-3 results per retrieval mode:
  ```
  Query: What are the rate limits for GPT-4o-mini?

  ┌─ KEYWORD results ────────────────────────────────────────────────────┐
  │ Score  │ ID                       │ Text                            │
  │ 8.2140 │ azure-openai-rate-lim-0  │ Azure OpenAI enforces rate...   │
  │ 3.1205 │ azure-openai-models-1    │ GPT-4o-mini is a cost-opti...   │
  └────────────────────────────────────────────────────────────────────────┘

  ┌─ VECTOR results ─────────────────────────────────────────────────────┐
  │ Score  │ ID                       │ Text                            │
  │ 0.8734 │ azure-openai-rate-lim-1  │ Default rate limits for st...   │
  │ 0.8291 │ azure-openai-rate-lim-0  │ Azure OpenAI enforces rate...   │
  └────────────────────────────────────────────────────────────────────────┘
  ```
- In local-only mode (no Azure AI Search), only vector search results are shown
- The query "What is CRAG and how does it improve RAG?" demonstrates where vector search outperforms keyword search — "CRAG" as an acronym may not match BM25 well, but the embedding captures the semantic relationship to "Corrective RAG"

**Why this matters:**
No single retrieval mode dominates all query types. Keyword search excels at exact term matches (error codes, version numbers); vector search handles paraphrases and conceptual queries. Hybrid search with RRF consistently outperforms either alone, which is why it is the default for production RAG systems.

**Run with:** `uv run rag --task C`

---

### Task D: Generation — the RAG Prompt

**Goal:** Construct a well-formed RAG prompt with retrieved context and generate a grounded, cited answer.

**What to do:**
1. Open `lab/src/rag_pipeline.py` and locate `task_d()` (line ~454)
2. Review the RAG prompt construction (lines ~488-501): retrieved chunks are formatted as `[Source 1]`, `[Source 2]`, etc., and the system prompt instructs the model to answer ONLY from context and cite sources
3. The pipeline is: retrieve top-3 chunks (hybrid or local vector) -> build context block -> call LLM -> display answer in a Rich panel
4. Three test questions are pre-configured: cost comparison, HNSW configuration, and advanced RAG patterns
5. Run the task:
   ```bash
   cd modules/module-09-rag/lab
   uv run rag --task D
   ```

**Expected result:**
- For each question, a green-bordered panel with a grounded answer citing sources:
  ```
  Question: What is the cost difference between GPT-4o and GPT-4o-mini?

  ┌─ Answer ─────────────────────────────────────────────────────────────┐
  │ GPT-4o-mini costs approximately $0.15 per 1M input tokens and       │
  │ $0.60 per 1M output tokens, making it 10-20x cheaper than GPT-4o   │
  │ [Source 1]. For provisioned throughput, one PTU provides ~6 RPM     │
  │ for GPT-4o versus ~25 RPM for GPT-4o-mini [Source 2].              │
  └──────────────────────────────────────────────────────────────────────┘
  Sources used: 3 chunks
  ```
- Answers should reference `[Source N]` citations that map back to retrieved chunks
- If you add a question outside the knowledge base (e.g., "What is Kubernetes?"), the model should respond with "I don't have enough information in the provided context to answer this question."

**Why this matters:**
The RAG prompt is where retrieval quality meets generation quality. The system instruction to cite sources and refuse unanswerable questions is the primary defense against hallucination. Without it, the model will confidently fabricate answers that look grounded but are not. The `[Source N]` citation pattern also makes answers auditable — you can trace every claim back to a retrieved chunk.

**Run with:** `uv run rag --task D`

---

### Task E: Evaluation (RAGAS-Style)

**Goal:** Implement RAGAS-style faithfulness and answer relevance scoring to measure RAG output quality.

**What to do:**
1. Open `lab/src/rag_pipeline.py` and locate `task_e()` (line ~513)
2. Review the three evaluation cases (lines ~517-533): each has a `question`, `expected` answer, and `context` drawn from `SAMPLE_DOCS`
3. Faithfulness scoring (lines ~547-563): the LLM extracts claims from the answer and checks each against the context, outputting JSON with `{"claims": [{"claim": "...", "supported": true/false}]}`
4. Answer relevancy (line ~566): computed as cosine similarity between the question embedding and the answer embedding
5. Context precision (line ~570): computed as cosine similarity between the question embedding and the context embedding
6. Run the task:
   ```bash
   cd modules/module-09-rag/lab
   uv run rag --task E
   ```

**Expected result:**
- Three evaluation cases with metrics tables:
  ```
  Q: What is the cost of GPT-4o-mini per million input tokens?
  A: GPT-4o-mini costs approximately $0.15 per 1M input tokens.

  ┌─ Metrics ─────────────────────────────────────────────────────────────┐
  │ Metric              │ Score  │ Detail                               │
  ├─────────────────────┼────────┼──────────────────────────────────────┤
  │ Faithfulness        │ 1.00   │ 2/2 claims supported                 │
  │ Answer Relevancy    │ 0.9312 │ cosine(question, answer)             │
  │ Context Precision   │ 0.8847 │ cosine(question, context)            │
  └──────────────────────────────────────────────────────────────────────┘
  ```
- Well-grounded questions (cost, HNSW algorithm) should score faithfulness near 1.0
- Answer relevancy scores above 0.85 indicate the answer addresses the question asked
- If faithfulness parsing fails (malformed JSON from the LLM), the score shows "error"

**Why this matters:**
Faithfulness is the most critical RAG metric — a system scoring below 0.7 is hallucinating too often for production use. Answer relevancy catches a subtler failure: the model answers accurately from context but answers a different question than was asked. These two metrics can be computed automatically without ground-truth labels, making them viable for continuous production monitoring.

**Run with:** `uv run rag --task E`

---

## Conceptual Checkpoints

Answer these before moving to Module 10:

1. **Chunking choice**: You're building a RAG system over a 500-page legal
   contract (dense prose with few paragraph breaks). Which chunking strategy
   would you choose and why? What chunk size would you start with? How would
   you measure whether your chunking is good or bad?

2. **Hybrid search**: For a developer documentation search system, describe
   two specific queries where BM25-only retrieval would fail but vector search
   would succeed, and two queries where the opposite is true. What does this
   tell you about when to invest in hybrid search vs. sticking with one approach?

3. **Faithfulness vs. answer relevance**: Your evaluation shows faithfulness=0.95
   but answer_relevance=0.42. What does this combination tell you about what
   is going wrong in the RAG pipeline? What would you investigate first?

4. **Context window budget**: You have a 4096-token context budget for RAG.
   Your system prompt uses 400 tokens, the conversation history uses 800 tokens,
   and the answer generation typically uses 600 tokens. How many 300-token chunks
   can you inject? What is the tradeoff between injecting more chunks and keeping
   conversation history?

5. **Evaluation without ground truth**: You need to continuously monitor your
   RAG system in production. You don't have labeled ground-truth retrieval sets.
   Which RAGAS metrics can you compute automatically without labels? Design a
   monitoring system using those metrics — what threshold would trigger an alert?

---

## Resources

- "RAGAS: Automated Evaluation of Retrieval Augmented Generation":
  https://arxiv.org/abs/2309.15217
- Azure AI Search hybrid search documentation:
  https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview
- "Lost in the Middle: How Language Models Use Long Contexts":
  https://arxiv.org/abs/2307.03172
- Reciprocal Rank Fusion paper (Cormack, Clarke, Buettcher 2009):
  https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- Azure OpenAI embeddings API reference:
  https://learn.microsoft.com/en-us/azure/ai-services/openai/reference#embeddings
- "Chunking Strategies for LLM Applications" (Pinecone blog):
  https://www.pinecone.io/learn/chunking-strategies/
