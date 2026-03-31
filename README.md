# CODEY-V2

```
  ██████╗ ██████╗ ██████╗ ███████╗██╗   ██╗
 ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗ ██╔╝
 ██║     ██║   ██║██║  ██║█████╗   ╚████╔╝
 ██║     ██║   ██║██║  ██║██╔══╝    ╚██╔╝
 ╚██████╗╚██████╔╝██████╔╝███████╗   ██║
  ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝  ─ V2
  v2.0.0 · Local AI Coding Assistant · Termux
```

> **Codey-v2: A persistent, fully local AI coding agent that runs in Termux on your Android phone — with daemon mode, RAG, git tools, voice, and self-refinement. No cloud required.**

[![Stars](https://img.shields.io/github/stars/Ishabdullah/Codey-v2?style=flat-square&color=gold)](https://github.com/Ishabdullah/Codey-v2/stargazers)
[![License](https://img.shields.io/github/license/Ishabdullah/Codey-v2?style=flat-square)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/Ishabdullah/Codey-v2?style=flat-square)](https://github.com/Ishabdullah/Codey-v2/commits/main)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python)](https://python.org)
[![llama.cpp](https://img.shields.io/badge/inference-llama.cpp-green?style=flat-square)](https://github.com/ggerganov/llama.cpp)

![Codey Mascot](assets/codey-mascot.png)

A persistent, daemon-based AI coding agent that runs entirely on your Android device. CODEY-V2 maintains state across sessions, manages a background task queue, and uses three purpose-built models — a 7B primary agent, a 0.5B planner and summarizer, and a dedicated embedding encoder — all served locally via llama.cpp.

> **Security notice:** CODEY-V2 executes shell commands and writes files based on model output. Read the [security guide](docs/security.md) before use.

---

## Quick Start

### Local — on-device models (5 steps)

```bash
# 1. Clone and enter the repo
git clone https://github.com/Ishabdullah/Codey-v2.git && cd Codey-v2

# 2. Run the installer (downloads models, builds llama.cpp, sets PATH)
./install.sh

# 3. Start all three model servers and the background daemon
codeyd2 start

# 4. Send your first task
codey2 "add a docstring to every function in utils.py"

# 5. Check daemon health at any time
codeyd2 status
```

See [docs/installation.md](docs/installation.md) for manual setup and model download links.

---

### OpenRouter — cloud inference, no local models (5 steps)

```bash
# 1. Clone and install Python dependencies
git clone https://github.com/Ishabdullah/Codey-v2.git && cd Codey-v2
pip install -r requirements.txt

# 2. Set your API key (get one at https://openrouter.ai/keys)
export OPENROUTER_API_KEY="sk-or-your-key-here"

# 3. Switch to the OpenRouter backend
export CODEY_BACKEND="openrouter"

# 4. (Optional) Choose a model — default is qwen/qwen-2.5-coder-7b-instruct
export OPENROUTER_MODEL="anthropic/claude-sonnet-4-5"

# 5. Run a task
python main.py "refactor my sort function to use timsort"
```

To make env vars permanent, add them to `~/.bashrc` and run `source ~/.bashrc`.

Any model slug from [openrouter.ai/models](https://openrouter.ai/models) works. You can also mix backends — run the planner locally while routing coding calls to OpenRouter:

```bash
export CODEY_BACKEND="openrouter"    # coding → OpenRouter
export CODEY_BACKEND_P="local"       # planner → local 0.5B (port 8081)
```

---

## Visuals

> **Screenshots and demo GIFs coming soon.**
> To contribute a screen recording of Codey in action, open a PR and drop your asset in `assets/` — it is hugely appreciated and helps other Android developers discover this project.

<!-- Suggested assets:
  assets/demo-task.gif  — a short GIF of `codey2 "add a function to sort this list"` running end-to-end
  assets/screenshot-cli.png  — terminal output showing the blue banner, tool calls, and result
  assets/screenshot-daemon.png  — `codeyd2 status` output
-->

---

## What's New in v2.0.0

### First Stable Release

- **Rebranded to CODEY-V2** — clean CLI banner in blue, unified name across all interfaces
- **Malformed JSON recovery** — relaxed parser now handles unquoted values emitted by smaller models, eliminating silent tool-call failures
- **Shell safety hardened** — dangerous command detection expanded to catch `find -delete`, `git reset --hard`, `git push --force`, and indirect execution via `sh -c` / `bash -c`
- **Peer code extraction improved** — fuzzy filename matching in peer output now handles `### File: x.py` and `File: x.py` heading styles in addition to bold/backtick patterns
- **Unified planning interface** — `core/planner_service.py` consolidates daemon (0.5B) and orchestrator (7B) planning paths into a single entry point
- **Memory system cleaned up** — all callers now import directly from `core/memory_v2.py`; the legacy shim has been removed
- **LRU eviction threshold fixed** — aligned to 3 turns (was incorrectly set to 6, causing memory bloat)
- **Codebase pruned** — removed legacy `core/loader.py`, `core/router.py`, outdated audit reports, and old plan documents

---

## Capabilities

### Three-Model Architecture

| Model | Port | Role |
|-------|------|------|
| Qwen2.5-Coder-7B Q4_K_M | 8080 | Primary agent — coding, reasoning, tool use |
| Qwen2.5-0.5B Q8_0 | 8081 | Task planning and conversation summarization |
| nomic-embed-text-v1.5 Q4 | 8082 | RAG retrieval encoder |

All three run as independent llama-server processes, managed and watchdog-monitored by `codeyd2`.

### Agent Features

- **Persistent daemon** — runs continuously in the background; state survives restarts
- **Task queue** — complex requests broken into steps and executed sequentially
- **RAG retrieval** — local knowledge base searched on every inference call; relevant docs injected automatically
- **Recursive self-refinement** — draft → critique → refine cycle catches bugs before they hit your files
- **Error recovery** — adaptive strategy switching when tools fail (write → patch, import error → install, etc.)
- **Peer CLI escalation** — delegates work to Claude Code, Gemini CLI, or Qwen CLI either on-demand ("ask Claude to X") or automatically when CODEY-V2 exhausts its retry budget. The peer receives current project file contents and returns complete, ready-to-apply code blocks that CODEY-V2 writes to disk. Requires explicit user consent before any files are shared (external services — see [Security](docs/security.md))
- **Git integration** — branch management, AI commit messages, conflict detection and resolution
- **Voice interface** — TTS output and STT input via Termux:API
- **Static analysis** — auto-lint on every Python write; `/review` command for on-demand scans
- **Thermal management** — monitors CPU load and battery; reduces threads automatically under stress
- **Fine-tuning** — export your interaction history and train a personalized adapter on Google Colab

---

## Documentation

| Guide | Contents |
|-------|----------|
| [Installation](docs/installation.md) | Requirements, one-line install, manual step-by-step |
| [Commands](docs/commands.md) | Full reference: `codeyd2`, `codey2`, slash commands, flags, env vars |
| [Configuration](docs/configuration.md) | Config JSON, model tuning, context management, thermal settings |
| [Architecture](docs/architecture.md) | System diagram, memory tiers, project structure, Python API |
| [Knowledge Base](docs/knowledge-base.md) | Setting up RAG, indexing docs, skill repos |
| [Fine-tuning](docs/fine-tuning.md) | Export data, Colab training, import adapter, rollback |
| [Pipeline](docs/pipeline.md) | Training data pipeline — build fine-tuning datasets from HuggingFace + synthetic data |
| [Security](docs/security.md) | Risks, mitigations, hardening summary, reporting vulnerabilities |
| [Troubleshooting](docs/troubleshooting.md) | Common issues, performance reference, known limitations |
| [Version History](docs/version-history.md) | Full changelog |

---

## Requirements

| | |
|-|-|
| **Platform** | Termux on Android, or any Linux system |
| **RAM** | 6 GB+ available |
| **Storage** | ~6 GB base (7B model ~4.2 GB, 0.5B ~500 MB, embed ~80 MB, toolchain ~1 GB); ~8 GB with training pipeline |
| **Python** | 3.12+ |

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes and run the tests (`pytest tests/ -v`)
4. Submit a pull request

Bug reports, security disclosures, and hardening contributions are especially welcome.

---

## Acknowledgments

- [llama.cpp](https://github.com/ggerganov/llama.cpp) — efficient on-device LLM inference
- [Qwen](https://huggingface.co/Qwen) — Qwen2.5-Coder models
- [nomic-ai](https://huggingface.co/nomic-ai) — nomic-embed-text embedding model
- [Codey v1](https://github.com/Ishabdullah/Codey) — the original session-based agent this builds on

---

MIT License

---

*If Codey helps you code on the go, consider starring ⭐ the repo — it helps other Android developers find this project!*
