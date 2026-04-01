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

---

## 14. Dataset Strategy and Sources

This section documents every selected dataset, why it was chosen, how each maps to
Codey-v2 tool calls, and how it feeds the embedding pipeline.  All datasets listed
below were verified against the HuggingFace Hub on 2026-03-28.

---

### 14.1 Dataset Selection Matrix

| # | Dataset | HF Path | License | Size | Priority | Tool Coverage |
|---|---------|---------|---------|------|----------|---------------|
| 1 | Glaive Function Calling v2 | `glaiveai/glaive-function-calling-v2` | Apache-2.0 | ~113K | HIGH | `shell`, `write_file` |
| 2 | Hermes Function-Calling v1 | `NousResearch/hermes-function-calling-v1` | Apache-2.0 | ~11K | HIGH | all tools |
| 3 | APIGen / xLAM-60k (mirror) | `lockon/xlam-function-calling-60k` | CC-BY-4.0 | 60K | HIGH | `shell`, `write_file` |
| 4 | argilla/apigen-function-calling | `argilla/apigen-function-calling` | CC-BY-4.0 | ~100K | HIGH | `shell`, `write_file` |
| 5 | Python Code Instructions 18k | `iamtarun/python_code_instructions_18k_alpaca` | (none) | 18K | HIGH | `write_file`, `shell` |
| 6 | Code Instructions 122k | `TokenBender/code_instructions_122k_alpaca_style` | Apache-2.0 | 122K | MEDIUM | `write_file` |
| 7 | Instructional CodeSearchNet (Python) | `Nan-Do/instructional_code-search-net-python` | Apache-2.0 | ~100K | MEDIUM | `write_file`, `read_file` |
| 8 | MBPP | `google-research-datasets/mbpp` | CC-BY-4.0 | ~1K | MEDIUM | `write_file`, `shell` |
| 9 | HumanEval+ | `evalplus/humanevalplus` | Apache-2.0 | 164 | MEDIUM | `write_file`, `shell` |
| 10 | BigCodeBench-Instruct | `bigcode/bigcodebench` | Apache-2.0 | 1140 | MEDIUM | `write_file`, `shell` |
| 11 | HumanEvalPack | `bigcode/humanevalpack` | MIT | ~1K | LOW | `write_file` |
| 12 | Alpaca-Cleaned | `yahma/alpaca-cleaned` | CC-BY-4.0 | ~52K | LOW | `write_file`, `note_save` |
| 13 | OrcaAgentInstruct-1M | `microsoft/orca-agentinstruct-1M-v1` | CDLA-2.0 | ~1M | LOW | multi-tool |
| 14 | Code-Feedback (OpenCodeInterpreter) | `m-a-p/Code-Feedback` | Apache-2.0 | ~68K | MEDIUM | `write_file`, `shell` |
| 15 | BFCL Leaderboard data | `gorilla-llm/Berkeley-Function-Calling-Leaderboard` | Apache-2.0 | ~2.5K | LOW | `shell`, `write_file` |
| 16 | **Synthetic: Termux CLI corpus** | custom-generated | MIT (own) | target 5K | CRITICAL | `shell` |
| 17 | **Synthetic: multi-step coding** | custom-generated | MIT (own) | target 3K | HIGH | all tools |

---

### 14.2 Dataset Details

---

#### Dataset 1 — `glaiveai/glaive-function-calling-v2`
**HF:** https://hf.co/datasets/glaiveai/glaive-function-calling-v2
**License:** Apache-2.0 | **Size:** ~113K | **Downloads:** 70K+

**Why useful for Codey-v2:**
The largest freely available function-calling dataset. Each example contains a
system prompt with JSON tool schemas, multi-turn conversations, and assistant turns
that call functions with structured arguments. Directly analogous to the Codey-v2
`<tool>{"name":..., "args":{...}}</tool>` format. High diversity of tool types and
argument shapes. Actively used for training production-grade tool-calling models.

**Schema:**
```json
{
  "system": "SYSTEM: You are a helpful assistant with access to the following functions...\nFUNCTION: {\"name\": \"get_news\", ...}",
  "chat": "USER: Get me some news about AI\nASSISTANT: <functioncall> {\"name\": \"get_news\", \"arguments\": {\"topic\": \"AI\"}}"
}
```

