# Command Reference

## Daemon Manager — `codeyd2`

| Command | Description |
|---------|-------------|
| `codeyd2 start` | Start all daemons in the background |
| `codeyd2 stop` | Stop all daemons cleanly |
| `codeyd2 status` | Show daemon status, uptime, and model state |
| `codeyd2 restart` | Restart all daemons |
| `codeyd2 reload` | Send hot-reload signal (SIGUSR1) without downtime |
| `codeyd2 config` | Write a default config file to `~/.codey-v2/config.json` |

---

## CLI Client — `codey2`

| Command | Description |
|---------|-------------|
| `codey2 "prompt"` | Send a task to the running daemon, or run standalone if no daemon is active |
| `codey2 status` | Show full system status |
| `codey2 task list` | List recent tasks and their state |
| `codey2 task <id>` | Get full details of a specific task |
| `codey2 cancel <id>` | Cancel a pending or running task |
| `codey2 --daemon` | Run in foreground daemon mode (for debugging) |

### CLI Flags

| Flag | Description |
|------|-------------|
| `--yolo` | Skip all confirmations |
| `--allow-self-mod` | Enable self-modification with checkpoint enforcement |
| `--threads N` | Override CPU thread count |
| `--ctx N` | Override context window size |
| `--read <file>` | Pre-load a file into context before starting |
| `--init` | Generate `CODEY.md` for the current project and exit |
| `--fix <file>` | Run a file and auto-fix any errors |
| `--tdd <file>` | TDD mode — run tests and iterate until they pass |
| `--no-resume` | Start a fresh session (ignore saved history) |
| `--plan` | Force planning mode for complex tasks |
| `--no-plan` | Disable orchestration and planning |
| `--finetune` | Export interaction data for fine-tuning |
| `--import-lora` | Import a trained LoRA adapter |
| `--rollback` | Roll back to the model state before last LoRA import |

---

## In-Session Slash Commands

### Files & Context

| Command | Description |
|---------|-------------|
| `/read <file>` | Load a file into the current context |
| `/diff [file]` | Show what Codey changed in this session |
| `/undo [file]` | Restore a file to its previous version |
| `/search <pattern>` | Grep across all project files |
| `/context` | Show which files are currently loaded |
| `/clear` | Clear conversation history and session state |
| `/exit` | Save session and quit |

### Git

| Command | Description |
|---------|-------------|
| `/git` | Show git status |
| `/git branches` | List all branches (current highlighted) |
| `/git branch <name>` | Create and switch to a new branch |
| `/git checkout <name>` | Switch branch with confirmation prompt |
| `/git merge <branch>` | Merge with conflict detection and resolution flow |
| `/git commit` | Generate an AI commit message from diff — you approve before commit |
| `/git commit "msg"` | Commit with an exact message |
| `/git diff` | Show the current diff |
| `/git push` | Push to remote |
| `/git conflicts` | List all conflicted files |

### Code Quality

| Command | Description |
|---------|-------------|
| `/review <file.py>` | Lint with all available tools and offer agent fix |

### Knowledge Base

| Command | Description |
|---------|-------------|
| `/rag <prompt>` | Show what the KB would retrieve and inject for a given prompt |

### Voice

| Command | Description |
|---------|-------------|
| `/voice` | Show voice status |
| `/voice on` / `/voice off` | Enable or disable TTS + STT |
| `/voice listen` | Speak one task and send it to the agent immediately |
| `/voice rate <n>` | Set TTS speech speed (default 1.0) |
| `/voice pitch <n>` | Set TTS pitch (default 1.0) |
| `/voice speak <text>` | Test TTS with a specific phrase |

### Peer CLI Escalation

| Command | Description |
|---------|-------------|
| `/peer` | List available peer CLIs and their status |
| `/peer <name> <task>` | Call a specific peer CLI directly |
| `/peer <task>` | Auto-pick the best peer CLI for the task |

### System

| Command | Description |
|---------|-------------|
| `/learning` | Show learning system status and learned preferences |
| `/status` | Full system state: tasks, memory, tokens, thermal |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CODEY_MODEL` | Override the primary model path |
| `CODEY_EMBED_MODEL` | Override the embedding model path |
| `CODEY_7B_MMAP=0` | Disable memory-mapped weights (use if RAM is tight) |
| `CODEY_7B_MLOCK=1` | Lock weights in RAM (prevents paging under pressure) |
| `CODEY_THREADS` | Override CPU thread count |
| `CODEY_LINTER` | Override linter: `ruff`, `flake8`, or `mypy` |
| `CODEY_PLANND_PORT` | Override the planner/summarizer model port (default 8081) |
| `CODEY_EMBED_PORT` | Override the embedding model port (default 8082) |
| `ALLOW_SELF_MOD=1` | Enable self-modification (alternative to `--allow-self-mod`) |
