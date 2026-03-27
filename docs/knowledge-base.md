# Knowledge Base

The knowledge base (KB) is an optional but recommended local document store that Codey searches during every inference call. Relevant chunks are injected into the prompt automatically — no manual retrieval step needed.

## How It Works

- Documents are split into ~512-word chunks with overlap.
- Each chunk is indexed using BM25 keyword search (always active, zero dependencies).
- Optionally, 768-dim vector embeddings are computed by `nomic-embed-text-v1.5` on port 8082 for semantic search.
- At inference time, a hybrid BM25 + cosine similarity search (RRF merging) retrieves the top 4 most relevant chunks and injects up to ~600 tokens of context into the prompt.

If the KB is empty, there is no overhead — retrieval is silently skipped.

---

## Quick Setup — 5 Curated Repositories

```bash
cd ~/codey-v2
mkdir -p knowledge && cd knowledge

git clone --depth 1 https://github.com/swaroopch/byte-of-python
git clone --depth 1 https://github.com/Aahil13/The-JS-Guide
git clone --depth 1 https://github.com/luckrnx09/python-guide-for-javascript-engineers
git clone --depth 1 https://github.com/EbookFoundation/free-programming-books
git clone --depth 1 https://github.com/mdn/content

cd ~/codey-v2
```

Total size: ~266 MB · ~38 markdown files indexed · ~1167 searchable chunks.

---

## Build the Index

```bash
# Run in foreground (30–60 minutes on S24 Ultra)
python3 -c "
from tools.kb_scraper import index_directory
from tools.kb_semantic import build_semantic_index
index_directory('knowledge')
build_semantic_index()
"
```

**Or run in the background:**

```bash
nohup python3 -c "
from tools.kb_scraper import index_directory
from tools.kb_semantic import build_semantic_index
index_directory('knowledge')
build_semantic_index()
" > embed.log 2>&1 &

tail -f embed.log   # watch progress
```

---

## Verify the Index

```bash
python3 -c "from tools.kb_semantic import index_stats; print(index_stats())"
```

Expected output:

```json
{
  "chunk_files": 500,
  "total_chunks": 1167,
  "has_semantic": true,
  "backend": "hybrid (BM25 + embeddings)"
}
```

---

## Add Your Own Documentation

```bash
cp my_api_docs.md ~/codey-v2/knowledge/docs/

python3 -c "
from tools.kb_scraper import index_directory
index_directory('knowledge/docs', 'docs')
"
```

Supports `.md`, `.txt`, `.py`, `.js`, and most text formats.

---

## Skill Repositories

Skill repos contain reusable agent prompt templates. Set them up once:

```bash
bash tools/setup_skills.sh
```

This clones curated skill repos into `knowledge/skills/` and indexes them. During inference, Codey detects if a skill template matches the current task and injects it into the system prompt automatically.

---

## Inspecting Retrieval Results

Use `/rag <prompt>` inside a session to see exactly what the KB would inject for any given prompt, before sending it to the model.

```
You> /rag create a Flask JWT authentication endpoint
```

Output breakdown:

- **Query** — the cleaned terms actually sent to the search backend (filler words like "create", "a", "the" are stripped)
- **Backend** — `semantic` (BM25 + cosine via embedding model) or `keyword` (BM25 only)
- **Score threshold** — the minimum score a chunk must reach to be included (default 0.3 for semantic)
- **All chunks returned** — every result with its score, source file, and a 3-line preview; each marked ✓ kept or ✗ filtered
- **Block injected** — the exact `## Reference Material` text that would be pasted into the system prompt

This is useful for:
- Checking whether your KB has relevant content for a task
- Tuning `semantic_threshold` in `~/.codey-v2/config.json` if too much or too little is being retrieved
- Verifying that newly indexed documents are being found

If the output shows `(nothing injected — all chunks filtered out or KB empty)`, either the KB has no relevant documents or the score threshold is too high for the available content.

---

## Feature Summary

| Feature | Detail |
|---------|--------|
| **Hybrid search** | BM25 + 768-dim cosine similarity merged via RRF |
| **Auto-retrieval** | Top 4 chunks, up to ~600 tokens, injected per inference call |
| **NEED_DOCS trigger** | Model can request a targeted KB lookup mid-critique |
| **Skill repos** | Claude skills, superpowers, and custom templates supported |
| **Embedding coverage** | 92.6% of chunks get vector embeddings; remainder uses BM25 only |
| **Graceful degradation** | Empty KB = zero overhead; BM25 always active without dependencies |

> **Termux note:** `fastembed` and `sentence-transformers` have no ARM64 Android wheels. The embedding server (`nomic-embed-text-v1.5` via llama-server) is the supported semantic backend on Android. BM25 requires no packages and is always active.