**Transformation to Codey-v2 format:**
1. Parse the `chat` field to extract the last USER turn as `"user"`.
2. Extract `<functioncall>` JSON — map `"arguments"` → `"args"`.
3. Map function name: generic API names (`get_weather`, `search_web`) → nearest
   Codey-v2 tool.  Direct-execution functions (`run_code`, `execute_command`) →
   `shell`.  File-output functions → `write_file`.
4. Discard examples where the function name has no plausible Codey-v2 equivalent.

**Name mapping table:**
| Glaive function pattern | Codey-v2 tool |
|------------------------|---------------|
| `*execute*`, `*run*`, `*command*` | `shell` |
| `*write*`, `*create_file*`, `*save*` | `write_file` |
| `*read*`, `*open_file*`, `*get_file*` | `read_file` |
| `*search_files*`, `*find_file*` | `search_files` |
| `*remember*`, `*store*`, `*save_note*` | `note_save` |
| Other (API calls, weather, etc.) | skip or `shell curl` fallback |

**Example transformation:**
```
Raw:
  USER: "Run the python script at /tmp/test.py"
  ASSISTANT: <functioncall> {"name": "execute_code", "arguments": {"file": "/tmp/test.py"}}

→ Codey-v2:
  {
    "user": "run the python script at /tmp/test.py",
    "tool_calls": [
      {"name": "shell", "args": {"command": "python /tmp/test.py"}}
    ]
  }
```

**Embedding strategy:**
- Embed: `"{user} → shell {command}"` or `"{user} → write_file {path}"`
- Chunk: one record per example (no sub-chunking)
- Metadata: `source`, `original_function_name`, `quality`, `is_multi_turn`

---

#### Dataset 2 — `NousResearch/hermes-function-calling-v1`
**HF:** https://hf.co/datasets/NousResearch/hermes-function-calling-v1
**License:** Apache-2.0 | **Size:** ~11K | **Downloads:** 43K+

**Why useful for Codey-v2:**
High-quality curated dataset used to train the Hermes 2 Pro series — widely regarded
as best-in-class for structured tool use.  Includes function-calling, JSON-mode, and
agentic multi-step examples.  Smaller but higher signal-to-noise than Glaive.
The JSON schema format closely mirrors Codey-v2's `args` dict structure.

**Schema:**
```json
{
  "conversations": [
    {"role": "system", "content": "You are a function calling AI..."},
    {"role": "user",   "content": "What's the weather in Paris?"},
    {"role": "assistant", "content": "<tool_call>\n{\"name\": \"get_weather\", \"arguments\": {\"location\": \"Paris\"}}\n</tool_call>"}
  ]
}
```

**Transformation:**
1. Extract `user` turn content as `"user"` field.
2. Parse `<tool_call>` JSON block from assistant turn.
3. Rename `"arguments"` → `"args"`.
4. Apply name-mapping table (same as Dataset 1).
5. Multi-turn examples: keep the first tool-calling turn only (or expand to
   individual records if multi-step is desired).

**Embedding strategy:**
- Embed: `"{user_content} → {tool_name} {primary_arg_value}"`
- Metadata: `source: hermes-v1`, `has_json_mode: bool`, `is_agentic: bool`

---

#### Dataset 3 — `lockon/xlam-function-calling-60k` (APIGen mirror)
**HF:** https://hf.co/datasets/lockon/xlam-function-calling-60k
**License:** CC-BY-4.0 | **Size:** 60K | **Downloads:** 5.8K

**Why useful for Codey-v2:**
Produced by Salesforce's APIGen pipeline — each example was verified through three
stages: format checking, live function execution, and semantic verification. This
makes it one of the highest-correctness function-calling datasets available.
The ungated mirror (`lockon/`) avoids the gated access of the official Salesforce
repo.  Strong coverage of chained/sequential tool calls.

**Schema:**
```json
{
  "query": "What is the current time in New York?",
  "tools": "[{\"name\": \"get_time\", \"description\": \"...\", \"parameters\": {...}}]",
  "answers": "[{\"name\": \"get_time\", \"arguments\": {\"location\": \"New York\"}}]"
}
```

**Transformation:**
1. `query` → `"user"` field.
2. Parse `answers` JSON array — each entry becomes one tool call.
3. Rename `"arguments"` → `"args"`.
4. Apply name-mapping table.
5. For chained calls (len(answers) > 1) → produce a `multi_step` record with
   ordered `tool_calls` list.

