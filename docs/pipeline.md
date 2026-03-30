# Training Data Pipeline

The `pipeline/` directory is a self-contained data ingestion, normalization, transformation, and embedding pipeline that builds fine-tuning datasets for Codey-v2 from open-source HuggingFace datasets and locally generated synthetic corpora.

---

## What it does

The pipeline:

1. **Ingests** records from HuggingFace datasets (streamed — no full download required) and local JSONL files
2. **Normalizes** each record: extracts instruction + code/tool-call content, converts Linux idioms to Termux equivalents (`apt` → `pkg`, `python3` → `python`, strips `sudo`), deduplicates, and scores quality
3. **Transforms** normalized records into Codey-v2 tool call format: `{"name": "shell", "args": {"command": "..."}}`
4. **Exports** a `training_data.jsonl` file in ShareGPT format, ready for Unsloth fine-tuning
5. **Optionally embeds** every record with nomic-embed-text and stores vectors + metadata in an hnswlib index + SQLite database for RAG retrieval

---

## Output files

After a run, the output directory (default `./pipeline_output/`) contains:

| File | Description |
|------|-------------|
| `training_data.jsonl` | ShareGPT-format records for fine-tuning (system + user + assistant turns) |
| `pipeline_errors.jsonl` | Records that were skipped, with the reason |
| `pipeline_stats.json` | Run summary: counts, retention rate, tool breakdown, quality histogram |
| `synthetic/synthetic_termux.jsonl` | Generated Termux CLI training examples (~5,800 records) |
| `synthetic/synthetic_multistep.jsonl` | Generated multi-step coding patterns (~50 records) |
| `retrieval/index.bin` | hnswlib vector index (only with `--embed`) |
| `retrieval/metadata.db` | SQLite store keyed by vector ID (only with `--embed`) |

### training_data.jsonl format

Each line is a JSON object in ShareGPT format:

```json
{
  "conversations": [
    {"role": "system",    "content": "<Codey-v2 system prompt>"},
    {"role": "user",      "content": "install python in termux"},
    {"role": "assistant", "content": "<tool>\n{\"name\": \"shell\", \"args\": {\"command\": \"pkg install python\"}}\n</tool>"}
  ],
  "metadata": {
    "id": "a3f2c8b1",
    "source": "synthetic",
    "quality": 0.8,
    "language": null,
    "num_steps": 1,
    "tool_names": ["shell"],
    "has_test": false,
    "is_synthetic": true
  }
}
```

Multi-step records produce multiple `<tool>` blocks in the assistant turn, one per step.

---

## Quick start

### Synthetic data only (no internet required)

```bash
python pipeline/run.py --synthetic-only
```

Generates ~5,830 training records from built-in templates. No HuggingFace connection needed.

### Phase 1 datasets (recommended starting point)

```bash
python pipeline/run.py --datasets phase1
```

Streams from 5 HuggingFace datasets: glaive, hermes, mbpp, humaneval, python18k. Processes up to the full dataset with 50% quality filter.

### Limit records per dataset

```bash
python pipeline/run.py --datasets phase1 --max-records 1000
```

Useful for testing — processes at most 1,000 records per dataset.

### Specific datasets

```bash
python pipeline/run.py --datasets mbpp humaneval
```

### With embedding (RAG index)

```bash
python pipeline/run.py --datasets phase1 --embed
```

Requires the nomic-embed-text llama-server running on port 8082 (`codeyd2 start` handles this). Builds a vector index for RAG retrieval in addition to the training JSONL.

### Custom output directory

```bash
python pipeline/run.py --datasets phase1 --output-dir ~/my_training_data
```

---

## All CLI options

```
python pipeline/run.py [OPTIONS]

Options:
  --datasets NAMES...     Dataset shortnames or phase keyword (default: phase1)
  --output-dir DIR        Output directory (default: ./pipeline_output)
  --min-quality FLOAT     Minimum quality score 0.0–1.0 (default: 0.5)
  --max-records INT        Max records per dataset (default: unlimited)
  --embed                 Build embedding index (requires nomic on port 8082)
  --skip-synthetic        Skip synthetic corpus generation
  --synthetic-only        Generate synthetic data only, skip HF datasets
  --extra-jsonl FILE...   Additional local JSONL files to include
  --force-local-embed     Use sentence-transformers instead of nomic server
```

---

## Dataset phases

### Phase 1 — Tool call + coding fundamentals

| Shortname | HuggingFace path | Records | Focus |
|-----------|-----------------|---------|-------|
| `glaive` | glaiveai/glaive-function-calling-v2 | ~113K | Function calling (JSON `<functioncall>`) |
| `hermes` | NousResearch/hermes-function-calling-v1 | ~12K | Function calling (XML `<tool_call>`) |
| `mbpp` | google-research-datasets/mbpp | ~374 | Python programming (write + test + run) |
| `humaneval` | evalplus/humanevalplus | ~164 | Python programming (write + test + run) |
| `python18k` | iamtarun/python_code_instructions_18k_alpaca | ~18K | Python coding from natural language |

### Phase 2 — Broader function calling and code

| Shortname | HuggingFace path | Records | Focus |
|-----------|-----------------|---------|-------|
| `xlam` | lockon/xlam-function-calling-60k | ~60K | Multi-tool chains |
| `code122k` | TokenBender/code_instructions_122k_alpaca_style | ~122K | Code generation from instructions |
| `codefeedback` | m-a-p/Code-Feedback | ~66K | Code fixes and feedback |
| `apigen` | argilla/apigen-function-calling | ~60K | API-style function calls |

