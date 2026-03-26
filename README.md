# Codey-v2

```
  ██████╗ ██████╗ ██████╗ ███████╗██╗   ██╗
 ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗ ██╔╝
 ██║     ██║   ██║██║  ██║█████╗   ╚████╔╝
 ██║     ██║   ██║██║  ██║██╔══╝    ╚██╔╝
 ╚██████╗╚██████╔╝██████╔╝███████╗   ██║
  ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝
  v2.7.0 · Three-Model AI Agent · Termux
```

![Codey Mascot](assets/codey-mascot.png)

A persistent, daemon-based AI coding agent that runs entirely on your Android device. Codey-v2 maintains state across sessions, manages a background task queue, and uses three purpose-built models — a 7B primary agent, a 0.5B planner and summarizer, and a dedicated embedding encoder — all served locally via llama.cpp.

> **Security notice:** Codey executes shell commands and writes files based on model output. Read the [security guide](docs/security.md) before use.

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

## What's New in v2.7.0

### Smarter Context Management

Long sessions no longer degrade. Context compression has been completely reworked:

| | Before | After |
|-|--------|-------|
| Trigger threshold | 75% of context window | **55%** — fires before things get tight |
| After compression | Left wherever it landed | **Drops to 40%** — real headroom restored |
| Message truncation | `content[:300]` before summarizing | **Removed** — full content passed to summarizer |
| Summarizer model | 7B (same model doing your work) | **0.5B on port 8081** — fast, independent |
| What gets summarized | Everything old, one flat pass | **Only dropped turns** — pinned messages survive |
| Re-summarization | Could summarize a summary | **Blocked** — existing summaries are pinned |

**Pinned messages** (never dropped): file writes, patches, errors, shell results, and existing summaries. The 0.5B call is best-effort — if port 8081 is unreachable, the drop still happens and the agent keeps working.

### Planner Timeout Increase

The planning call timeout has been raised from 45 s → **180 s**, with the HTTP timeout set to 165 s so the network call always resolves cleanly before the outer timeout fires.

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
- **Peer CLI escalation** — calls Claude Code, Gemini CLI, or Qwen CLI when retry budget is exhausted
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
| [Security](docs/security.md) | Risks, mitigations, hardening summary, reporting vulnerabilities |
| [Troubleshooting](docs/troubleshooting.md) | Common issues, performance reference, known limitations |
| [Version History](docs/version-history.md) | Full changelog from v1.0.0 through v2.7.0 |

---

## Requirements

| | |
|-|-|
| **Platform** | Termux on Android, or any Linux system |
| **RAM** | 6 GB+ available |
| **Storage** | ~10 GB |
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
