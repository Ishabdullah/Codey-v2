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

![Codey Mascot](assets/codey-mascot.png)

A persistent, daemon-based AI coding agent that runs entirely on your Android device. CODEY-V2 maintains state across sessions, manages a background task queue, and uses three purpose-built models — a 7B primary agent, a 0.5B planner and summarizer, and a dedicated embedding encoder — all served locally via llama.cpp.

> **Security notice:** CODEY-V2 executes shell commands and writes files based on model output. Read the [security guide](docs/security.md) before use.

---

## Quick Start

```bash
./install.sh          # Install everything (models, llama.cpp, PATH)
codeyd2 start         # Start all three model servers and the daemon
codey2 "your task"    # Send a task
codeyd2 status        # Check daemon health at any time
```

See [docs/installation.md](docs/installation.md) for manual setup and model download links.

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