**Embedding strategy:**
- Embed: `"{query} → {joined tool names and key args}"`
- Metadata: `source: xlam-apigen`, `num_tools: int`, `tool_names: list`

---

#### Dataset 4 — `argilla/apigen-function-calling`
**HF:** https://hf.co/datasets/argilla/apigen-function-calling
**License:** CC-BY-4.0 | **Size:** ~100K | **Downloads:** 1.9K

**Why useful for Codey-v2:**
A merge of Salesforce xLAM-60k and argilla's own Synth-APIGen-v0.1, totalling
100K+ examples. Provides volume redundancy and diversity across API domains.
Ready-to-use parquet format with clean splits.

**Transformation:** Same as Dataset 3 (shares the APIGen schema).

**Embedding strategy:** Same as Dataset 3; deduplicate against Dataset 3 by
instruction hash before inserting to avoid vector duplicates in FAISS.

---

#### Dataset 5 — `iamtarun/python_code_instructions_18k_alpaca`
**HF:** https://hf.co/datasets/iamtarun/python_code_instructions_18k_alpaca
**License:** none stated (upstream sahil2801) | **Size:** 18K | **Downloads:** 116K+

**Why useful for Codey-v2:**
Dense Python-focused instruction dataset. Each example has a natural language
instruction and a complete Python code solution. Directly maps to the most common
Codey-v2 `write_file` pattern: "write a Python function that does X."

**Schema:**
```json
{
  "instruction": "Write a Python function to check if a string is a palindrome",
  "input": "",
  "output": "def is_palindrome(s):\n    return s == s[::-1]",
  "prompt": "Below is an instruction..."
}
```

**Transformation:**
1. `instruction` (lowercased) → `"user"`.
2. `output` → `write_file` content, path inferred from instruction keywords.
3. If `input` is non-empty, prepend to `output` as a comment or context block.
4. Append `shell` run step if instruction says "run", "execute", or "test".

**Example transformation:**
```
Raw:
  instruction: "Write a Python function to check if a string is a palindrome"
  output: "def is_palindrome(s):\n    return s == s[::-1]"

→ Codey-v2:
  {
    "user": "write a python function to check if a string is a palindrome",
    "tool_calls": [
      {
        "name": "write_file",
        "args": {"path": "solution.py", "content": "def is_palindrome(s):\n    return s == s[::-1]\n"}
      }
    ]
  }
```

**Embedding strategy:**
- Embed: `"{instruction} → write_file solution.py"`
- Metadata: `source: python-alpaca-18k`, `language: python`, `has_run_step: bool`

---

#### Dataset 6 — `TokenBender/code_instructions_122k_alpaca_style`
**HF:** https://hf.co/datasets/TokenBender/code_instructions_122k_alpaca_style
**License:** Apache-2.0 | **Size:** 122K | **Downloads:** 37K+

**Why useful for Codey-v2:**
Large multilingual code instruction dataset (~122K examples). Covers Python,
JavaScript, Bash, SQL, and more. The Bash/shell subset is especially valuable for
building `shell` tool call coverage across non-Termux CLI commands (which become
training fodder after TermuxNormalizer post-processing).

**Schema:** Alpaca-style (`instruction`, `input`, `output`).

**Transformation:** Same as Dataset 5. Additional step: detect language from
`output` code block; Bash outputs → `shell` tool call, others → `write_file`.

**Language → tool mapping:**
| Language in output | Tool |
|-------------------|------|
| bash, sh, zsh | `shell` |
| Python, JS, TS, Ruby | `write_file` |
| SQL | `shell` (via sqlite3 CLI) or `write_file` for .sql file |

**Embedding strategy:**
- Embed: `"{instruction} → {tool_name} {primary_arg}"`
- Metadata: `language`, `source: code-instructions-122k`
- Filter to English only via language detection.

---

#### Dataset 7 — `Nan-Do/instructional_code-search-net-python`
**HF:** https://hf.co/datasets/Nan-Do/instructional_code-search-net-python
**License:** Apache-2.0 | **Size:** ~100K | **Downloads:** 5.1K

**Why useful for Codey-v2:**
Built on CodeSearchNet — pairs real GitHub Python functions with natural language
docstrings. Provides two task types: (a) code → description (useful for `read_file`
pattern: "explain what this file does") and (b) description → code (→ `write_file`).
The real-world code quality is higher than synthetic datasets.

