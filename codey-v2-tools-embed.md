# Codey-v2 Tools Embedding Pipeline — Design Plan

## 1. Overview

This document describes the architecture for a **dataset ingestion, normalization, and embedding pipeline** that:

1. Loads open-source code + instruction datasets (HuggingFace Hub)
2. Converts raw examples into Codey-v2 tool-call format
3. Generates text embeddings for semantic retrieval
4. Stores examples in a vector store (FAISS + SQLite metadata)
5. Outputs dual-purpose artifacts: training-ready JSONL + retrieval-ready index

The pipeline is designed to run on-device (Termux/Android) with lightweight models, or off-device for large dataset processing. It reuses Codey-v2's existing embedding infrastructure (nomic-embed-text on port 8082) wherever possible.

---

## 2. Codey-v2 Tool System — Key Findings

### 2.1 Tool Call Format (from `core/agent.py` + `prompts/system_prompt.py`)

The model generates tool calls wrapped in `<tool>` XML tags containing a JSON object:

```
<tool>
{"name": "TOOL_NAME", "args": {"ARG": "VALUE"}}
</tool>
```

### 2.2 Available Tools (canonical set)

| Tool Name      | Required Args                          | Description                  |
|----------------|----------------------------------------|------------------------------|
| `shell`        | `command`                              | Run a shell/termux command   |
| `write_file`   | `path`, `content`                      | Create or overwrite a file   |
| `patch_file`   | `path`, `old_str`, `new_str`           | Edit existing file           |
| `read_file`    | `path`                                 | Read file content            |
| `append_file`  | `path`, `content`                      | Append to file               |
| `list_dir`     | `path` (optional, default `.`)         | List directory               |
| `search_files` | `pattern`, `path` (optional)           | Find files by name pattern   |
| `note_save`    | `key`, `value`                         | Persist a named fact         |
| `note_forget`  | `key`                                  | Remove a stored note         |

### 2.3 Training Format (from `core/finetune_prep.py`)

Fine-tuning data uses ShareGPT-style JSONL where the assistant turn contains a raw `<tool>` block:

```json
{
  "conversations": [
    {"role": "system",    "content": "<system prompt>"},
    {"role": "user",      "content": "install python in termux"},
    {"role": "assistant", "content": "<tool>\n{\"name\": \"shell\", \"args\": {\"command\": \"pkg install python\"}}\n</tool>"}
  ],
  "metadata": {
    "source": "dataset_name",
    "tool": "shell",
    "quality": 0.9
  }
}
```

### 2.4 Internal Retrieval Record Format

For the embedding/RAG store, each record is a flat dict:

```json
{
  "user": "install python in termux",
  "tool_calls": [
    {
      "name": "shell",
      "args": { "command": "pkg install python" }
    }
  ],
  "metadata": {
    "source": "dataset_name",
    "split": "train",
    "quality": 0.9,
    "tags": ["termux", "python", "install"]
  }
}
```

> **Note on naming:** The example in the task description uses `"arguments"` and `"run_termux_command"`. The canonical Codey-v2 format uses `"args"` and `"shell"`. This pipeline normalizes everything to the canonical format.

---

## 3. Data Pipeline Stages

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PIPELINE OVERVIEW                                │
│                                                                         │
│  [HF Dataset]  →  [Ingestor]  →  [Normalizer]  →  [Transformer]       │
│                                                                         │
│  [Transformer]  →  [Embedder]  →  [FAISS + SQLite]  →  [Exporter]     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Stage 1 — Dataset Ingestion (`ingestion/`)

**Purpose:** Load raw datasets from HuggingFace Hub or local files.

**Responsibilities:**
- Stream or batch-load datasets using `datasets` library
- Support multiple dataset formats (instruction-tuning, code QA, shell commands)
- Apply row-level deduplication (SHA-256 hash of normalized input text)
- Cache locally in `~/.codey-v2/pipeline_cache/` to avoid re-downloading

**Input sources (initial targets):**

