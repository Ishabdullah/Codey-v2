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