**Schema:**
```json
{
  "instruction": "Write a function that [docstring summary]",
  "response": "def func(...):\n    ..."
}
```

**Transformation:**
1. `instruction` → `"user"`.
2. `response` → `write_file` content; path inferred from function name in response
   (`def my_func` → `my_func.py`) or fallback to `solution.py`.

**Embedding strategy:**
- Embed: `"{instruction} → write_file {inferred_path}"`
- Metadata: `source: codesearchnet-python`, `function_name`, `docstring_length`

---

#### Dataset 8 — `google-research-datasets/mbpp`
**HF:** https://hf.co/datasets/google-research-datasets/mbpp
**License:** CC-BY-4.0 | **Size:** ~974 | **Downloads:** 9M+

**Why useful for Codey-v2:**
MBPP (Mostly Basic Python Problems) is a gold-standard benchmark with human-verified
task descriptions, canonical solutions, and 3 test cases per problem. The test cases
enable a two-step `write_file` + `shell` pattern: write the solution, then verify
with tests. This is the most realistic approximation of Codey-v2's actual coding
workflow.

**Schema:**
```json
{
  "task_id": 1,
  "text": "Write a function to find the minimum cost path to reach (m, n) from (0, 0)...",
  "code": "def min_cost(cost, m, n): ...",
  "test_list": ["assert min_cost([[1,2,3]], 2, 2) == 8", ...]
}
```

**Transformation:**
1. `text` → `"user"` (lowercased, strip leading "Write a").
2. `code` → `write_file` content → `solution.py`.
3. Build test file from `test_list` → second `write_file` → `test_solution.py`.
4. Add `shell` call: `python test_solution.py`.
5. This produces a **3-step multi-tool record** — high value for training
   multi-step reasoning.

**Example transformation:**
```
Raw:
  text: "Write a Python function to find the maximum of two numbers."
  code: "def max_of_two(a, b):\n    return a if a > b else b"
  test_list: ["assert max_of_two(3, 4) == 4", "assert max_of_two(10, 2) == 10"]

→ Codey-v2:
  {
    "user": "write a python function to find the maximum of two numbers",
    "tool_calls": [
      {"name": "write_file", "args": {"path": "solution.py", "content": "def max_of_two(a, b):\n    return a if a > b else b\n"}},
      {"name": "write_file", "args": {"path": "test_solution.py", "content": "from solution import max_of_two\nassert max_of_two(3, 4) == 4\nassert max_of_two(10, 2) == 10\nprint('All tests passed')\n"}},
      {"name": "shell",      "args": {"command": "python test_solution.py"}}
    ]
  }
```

**Embedding strategy:**
- Embed: `"{text} → write_file + shell test"` (combined intent string)
- Metadata: `source: mbpp`, `task_id`, `num_tests`, `is_multi_step: true`

---

#### Dataset 9 — `evalplus/humanevalplus`
**HF:** https://hf.co/datasets/evalplus/humanevalplus
**License:** Apache-2.0 | **Size:** 164 | **Downloads:** 497K+

**Why useful for Codey-v2:**
The hardened version of OpenAI HumanEval with 80× more test cases per problem.
Small but authoritative. Each problem includes a function signature + docstring
(clean instruction) and canonical solution. The extra tests make the 3-step
`write_file` → `write_file` → `shell` pattern very reliable for validation.

**Schema:**
```json
{
  "task_id": "HumanEval/0",
  "prompt": "from typing import List\ndef has_close_elements(numbers: List[float], threshold: float) -> bool:\n    \"\"\"...\"\"\"\n",
  "canonical_solution": "    for ...",
  "test": "def check(candidate):\n    assert candidate([1.0, 2.0], 0.5) == False\n    ...",
  "entry_point": "has_close_elements"
}
```

**Transformation:**
1. Extract docstring from `prompt` → `"user"` field.
2. Combine `prompt` + `canonical_solution` → `write_file` content → `solution.py`.
3. Wrap `test` block → `write_file` → `test_solution.py`.
4. Add `shell` → `python -m pytest test_solution.py` (or `python test_solution.py`).

**Embedding strategy:**
- Embed: `"{docstring_first_sentence} → write_file solution.py"`
- Metadata: `source: humanevalplus`, `task_id`, `entry_point`

---

#### Dataset 10 — `bigcode/bigcodebench` (Instruct split)
**HF:** https://hf.co/datasets/bigcode/bigcodebench
**License:** Apache-2.0 | **Size:** 1140 | **Downloads:** 960K+

