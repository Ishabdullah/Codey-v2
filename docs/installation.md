# Installation Guide

## Requirements

| Requirement | Specification |
|-------------|---------------|
| **Platform** | Termux on Android, or any Linux system |
| **RAM** | 6 GB+ available |
| **Storage** | ~10 GB (7B model + 0.5B model + Codey) |
| **Python** | 3.12+ |
| **Packages** | `rich`, `numpy`, `watchdog` |

---

## One-Line Install

```bash
./install.sh
```

This handles everything below automatically. If you prefer full control, follow the manual steps.

---

## Manual Installation

### Step 1 — Install system dependencies

```bash
pkg install cmake ninja clang python
pip install rich numpy watchdog
```

### Step 2 — Build llama.cpp

```bash
git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DLLAMA_CURL=OFF  # disables optional libcurl dependency (unavailable on Termux; not needed for local inference)
cmake --build build --config Release -j4
```

The build takes 10–20 minutes on a modern Android device.

### Step 3 — Download models

**Primary model — Qwen2.5-Coder-7B (~4.7 GB)**

```bash
mkdir -p ~/models/qwen2.5-coder-7b
cd ~/models/qwen2.5-coder-7b
wget https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf
```

**Planner/summarizer model — Qwen2.5-0.5B (~400 MB)**

```bash
mkdir -p ~/models/qwen2.5-0.5b
cd ~/models/qwen2.5-0.5b
wget https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q8_0.gguf
```

**Embedding model — nomic-embed-text-v1.5 (~80 MB)**

```bash
mkdir -p ~/models/nomic-embed
cd ~/models/nomic-embed
wget https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf
```

### Step 4 — Clone Codey-v2

```bash
git clone https://github.com/Ishabdullah/Codey.git ~/codey-v2
cd ~/codey-v2
chmod +x codey2 codeyd2
```

### Step 5 — Add to PATH

```bash
echo 'export PATH="$HOME/codey-v2:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

> **Other shells:** For `zsh`, replace `~/.bashrc` with `~/.zshrc`. For fish, add `set -x PATH $HOME/codey-v2 $PATH` to `~/.config/fish/config.fish`. For a universal fallback, add the export to `~/.profile`.

### Step 6 — Verify

```bash
codey2 --version
codeyd2 status
```

---

## Optional: Knowledge Base

Setting up a local knowledge base significantly improves response quality. See [knowledge-base.md](knowledge-base.md) for the full guide.

## Optional: Fine-tuning

You can personalize the model using your own interaction history. See [fine-tuning.md](fine-tuning.md) for the full workflow.

---

## Optional: Training Data Pipeline

The `pipeline/` directory contains a full data ingestion and transformation pipeline that builds fine-tuning datasets in ShareGPT format from open-source HuggingFace datasets and synthetic corpora.

### What the pipeline needs

The pipeline has additional dependencies beyond the base Codey-v2 install. The install order matters on Termux — some packages with C extensions must be installed via `pkg` (pre-built ARM binaries); pip cannot compile them on aarch64.

#### Step 1 — Install compiled packages via pkg

```bash
pkg install python-pyarrow python-pandas
```

> Do **not** use `pip install pyarrow` or `pip install pandas` on Termux. Pip will attempt to compile from source and fail with Rust/meson/Cython errors on aarch64. The `pkg` versions (pyarrow 23.0.1, pandas 3.0.1 as of this writing) are pre-built and work immediately.

#### Step 2 — Install Python packages via pip

```bash
pip install datasets huggingface-hub "fsspec==2026.2.0" \
            httpcore httpx typer tqdm hnswlib \
            aiohttp multiprocess dill xxhash pyyaml \
            filelock requests
```

**Key notes:**

- **`fsspec==2026.2.0` must be pinned.** The `datasets` 4.8.4 library is incompatible with `fsspec>=2026.3.0`. Installing without the pin causes an `ImportError` at runtime. If you already have a newer fsspec, downgrade: `pip install "fsspec==2026.2.0"`.

- **`hnswlib` build requires clang.** If you haven't installed clang already (for llama.cpp), run `pkg install clang cmake` first. If hnswlib fails to build for any reason, the pipeline automatically falls back to numpy brute-force cosine search — you do not need hnswlib for the pipeline to work.

- **`hf-xet` build failures are harmless.** You may see `ERROR: Failed to build 'hf-xet'` during `pip install datasets`. This is an optional Rust extension used only for HuggingFace uploads; it is not used by the pipeline. Ignore it.

- **Embedding backend.** The pipeline defaults to the nomic-embed-text llama-server already running on port 8082. `sentence-transformers` is an optional 384-dim fallback that requires PyTorch, which is unavailable on Termux/Android. Only install it if you are running the pipeline on a desktop Linux machine.

### Verify the install

```bash
python pipeline/run.py --synthetic-only
```

This generates two synthetic JSONL corpora (~5K Termux CLI examples and ~3K multi-step patterns) without downloading anything from HuggingFace. Expected output:

```
  Synthetic Termux corpus:    5,780 records → pipeline_output/synthetic/synthetic_termux.jsonl
  Synthetic multi-step corpus: 50 records → pipeline_output/synthetic/synthetic_multistep.jsonl
  Output records:  5,830  (100.0% retention)
```

### Storage requirements

| Component | Size |
|-----------|------|
| Base Codey-v2 (models + toolchain) | ~6 GB |
| Pipeline dependencies (pip packages) | ~800 MB |
| HuggingFace dataset cache (phase 1, streaming) | minimal — only processed records kept |
| Pipeline output (training_data.jsonl + index) | ~50–500 MB depending on record count |
| **Total with pipeline** | **~7–8 GB** |

> If you download all HuggingFace datasets locally instead of streaming, add ~4 GB for phase 1, ~3 GB for phase 2, and ~6 GB for phase 3. Streaming mode (the default) avoids this entirely.

See [pipeline.md](pipeline.md) for the full pipeline guide.