| Dataset | HF Path | Why |
|---------|---------|-----|
| CodeSearchNet (Python) | `code_search_net` | Code + docstring pairs |
| The Stack Smol | `bigcode/the-stack-smol` | Code-only, many languages |
| glaiveai/glaive-function-calling-v2 | `glaiveai/glaive-function-calling-v2` | Instruction → function call pairs |
| Alpaca (code subset) | `tatsu-lab/alpaca` | Instruction → code pairs |
| Shell Command Corpus | custom / scraped | Shell instruction → command |
| Termux-specific commands | custom JSONL | High-value Termux actions |

**Output:** Raw Python dicts, one per example.

---

### Stage 2 — Normalization (`normalization/`)

**Purpose:** Bring raw examples from different schemas into a single intermediate format.

**Intermediate format:**

```json
{
  "instruction": "install python in termux",
  "response_type": "shell_command",
  "raw_response": "pkg install python",
  "language": null,
  "source_dataset": "termux_commands",
  "source_id": "abc123"
}
```

**Normalizer responsibilities:**
- Detect response type: `shell_command`, `file_write`, `file_patch`, `code_generation`, `multi_step`
- Extract instruction text (clean markdown, strip URLs, normalize whitespace)
- Detect programming language from code blocks or metadata
- Score quality (0.0–1.0) using heuristics (see §8)

---

### Stage 3 — Tool Call Transformation (`transformation/`)

**Purpose:** Map normalized examples to one or more Codey-v2 tool calls.

**Output:**

```json
{
  "user": "install python in termux",
  "tool_calls": [
    { "name": "shell", "args": { "command": "pkg install python" } }
  ],
  "metadata": { ... }
}
```

See §5 (Mapping Logic) for the transformation rules.

---

### Stage 4 — Embedding Generation (`embedding/`)

**Purpose:** Embed the `"user"` field (and optionally tool call text) for semantic retrieval.

See §6 (Embedding Strategy) for details.

---

### Stage 5 — Storage (`storage/`)

**Purpose:** Persist embeddings + metadata for retrieval at inference time.

- **FAISS index** — flat L2 or cosine similarity index for fast ANN search
- **SQLite metadata DB** — stores full record (user, tool_calls, metadata) keyed by FAISS vector ID

---

### Stage 6 — Export (`export/`)

**Purpose:** Write two output artifacts:

1. **`training_data.jsonl`** — ShareGPT-format, ready for Unsloth fine-tuning
2. **`retrieval_index/`** — FAISS index + SQLite DB, ready for RAG injection

---

## 4. Mapping Logic — Raw Dataset → Tool Calls

### 4.1 Classification Rules

Each normalized example is classified by `response_type`. The classifier applies these rules in order:

| Condition | `response_type` | Primary Tool |
|-----------|----------------|--------------|
| Response is a single shell command | `shell_command` | `shell` |
| Response creates a new file | `file_write` | `write_file` |
| Response modifies an existing file | `file_patch` | `patch_file` |
| Response is pure Python/JS/etc code | `code_generation` | `write_file` |
| Response has multiple numbered steps | `multi_step` | sequence of tools |
| Response reads/inspects a file | `file_read` | `read_file` |
| Fallback | `shell_command` | `shell` |

### 4.2 Transformation Rules by Type

#### `shell_command`
```python
# Raw: "pkg install python"
# Maps to:
{"name": "shell", "args": {"command": "pkg install python"}}
```

#### `file_write` (new file)
```python
# Raw: instruction asks to create hello.py with print("hello")
# Maps to:
{"name": "write_file", "args": {"path": "hello.py", "content": "print('hello')\n"}}
```

#### `file_patch` (edit existing)
```python
# Raw: instruction says to change line X to Y in file.py
# Maps to:
{"name": "patch_file", "args": {"path": "file.py", "old_str": "<old>", "new_str": "<new>"}}
```

#### `code_generation` (code block in response)
```python
# Raw: "write a function that adds two numbers"
# Maps to:
{"name": "write_file", "args": {"path": "solution.py", "content": "def add(a, b):\n    return a + b\n"}}
```