### Phase 3 — Extended coverage

| Shortname | HuggingFace path | Records | Focus |
|-----------|-----------------|---------|-------|
| `bigcodebench` | bigcode/bigcodebench | ~1.1K | Complex multi-library tasks |
| `humanevalpack` | bigcode/humanevalpack | ~820 | Cross-language bug fixes |
| `alpaca` | yahma/alpaca-cleaned | ~52K | General instruction following |
| `codesearchnet` | Nan-Do/instructional_code-search-net-python | ~100K | Python code search and explanation |
| `orca` | microsoft/orca-agentinstruct-1M-v1 | ~1M | Agent-style instruction tuning |

Use phase keywords to select a group:

```bash
python pipeline/run.py --datasets phase1
python pipeline/run.py --datasets phase2
python pipeline/run.py --datasets phase3
```

---

## Quality scoring

Every record receives a quality score 0.0–1.0. Records scoring below `--min-quality` (default 0.5) are dropped.

| Factor | Effect |
|--------|--------|
| Base score | +0.50 |
| Instruction ≥ 5 words | +0.10 |
| Placeholder content detected (`...`, `pass`, `TODO`) | −0.50 |
| Source is curated (mbpp, humaneval, bigcodebench) | +0.15 |
| Record is execution-verified (has passing test) | +0.15 |
| Multi-step record (≥ 2 tool calls) | +0.10 |

---

## Termux normalization

The pipeline automatically converts Linux-style commands to their Termux equivalents:

| Linux | Termux |
|-------|--------|
| `sudo apt install python3` | `pkg install python` |
| `apt-get install nodejs` | `pkg install nodejs` |
| `python3 script.py` | `python script.py` |
| `pip3 install flask` | `pip install flask` |
| `/usr/bin/python` | `python` |
| `/usr/local/bin/pip` | `pip` |

`sudo` is stripped from all commands. Package names are mapped to their Termux equivalents where they differ (e.g., `gcc` → `clang`).

---

## Tool call format

All output records use Codey-v2's native tool call format:

```
<tool>
{"name": "TOOL_NAME", "args": {"ARG": "VALUE"}}
</tool>
```

The 9 supported tools and their required arguments:

| Tool | Required args |
|------|--------------|
| `shell` | `command` |
| `write_file` | `path`, `content` |
| `patch_file` | `path`, `old_str`, `new_str` |
| `read_file` | `path` |
| `append_file` | `path`, `content` |
| `list_dir` | `path` |
| `search_files` | `pattern` |
| `note_save` | `key`, `value` |
| `note_forget` | `key` |

Function calls from Glaive/Hermes/xLAM are mapped to these tools by name pattern. Generic code generation becomes `write_file`. Shell commands become `shell`. MBPP/HumanEval tasks become 3-step records: `write_file` (solution) + `write_file` (test) + `shell` (run test).

---

## Using the output for fine-tuning

The `training_data.jsonl` output is in ShareGPT format, directly compatible with [Unsloth](https://github.com/unslothai/unsloth) on Google Colab.

See [fine-tuning.md](fine-tuning.md) for the full Colab workflow. The key step is uploading `training_data.jsonl` to your Colab environment and pointing Unsloth's `dataset_text_field` to the `conversations` key.

---

## Using the output for RAG

When run with `--embed`, the pipeline builds a retrieval index alongside the training data. The index is used automatically by the Codey-v2 daemon for tool-call retrieval — when you ask Codey to do something, it searches the index for similar past examples and injects the top-k results into the prompt.

The index lives at `pipeline_output/retrieval/`:
- `index.bin` — hnswlib cosine vector index (768-dim nomic vectors)
- `metadata.db` — SQLite store with full records keyed by vector ID

To use a custom index with the daemon, set the `retrieval_index` path in `config.json`.

---

## Architecture

```
pipeline/
├── run.py                  CLI entry point
├── synthetic.py            Synthetic corpus generator (Termux + multi-step)
├── ingestion/
│   ├── hf_ingestor.py      Streams HuggingFace datasets
│   └── jsonl_ingestor.py   Reads local JSONL files
├── normalization/
│   ├── normalizer.py       12 per-schema extractors + TermuxNormalizer
│   ├── classifier.py       Response type and language detection
│   └── quality.py          Quality scorer 0.0–1.0
├── transformation/
│   ├── transformer.py      Main transformation engine
│   ├── rules.py            Per-dataset transformation rules
│   ├── termux.py           Termux command normalizer
│   └── validator.py        Tool call schema validation
├── embedding/
│   ├── embedder.py         Backend auto-selector + embed_text builder
│   ├── nomic_client.py     HTTP client for nomic-embed-text on port 8082
│   └── sentence_client.py  sentence-transformers fallback (384-dim MiniLM)
├── storage/
│   ├── vector_store.py     hnswlib wrapper with numpy brute-force fallback
│   └── sqlite_store.py     SQLite metadata store keyed by vector ID
└── export/
    └── exporter.py         ShareGPT JSONL writer + stats
```

Each record flows through the pipeline as:

```
raw HF record
    → ingestor (tag with _source, _schema_type)
    → normalizer (extract instruction + content, Termux-normalize, deduplicate, quality score)
    → transformer (convert to tool calls, validate schema)
    → exporter (write ShareGPT JSONL + stats)
    → [optional] embedder → vector_store + sqlite_store
```