**Why useful for Codey-v2:**
BigCodeBench-Instruct features natural language (NL-oriented) prompts that require
integrating multiple Python standard-library and third-party packages. Each example
has 5–6 test cases and near-100% test coverage. This is the most realistic dataset
for training Codey-v2 on "write a complete, working Python program" tasks.

**Schema:**
```json
{
  "task_id": "BigCodeBench/0",
  "instruct_prompt": "Develop a function that parses a CSV and returns statistics...",
  "canonical_solution": "import csv\nimport statistics\ndef parse_csv(path):\n    ...",
  "test": "class TestParseCsv(unittest.TestCase):\n    ..."
}
```

**Transformation:** Same 3-step pattern as MBPP (§Dataset 8).

**Embedding strategy:**
- Embed: `"{instruct_prompt} → write_file + shell test"`
- Metadata: `source: bigcodebench`, `task_id`, `uses_stdlib: bool`

---

#### Dataset 11 — `bigcode/humanevalpack`
**HF:** https://hf.co/datasets/bigcode/humanevalpack
**License:** MIT | **Size:** ~984 (6 langs × 164) | **Downloads:** 2.4M+

**Why useful for Codey-v2:**
Multilingual extension of HumanEval covering Python, JS, Java, Go, C++, Rust.
For Codey-v2 the Python split is the highest priority; JS is secondary (Node.js
runs in Termux). Provides 3 task types: synthesis, fixing (patch), and explanation
(read+describe). The **fixing** task maps directly to `patch_file`.

**Transformation:**
- Synthesis task → `write_file` (same as HumanEval+)
- Fixing task: `buggy_solution` + `fix` → `patch_file` record:
  ```json
  {
    "user": "fix the bug in solution.py",
    "tool_calls": [
      {"name": "patch_file", "args": {"path": "solution.py", "old_str": "<buggy>", "new_str": "<fixed>"}}
    ]
  }
  ```
- Explanation task → `read_file` + prose response (skip for tool-call training,
  useful for retrieval index only)

**Embedding strategy:**
- Embed: `"{docstring} → {tool_name} solution.py"`
- Metadata: `source: humanevalpack`, `language`, `task_type: synthesis|fix|explain`

---

#### Dataset 12 — `yahma/alpaca-cleaned`
**HF:** https://hf.co/datasets/yahma/alpaca-cleaned
**License:** CC-BY-4.0 | **Size:** ~52K | **Downloads:** 921K+

**Why useful for Codey-v2:**
The cleaned Alpaca dataset. Not code-specific, but covers a wide range of
general task instructions including note-taking, lookup, and multi-step reasoning.
Valuable for training the non-code tools: `note_save`, `note_forget`, and general
`shell` commands. The cleaned version removes hallucinated web references.

**Transformation:**
- Filter to examples where `output` implies a command or file operation.
- "Remember this", "Don't forget X" → `note_save`
- "Run X", "Execute Y" → `shell`
- Code outputs → `write_file`
- Discard conversational or factual Q&A examples (no tool applies).

**Embedding strategy:**
- Embed: `"{instruction} → {tool_name} {key_arg}"`
- Metadata: `source: alpaca-cleaned`, `category: general|code|shell|note`

---

#### Dataset 13 — `microsoft/orca-agentinstruct-1M-v1`
**HF:** https://hf.co/datasets/microsoft/orca-agentinstruct-1M-v1
**License:** CDLA-Permissive-2.0 | **Size:** ~1M | **Downloads:** 69K+

**Why useful for Codey-v2:**
Microsoft's AgentInstruct dataset covering complex multi-step agentic tasks: text
editing, creative writing, tool use, coding, and web-interaction simulations.
Large scale (1M examples) with high diversity. The coding and tool-use subsets map
directly to Codey-v2. Use this as a **secondary source** — sample strategically by
category rather than loading all 1M records.

**Recommended subsets to sample:**
- `coding` category → `write_file`, `shell`
- `tool_use` category → all tools
- `text_editing` category → `patch_file`, `write_file`

**Transformation:** Parse multi-turn conversations; extract first user instruction
as `"user"`, last assistant action as tool call using the same classification rules.

**Embedding strategy:**
- Sample max 20K examples from high-signal categories.
- Embed: `"{user} → {tool_name} {key_arg}"`
- Metadata: `source: orca-agentinstruct`, `category`