#### `multi_step` (numbered steps)
```python
# Raw: "create a flask app and run it"
# Maps to a sequence:
[
  {"name": "write_file", "args": {"path": "app.py", "content": "..."}},
  {"name": "shell",      "args": {"command": "python app.py"}}
]
```

### 4.3 Path Inference for Code Files

When a file path is not explicitly given, infer it from:
1. A filename mentioned in the instruction (`"create main.py"` → `main.py`)
2. Language extension (`python` → `.py`, `javascript` → `.js`, etc.)
3. Fallback: `solution.<ext>` based on detected language, or `output.txt`

### 4.4 Termux-Specific Command Normalization

Shell commands from generic Linux datasets need Termux adaptation:

| Generic (Linux) | Termux equivalent |
|-----------------|-------------------|
| `apt install X` | `pkg install X` |
| `sudo apt ...`  | `pkg ...` (no sudo) |
| `python3 X`     | `python X` (Termux symlink) |
| `pip3 install X`| `pip install X` |
| `/usr/bin/X`    | `X` (PATH already set) |

A `TermuxNormalizer` post-processor applies these substitutions after classification.

---

## 5. Tool Schema Alignment

All output tool calls must conform to this schema:

```python
{
  "name": str,           # One of the 9 canonical tool names
  "args": {              # Flat dict of string values only
    str: str             # All values coerced to str
  }
}
```

**Validation checks:**
- `name` must be in `VALID_TOOLS` set
- `args` must contain all required keys for that tool (see §2.2 table)
- `args` values must be non-empty strings
- `content` fields must not be `"..."` or placeholder text
- `command` must not contain shell metacharacters: `;`, `&&`, `||`, `` ` ``, `$(`, `\n`, `\r`

Invalid examples are logged to `pipeline_errors.jsonl` and skipped.

---

## 6. Embedding Strategy

### 6.1 What Text Is Embedded

The **primary embedding text** is constructed by concatenating:

```
"{user_instruction} → {tool_name} {key_arg_value}"
```

Examples:
- `"install python in termux → shell pkg install python"`
- `"create hello.py → write_file hello.py"`
- `"list files in current directory → list_dir ."`

This gives the embedding both the intent AND the resolution, making similarity search more precise.

**Secondary embeddings** (optional, for larger indexes):
- Embed `user_instruction` alone → for instruction similarity
- Embed tool call JSON as string → for action similarity

### 6.2 Chunking Strategy

Each tool-call record is treated as a **single unit** — no sub-chunking.

For `multi_step` records with many tool calls, embed each step separately AND embed the combined instruction as a "multi-step" record. This allows retrieval at both granularities.

### 6.3 Embedding Model Options

| Model | Dim | Size | Source |
|-------|-----|------|--------|
| `nomic-embed-text-v1.5` | 768 | ~270MB | Already running on port 8082 |
| `all-MiniLM-L6-v2` | 384 | ~80MB | sentence-transformers (already in `core/embeddings.py`) |
| `BAAI/bge-small-en-v1.5` | 384 | ~133MB | Fast, high quality |

**Recommendation:** Use **nomic-embed-text** via port 8082 for consistency with Codey-v2's existing RAG pipeline. Fall back to `all-MiniLM-L6-v2` if the embed server is offline.

### 6.4 Metadata to Store Alongside Each Vector

```json
{
  "id": "sha256_first16",
  "user": "install python in termux",
  "tool_calls": [...],
  "source_dataset": "termux_commands",
  "source_split": "train",
  "quality": 0.92,
  "tool_names": ["shell"],
  "language": null,
  "tags": ["termux", "package-manager", "python"],
  "created_at": 1743123456
}
```

---

## 7. Suggested Python Libraries

| Library | Purpose | Install |
|---------|---------|---------|
| `datasets` | Load HuggingFace datasets | `pip install datasets` |
| `sentence-transformers` | Local embedding generation | `pip install sentence-transformers` |
| `faiss-cpu` | Vector index (ANN search) | `pip install faiss-cpu` |
| `numpy` | Vector math | `pip install numpy` |
| `tqdm` | Progress bars | `pip install tqdm` |
| `httpx` | Call local embed server (port 8082) | `pip install httpx` |
| `pydantic` | Schema validation | `pip install pydantic` |
| `jsonlines` | JSONL I/O | `pip install jsonlines` |

> **Note:** `faiss-cpu` may need special build on Android/Termux. Fallback: use `hnswlib` (`pip install hnswlib`) or pure-Python similarity search for small indexes.

---

## 8. Quality Scoring Heuristics

Each example is assigned a quality score 0.0–1.0:

| Signal | Score delta |
|--------|------------|
| Instruction is ≥ 5 words | +0.2 |
| Tool args are non-trivial (content > 20 chars) | +0.2 |
| Command passes Codey-v2 metacharacter validation | +0.1 |
| Source dataset is curated (glaive, alpaca) | +0.2 |
| Source dataset is raw scrape | −0.1 |
| Multi-step example (≥ 2 tool calls) | +0.1 |
| Contains placeholder text (`...`, `TODO`, `<insert>`) | −0.5 |
| Instruction is < 3 words | −0.3 |
| Duplicate (by instruction hash) | discard |

Minimum threshold to include in output: **0.5**

---

## 9. Example Transformations

### Raw → Structured

**Input (CodeSearchNet docstring):**
```python
# function: install_pkg
# docstring: "Install a package using pkg manager in Termux"
# code: subprocess.run(["pkg", "install", package_name])
```

**Normalized intermediate:**
```json
{
  "instruction": "install a package using pkg manager in termux",
  "response_type": "shell_command",
  "raw_response": "pkg install <package_name>",
  "source_dataset": "code_search_net"
}
```

**Final tool-call record:**
```json
{
  "user": "install a package using pkg manager in termux",
  "tool_calls": [
    { "name": "shell", "args": { "command": "pkg install python" } }
  ],
  "metadata": { "source": "code_search_net", "quality": 0.75 }
}
```

---

**Input (Alpaca instruction):**
```json
{
  "instruction": "Write a Python function that reverses a string",
  "input": "",
  "output": "def reverse_string(s):\n    return s[::-1]"
}
```

**Final tool-call record:**
```json
{
  "user": "write a python function that reverses a string",
  "tool_calls": [
    {
      "name": "write_file",
      "args": {
        "path": "solution.py",
        "content": "def reverse_string(s):\n    return s[::-1]\n"
      }
    }
  ],
  "metadata": { "source": "alpaca", "quality": 0.85, "language": "python" }
}
```

---

**Input (multi-step instruction):**
```
Create a Flask app that says hello, then run it on port 9000.
```

**Final tool-call record:**
```json
{
  "user": "create a flask app that says hello and run it on port 9000",
  "tool_calls": [
    {
      "name": "write_file",
      "args": {
        "path": "app.py",
        "content": "from flask import Flask\napp = Flask(__name__)\n\n@app.route('/')\ndef hello():\n    return 'Hello!'\n\nif __name__ == '__main__':\n    app.run(port=9000)\n"
      }
    },
    {
      "name": "shell",
      "args": { "command": "python app.py" }
    }
  ],
  "metadata": { "source": "alpaca", "quality": 0.80, "is_multi_step": true }
}
```

---

## 10. Execution Workflow (End-to-End)

```
python pipeline/run.py \
  --datasets termux_commands alpaca \
  --embed-model nomic \
  --output-dir ./pipeline_output \
  --min-quality 0.5
```

**Step-by-step execution:**

```
1. IngestionManager
   └─ Load each dataset (streaming mode for large sets)
   └─ Deduplicate by instruction hash

2. NormalizationPipeline
   └─ Classify response_type
   └─ Extract and clean instruction text
   └─ Score quality

3. TransformationEngine
   └─ Apply mapping rules per response_type
   └─ Run TermuxNormalizer
   └─ Validate tool schema

4. EmbeddingPipeline
   └─ Build embed_text per record
   └─ Batch embed (64 at a time) via nomic/sentence-transformers
   └─ Normalize vectors (L2)

5. StorageBackend
   └─ Upsert to FAISS index
   └─ Upsert metadata to SQLite

6. ExportPipeline
   └─ Write training_data.jsonl (ShareGPT format)
   └─ Save faiss.index + metadata.db
   └─ Write pipeline_stats.json (counts, quality histogram)
```

**Output directory structure:**

```
pipeline_output/
├── training_data.jsonl          # ShareGPT JSONL for fine-tuning
├── retrieval/
│   ├── faiss.index              # FAISS vector index
│   └── metadata.db              # SQLite metadata
├── pipeline_errors.jsonl        # Skipped records + reasons
└── pipeline_stats.json          # Run summary
```

---

## 11. Module Structure

```
pipeline/
├── __init__.py
├── run.py                   # CLI entry point
├── ingestion/
│   ├── __init__.py
│   ├── base.py              # BaseIngestor ABC
│   ├── hf_ingestor.py       # HuggingFace datasets loader
│   └── jsonl_ingestor.py    # Local JSONL files
├── normalization/
│   ├── __init__.py
│   ├── normalizer.py        # Main NormalizationPipeline
│   ├── classifier.py        # response_type classifier
│   └── quality.py           # Quality scorer
├── transformation/
│   ├── __init__.py
│   ├── transformer.py       # TransformationEngine
│   ├── rules.py             # Per-type mapping rules
│   ├── termux.py            # TermuxNormalizer
│   └── validator.py         # Schema validation
├── embedding/
│   ├── __init__.py
│   ├── embedder.py          # EmbeddingPipeline
│   ├── nomic_client.py      # nomic-embed-text via HTTP (port 8082)
│   └── sentence_client.py   # sentence-transformers fallback
├── storage/
│   ├── __init__.py
│   ├── faiss_store.py       # FAISS index wrapper
│   └── sqlite_store.py      # SQLite metadata store
└── export/
    ├── __init__.py
    └── exporter.py          # training_data.jsonl + stats
```

---

## 12. Edge Cases and Handling

| Edge Case | Handling |
|-----------|---------|
| Multi-language dataset (non-English) | Detect with `langdetect`; skip non-English unless `--include-all-langs` |
| Shell commands with injection characters (`;`, `\|`, etc.) | Flag as invalid, log to errors.jsonl, skip |
| Code response with no clear file path | Infer from language extension; fallback to `solution.py` |
| Very long file content (>50K chars) | Truncate at 50K with a `# [truncated]` marker; flag in metadata |
| Duplicate instructions | Deduplicate by normalized instruction hash; keep highest quality |
| Generic Linux commands needing Termux adaptation | Apply TermuxNormalizer post-processing |
| Multi-step with ambiguous step boundaries | Use numbered list parser; fallback to single `shell` call |
| nomic embed server offline | Automatically fall back to `sentence-transformers` local model |
| FAISS not installable on ARM/Termux | Fall back to `hnswlib` or in-memory cosine similarity with numpy |
| Empty or trivial instruction (`"help"`, `"ok"`) | Quality score < threshold → skip |
| Placeholder text in code (`...`, `pass`, `TODO`) | Quality penalty −0.5; typically filtered out |
| Dataset with no clear instruction/response split | Log warning; attempt heuristic extraction or skip |

---

## 13. Integration with Codey-v2

Once the pipeline runs, the outputs plug directly into the existing Codey-v2 systems:

1. **Fine-tuning:** `training_data.jsonl` is ShareGPT format, compatible with `core/finetune_prep.py` and the Unsloth Colab workflow.

2. **RAG retrieval:** Copy `retrieval/faiss.index` + `retrieval/metadata.db` to `~/.codey-v2/kb/`. The existing `core/retrieval.py` will pick them up for semantic search on the next query.

3. **Direct querying:** The `storage/faiss_store.py` module exposes a `search(query_text, top_k=5)` method that can be called from `core/agent.py` or a new `/kb-tools` command in `main.py`.

---

*Plan version: 1.0 — 2026-03-28. Awaiting approval before implementation begins.*