---

#### Dataset 14 — `m-a-p/Code-Feedback`
**HF:** https://hf.co/datasets/m-a-p/Code-Feedback
**License:** Apache-2.0 | **Size:** ~68K | **Downloads:** 29K+

**Why useful for Codey-v2:**
OpenCodeInterpreter dataset. Contains multi-turn coding conversations where the
user provides an instruction, the assistant generates code, executes it, sees the
output, and refines. This execution loop pattern (write → run → see error → patch)
is exactly the Codey-v2 agentic loop: `write_file` → `shell` → `patch_file`.

**Schema:**
```json
{
  "query": "Write a function that counts vowels",
  "answer": "def count_vowels(s):\n    ...",
  "code_feedback": [{"input": "print(count_vowels('hello'))", "output": "2\n"}]
}
```

**Transformation:**
1. `query` → `"user"`.
2. `answer` → `write_file` content.
3. `code_feedback[0].input` → `shell` command.
4. Produces 2-step `write_file` + `shell` record.
5. If multi-turn, extract subsequent fix turns → `patch_file` records.

**Embedding strategy:**
- Embed: `"{query} → write_file + shell execute"`
- Metadata: `source: code-feedback`, `has_execution_loop: bool`, `num_refinements`

---

#### Dataset 15 — `gorilla-llm/Berkeley-Function-Calling-Leaderboard`
**HF:** https://hf.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard
**License:** Apache-2.0 | **Size:** ~2.5K | **Downloads:** 127K+

**Why useful for Codey-v2:**
BFCL is the canonical function-calling benchmark — used to rank LLMs on tool-use
accuracy. Small, but the examples are human-curated and span diverse categories:
simple calls, nested calls, parallel calls, and multi-turn. Use as a **validation
set** to measure pipeline quality rather than as bulk training data.

**Role in pipeline:** BFCL examples → held-out eval set; measure how well the
pipeline normalizes them vs. ground truth. Not included in training JSONL.

---

### 14.3 Synthetic Data Strategy

The biggest gap in available open datasets is **Termux / Android CLI interaction**.
No existing public dataset covers:
- `pkg install` / `pkg upgrade` package management
- Termux-specific paths (`/data/data/com.termux/files/`)
- Termux API commands (`termux-notification`, `termux-clipboard-get`)
- Multi-step Termux dev workflows (install → configure → run)
- Python virtual environment management on Termux
- Git operations in Termux context
- Command execution loops with error recovery

#### 14.3.1 Synthetic Termux CLI Corpus (target: 5K examples)

**Generation method:** Template-based expansion + LLM paraphrasing.

**Template categories:**

| Category | Example instruction | Tool call |
|----------|-------------------|-----------|
| Package install | "install {package} in termux" | `shell: pkg install {package}` |
| Package upgrade | "update all termux packages" | `shell: pkg upgrade` |
| Python packages | "install {pip_pkg} with pip" | `shell: pip install {pip_pkg}` |
| File operations | "create a {ext} file named {name}" | `write_file: {name}.{ext}` |
| Run scripts | "run {script}" | `shell: python {script}` |
| Git operations | "clone {repo}" | `shell: git clone {url}` |
| Check installed | "list installed packages" | `shell: pkg list-installed` |
| Storage access | "list files in home directory" | `list_dir: ~` |
| Termux API | "send a notification saying {msg}" | `shell: termux-notification --content {msg}` |
| Multi-step setup | "set up a python project called {name}" | `shell mkdir` + `write_file` + `shell pip install` |

**Paraphrase generation:** For each template, generate 5–10 natural language
variants using pattern substitution:
- "install X" → "get X", "set up X", "add X", "download X"
- "create" → "make", "write", "generate", "build"

**Total target:** 500 templates × 10 paraphrases = 5000 synthetic examples.

#### 14.3.2 Synthetic Multi-Step Coding Corpus (target: 3K examples)

**Gap:** Most datasets have single-step responses. Codey-v2's orchestrator generates
multi-step plans (write + run + verify), but training data for this pattern is sparse.

**Generation method:** Compose known single-step examples into sequences:

**Pattern library:**
```
Pattern A: write_file → shell run
  "create {name}.py and run it"

Pattern B: write_file → write_file → shell test
  "write {func} with tests and verify it passes"

Pattern C: read_file → patch_file
  "fix the {error} in {file}.py"

Pattern D: shell install → write_file → shell run
  "install {lib} and write a script that uses it"

Pattern E: list_dir → read_file → write_file
  "read {file} and create an updated version"
```

**Total target:** 600 patterns × 5 paraphrases = 3000 synthetic examples.

#### 14.3.3 Synthetic Data Quality Controls

- All synthetic shell commands must pass `validate_command_structure()` from
  `tools/shell_tools.py` (no metacharacters).
- All synthetic `write_file` content must be complete (not stubs or `...`).
- De-duplicate against existing dataset records by instruction hash.
- Manual review sample: spot-check 5% of generated records before inclusion.

---

### 14.4 Dataset Loading Priority and Phasing

#### Phase 1 — Core (implement first, ~200K examples)
1. `glaiveai/glaive-function-calling-v2` — primary function-call training
2. `iamtarun/python_code_instructions_18k_alpaca` — Python write_file patterns
3. `google-research-datasets/mbpp` — write+test+run patterns
4. `evalplus/humanevalplus` — write+test+run patterns
5. Synthetic Termux CLI corpus — critical gap fill

#### Phase 2 — Volume (add after Phase 1 validated, ~300K more)
6. `lockon/xlam-function-calling-60k` — chained calls
7. `TokenBender/code_instructions_122k_alpaca_style` — multilang coverage
8. `m-a-p/Code-Feedback` — execution loop pattern
9. Synthetic multi-step corpus

#### Phase 3 — Refinement (optional, after Phase 2)
10. `NousResearch/hermes-function-calling-v1` — high quality filter
11. `bigcode/bigcodebench` — complex stdlib tasks
12. `argilla/apigen-function-calling` — additional diversity
13. `microsoft/orca-agentinstruct-1M-v1` — sampled 20K from coding/tool subsets
14. `bigcode/humanevalpack` — patch_file pattern (fix tasks)

---

### 14.5 Embedding Field Summary (all datasets)

| Embed text construction | Datasets |
|------------------------|---------|
| `"{user} → shell {command}"` | Glaive, xLAM, APIGen, Alpaca, Termux-synthetic |
| `"{user} → write_file {path}"` | Python-18k, Code-122k, CodeSearchNet, HumanEval+, MBPP |
| `"{user} → write_file + shell test"` | MBPP, HumanEval+, BigCodeBench, Code-Feedback |
| `"{user} → patch_file {path}"` | HumanEvalPack (fix), Alpaca (edit tasks) |
| `"{user} → note_save {key}"` | Alpaca (remember tasks) |

**Chunking:** One record per instruction-response pair.  Multi-step records are
stored as one unit (the full sequence), with `num_steps` in metadata to enable
filtering.

**Metadata schema (all records):**
```json
{
  "id":           "sha256_first16_of_user_text",
  "user":         "lowercased normalized instruction",
  "tool_calls":   [...],
  "source":       "dataset_name",
  "phase":        1,
  "quality":      0.0-1.0,
  "language":     "python|bash|javascript|null",
  "num_steps":    1,
  "tool_names":   ["shell"],
  "has_test":     false,
  "is_synthetic": false,
  "created_at":   1743123456
}
```

---

### 14.6 License Compliance Summary

| License | Datasets | Commercial use? | Restrictions |
|---------|---------|-----------------|-------------|
| Apache-2.0 | Glaive-v2, Hermes-v1, Python-18k, Code-122k, CodeSearchNet-Python, BigCodeBench, HumanEvalPack, BFCL | Yes | Attribution |
| CC-BY-4.0 | MBPP, xLAM-60k, APIGen-100k | Yes | Attribution |
| MIT | HumanEvalPack, synthetic (own) | Yes | None |
| CC-BY-NC-4.0 | tatsu-lab/alpaca | No (non-commercial) | Non-commercial only |
| CC-BY-4.0 | yahma/alpaca-cleaned | Yes | Attribution |
| CDLA-2.0 | OrcaAgentInstruct | Yes | Attribution |

> **Action item:** Replace `tatsu-lab/alpaca` (NC license) with `yahma/alpaca-cleaned`
> (CC-BY-4.0) to maintain commercial-use compatibility throughout the pipeline.

---

*Dataset Strategy section added: 2026-03-28. 17 datasets selected, 15 active +
2 synthetic corpora. Phase 1 target: ~200K examples. Total pipeline target: ~500K+.*
