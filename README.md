# Codey-v2

**⚠️ Powerful on-device agent – persistent & adaptive. Know what you're doing – see Security Considerations below.**

**A persistent, daemon-like AI agent that lives on your device.**

Codey-v2 transforms Codey https://github.com/Ishabdullah/Codey from a session-based CLI tool into a continuous AI agent—maintaining state, managing background tasks, and adapting to work without constant supervision. All while running locally on your Android device with dual-model hot-swap for thermal and memory efficiency.

```
  ██████╗ ██████╗ ██████╗ ███████╗██╗   ██╗
 ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗ ██╔╝
 ██║     ██║   ██║██║  ██║█████╗   ╚████╔╝
 ██║     ██║   ██║██║  ██║██╔══╝    ╚██╔╝
 ╚██████╗╚██████╔╝██████╔╝███████╗   ██║
  ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝
  v2.6.2 · Learning AI Agent · Termux
```

---

## Key Features

### 🔄 Recursive Self-Refinement (v2.6.2)
- **Draft → Critique → Refine**: On every non-trivial coding task, the model reviews its own output before returning it — catching bugs, missing imports, and incomplete code before they reach your files
- **Adaptive depth**: `classify_breadth_need()` auto-detects task complexity: simple Q&A = single pass; typical code edits = 1 critique+refine cycle; multi-file/complex tasks = 2 cycles
- **Quality gate**: If the model rates its own output ≥ 7/10, refinement is skipped — no wasted inference on already-good responses
- **NEED_DOCS retrieval**: When the model is unsure about an API, it emits `NEED_DOCS: <topic>` in the critique — triggering a targeted KB search before the refine pass
- **Zero regression risk**: All recursive passes are wrapped in `try/except` — any failure transparently falls back to single-pass inference
- **Configurable**: `RECURSIVE_CONFIG["enabled"] = False` reverts to v2.6.1 behavior instantly

### 📚 Knowledge Base + RAG Retrieval (v2.6.1)
- **Local knowledge base**: `knowledge/` directory stores docs, APIs, patterns, and skill repos as searchable chunks
- **Auto-retrieval**: Every inference call searches the KB and injects up to ~600 tokens of relevant context into the system prompt — the model sees the right docs for the task
- **Dual search backends**: Semantic search via `sentence-transformers` all-MiniLM-L6-v2 (80 MB, 384-dim); pure keyword fallback always active with zero dependencies
- **Skill repos**: `bash tools/setup_skills.sh` clones 4 curated skill repositories and indexes them automatically
- **Bring your own docs**: Drop `.md`/`.txt` files into `knowledge/docs/` and index them in one command
- **Effective model uplift**: RAG + 3-pass recursion (Phase 2) targets ~20B-equivalent quality from a 7B model
- **Graceful degradation**: Empty KB = no retrieval overhead; the agent loop is never blocked

```bash
# First-time setup (run once) — no extra packages needed
bash tools/setup_skills.sh

# Add your own docs
cp my_guide.md ~/codey-v2/knowledge/docs/
python -c "from tools.kb_scraper import index_directory; index_directory('knowledge/docs', 'docs')"
```

> **Termux/Android**: BM25 keyword search is built-in (zero dependencies). Vector semantic search requires `fastembed` or `sentence-transformers`, neither of which have ARM64 Android wheels — skip them, BM25 is the active backend and works well.

### 🌿 Git Enhancements (v2.5.5)
- **Branch management**: `/git branches` lists all branches; `/git branch <name>` creates and switches; `/git checkout <name>` switches with confirmation prompt
- **Smart merge**: `/git merge <branch>` merges with automatic conflict detection and resolution flow
- **AI commit messages**: `/git commit` reads the diff and generates a meaningful message — you review and accept or edit before it commits
- **Conventional commits**: Detects if your project uses `feat:` / `fix:` style and matches it automatically
- **Conflict resolution**: Shows which files conflict, presents both sides, asks if Codey should resolve
- **`/git conflicts`**: List all conflicted files at any time

### 🎙️ Voice Interface (v2.5.1)
- **Text-to-Speech**: Every response is spoken aloud via `termux-tts-speak` — code blocks and markdown filtered out, only prose spoken
- **Speech-to-Text**: Press Enter on a blank line (in voice mode) to speak your task via `termux-speech-to-text`
- **Voice Mode Toggle**: `/voice on` / `/voice off` — preference saved across sessions
- **Configurable**: `/voice rate 1.5` (speed), `/voice pitch 0.9`, engine, language
- **Interrupt**: Ctrl+C stops speech mid-sentence
- **Requires**: Termux:API app + `pkg install termux-api`

### 🔍 Static Analysis & Code Review (v2.5.2)
- **Auto-lint on write**: Every Python file Codey writes is automatically linted — issues appended to agent context so it can self-correct
- **Pre-write syntax gate**: Python files with broken syntax are blocked before they touch disk — agent retries with the error
- **`/review <file>`**: Full multi-linter scan (ruff + flake8 + mypy + syntax) with colored output, then optional agent fix
- **Tool priority**: ruff → flake8 → mypy → ast (uses first available; override with `CODEY_LINTER=flake8`)
- **No tools required**: Syntax checking works with zero external tools via Python's `ast.parse`

### 🤝 Peer CLI Escalation (v2.5.0)
- **Auto-escalation**: When Codey hits max retries, it can call Claude Code, Gemini CLI, or Qwen CLI for help
- **Manual escalation**: `/peer` command to directly invoke a peer CLI at any time
- **Smart routing**: Task type detection picks the best CLI (debugging → Claude, analysis → Gemini, generation → Qwen)
- **Non-interactive mode**: All peers run via `-p` flag — clean streaming output, no TUI overhead
- **Crash detection**: At startup, Codey tests each CLI binary and auto-excludes any that crash (e.g. missing native modules on Android ARM64)
- **Result injection**: Peer output is summarized and injected into Codey's conversation context to continue the task
- **User control**: Confirm/deny/redirect/switch-CLI prompt before any escalation runs

### 🧠 Enhanced Learning (v2.5.0)
- **Natural language detection**: Learns preferences from plain statements ("I prefer type hints", "use httpx not requests")
- **Expanded categories**: Tracks `type_hints`, `async_style`, `http_library`, `cli_library`, `log_style` in addition to existing preferences
- **CODEY.md sync**: High-confidence preferences are automatically written to the project's Conventions section
- **File-based learning**: Detects coding style from files Codey reads or writes during a session

### 🔍 Self-Review Fix (v2.5.0)
- **Reads before reviewing**: Codey now auto-loads its own source files when asked to review or analyze itself
- **No more hallucination**: Self-review requests trigger pre-loading of `agent.py`, `main.py`, `inference_hybrid.py`, etc.
- **REVIEW/AUDIT rule**: System prompt enforces `read_file` before commenting on any code

### 🔧 Fine-tuning Support (v2.3.0)
- **Export Interaction Data**: Curate high-quality examples from your history
- **Unsloth Colab Notebooks**: Ready-to-run fine-tuning on free T4 GPU
- **LoRA Adapter Import**: Import trained adapters back to Codey-v2
- **Off-device Training**: Heavy compute on Colab, not your phone
- `codey2 --finetune` to export, `codey2 --import-lora` to import

### 🧠 Machine Learning (v2.2.0)
- **User Preference Learning**: Automatically learns your coding style (test framework, naming, imports)
- **Error Pattern Database**: Remembers errors and fixes - suggests solutions for similar errors
- **Strategy Tracking**: Learns which recovery strategies work best over time
- **Adaptive Behavior**: Gets smarter with each interaction
- `/learning` command to view learned preferences and statistics

### 🛡️ Security Hardening (v2.1.0)
- **Shell Injection Prevention**: Blocks `;`, `&&`, `||`, `|`, backticks, `$()`, `${}`, `<()`, `>()`
- **Self-Modification Opt-In**: Requires `--allow-self-mod` flag or `ALLOW_SELF_MOD=1` env var
- **Checkpoint Enforcement**: Auto-creates checkpoint before modifying core files
- **Workspace Boundaries**: Files outside workspace blocked unless self-mod enabled
- ## 🔒 Security Considerations

Codey-v2 is a **persistent, autonomous coding agent** that runs as a background daemon in Termux (or Linux), maintains long-term memory, executes shell commands via tools, supports self-modification (opt-in), and loads/runs local LLMs. These capabilities make it powerful but introduce non-trivial security risks compared to simple chat-based local LLMs.

**This is early-stage open-source software — use with caution, especially on devices with sensitive data.** Always review generated code/commands before execution, keep your device physically secure, and consider running in a restricted environment (e.g., dedicated Termux instance or container).

### Key Risks & Mitigations

1. **Persistent Daemon & Background Execution**  
   - The daemon (`codeyd2`) runs continuously with a Unix socket for IPC (`codey-v2.sock`).  
   - **Risk**: If the socket file has permissive permissions or is in a shared location, unauthorized local processes could potentially send commands.  
   - **Mitigations**: Socket created with 0600 permissions (owner-only); daemon runs under your Termux/Linux user (no root required). Stop the daemon when not in use (`codeyd2 stop`). Monitor with `codeyd2 status` or `ps`.  
   - **Recommendation**: Only start on trusted devices; avoid public/multi-user environments.

2. **Shell Command Execution & Tool Use**  
   - Tools can execute shell commands (e.g., file ops, git, etc.) based on agent decisions.  
   - **Risk**: Prompt injection or hallucinated/malicious output could lead to unintended commands (e.g., `rm -rf`, data exfiltration if network tools added later).  
   - **Mitigations**: Aggressive shell injection prevention (blocks `;`, `&&`, `||`, `|`, backticks, `\( ()`, ` \){}`, `<()`, `>()`, etc.); commands run in user context only. User must confirm high-risk actions in most flows (expandable).  
   - **Recommendation**: Always review `--plan` output before execution; use `--no-execute` flag for dry runs.

3. **Self-Modification & Code Alteration**  
   - Opt-in feature allows the agent to patch its own code/files.  
   - **Risk**: If enabled and tricked (via clever prompts or bugs), it could introduce backdoors, delete data, or escalate damage persistently.  
   - **Mitigations**:  
     - Requires explicit `--allow-self-mod` flag **or** `ALLOW_SELF_MOD=1` env var.  
     - Auto-creates checkpoints + full backups before core changes.  
     - Git integration for versioning/rollback.  
     - Workspace boundaries enforced (outside files blocked unless self-mod active).  
   - **Recommendation**: Keep disabled by default. Only enable for experimentation; review diffs/checkpoints immediately after any mod.

4. **Memory & State Persistence**  
   - Hierarchical memory (SQLite for episodic/project state, embeddings for long-term).  
   - **Risk**: Sensitive code snippets, API keys (if you add tools), or personal data could be stored and potentially leaked if device compromised or backups mishandled.  
   - **Mitigations**: Data stored in Termux app-private dirs (`\~/.codey-v2/`); no encryption yet (planned). No automatic exfiltration.  
   - **Recommendation**: Avoid feeding sensitive info; periodically review/delete state (`codey2 memory clear` or manual rm).

5. **Model Loading & Fine-Tuning**  
   - Loads external GGUF files; supports importing LoRA adapters from fine-tuning.  
   - **Risk**: Malicious/poisoned models/adapters could cause denial-of-service (OOM), unexpected behavior, or (theoretically) exploits if GGUF parsing has vulns.  
   - **Mitigations**: Models downloaded manually by user; no auto-download. Use trusted sources (Hugging Face official).  
   - **Recommendation**: Verify model hashes; run on isolated devices for testing untrusted adapters.

6. **General Android/Termux Risks**  
   - Runs with Termux permissions (storage, potentially network if tools expanded).  
   - **Risk**: Device-wide compromise if agent exploited (e.g., via generated malware code). Thermal/resource abuse possible on long runs.  
   - **Mitigations**: CPU-only inference; built-in thermal throttling (warnings + thread reduction). No root needed.  
   - **Recommendation**: Use on secondary/test device first; monitor battery/CPU with `top` or Android settings.

### Current Hardening Summary (v2.1.0+)
- Shell metacharacter blocking  
- Opt-in self-mod with checkpoints/git/rollback  
- Workspace/file boundary enforcement  
- Observability (`codey2 status`, health checks)  
- No network calls by default (fully local)  
- Audit report example in repo (`audit_report_2026-03-09_12-00-00.md`)

### Future Improvements (Help Wanted!)
- Encrypted memory/state storage  
- Runtime sandboxing (e.g., bubblewrap/seccomp on Linux, better Termux isolation)  
- Command confirmation prompts for more actions  
- Model signature/hash verification  
- Audit logs + anomaly detection

**Transparency is key** — the full source is open; feel free to audit, open issues, or submit PRs for hardening. If you spot vulnerabilities, report responsibly (DM or issue with security label). Contributions to security features are especially welcome!

**Use at your own risk.** This project is experimental — no warranties. Start small, monitor closely, and disable risky features until you're comfortable.

### 🔄 Persistent Daemon
- Runs continuously in the background
- Unix socket for instant CLI communication
- Graceful shutdown and hot-reload support
- State persists across restarts

### 🧠 Hierarchical Memory
- **Working Memory**: Currently edited files (evicted after task)
- **Project Memory**: Key files like CODEY.md (never evicted)
- **Long-term Memory**: Embeddings for semantic search
- **Episodic Memory**: Complete action history

### ⚡ Dual-Model Hot-Swap
- **Primary**: Qwen2.5-Coder-7B for complex tasks
- **Secondary**: Qwen2.5-1.5B for simple queries
- Automatic routing based on input complexity
- **LRU Cache**: SIGSTOP/SIGCONT for quick restart (reduces 2-3s swap delay)

### 📋 Internal Planning
- Native task queue with dependency tracking
- Automatic task breakdown for complex requests
- **Conversational Filters**: Q&A queries don't trigger unnecessary planning
- Strategy adaptation on failure
- Background task scheduling

### 🛡️ Self-Modification Safety
- Checkpoint before any core file modification
- Git integration for version control
- Rollback to any checkpoint
- Full file backup system

### 🔍 Observability
- `/status` command for full system state
- Health monitoring (CPU, memory, uptime)
- Token usage tracking
- Task queue visibility

### 🔥 Thermal Management
- Tracks continuous inference duration
- Warns after 5 minutes
- Reduces threads after 10 minutes
- Optimized for mobile devices (S24 Ultra)

### 🔄 Error Recovery
- Strategy switching on failures
- `write_file` fails → try `patch_file`
- Import error → suggest installation
- Test failure → debug with targeted fixes

### 🎯 Improved Reliability (v2.1.0)
- **JSON Parser**: Better escape sequence handling (`\n`, `\t`, `\"`, `\\`)
- **Hallucination Detection**: Past/future tense analysis reduces false positives
- **Context Budget**: 4000 token cap prevents context overflow on large projects

---

## Peer CLI Escalation

Codey can call external AI coding CLIs when it gets stuck or when you invoke them directly.

### Supported Peers

| CLI | Best For | Flag |
|-----|----------|------|
| `claude` (Claude Code) | Debugging, refactor, architecture, complex tasks | `-p` |
| `gemini` (Gemini CLI) | Explain, analysis, large context, review | `-p` |
| `qwen` (Qwen Code) | Generate, code completion, quick fixes | `-p` |

All peers run in non-interactive mode — output streams live to your terminal and is captured for Codey.

### Manual Escalation

```bash
# List available peer CLIs
/peer

# Call a specific peer
/peer claude debug this authentication bug
/peer gemini explain what this module does
/peer qwen write a hello world script

# Auto-pick best CLI for the task
/peer fix the broken import in utils.py
```

### Auto-Escalation

When Codey exhausts its retry budget on a task, it presents a confirmation prompt:

```
⚠  Codey hit max retries and needs help.
  Task:       fix the broken import in utils.py
  Suggest:    Claude Code (Anthropic)  (debugging task)
  Fallbacks:  gemini, qwen

  Your options:
    y / enter          Call Claude Code
    n                  Skip — return control to you
    gemini | qwen      Use that CLI instead
    <any text>         Tell Codey to try differently
```

### Crash Detection

On Android ARM64, some CLIs crash at startup due to missing native modules (e.g. `node-pty` prebuilds). Codey detects this automatically by running `check_cmd` at startup and inspecting stderr for crash signatures. Broken CLIs are excluded from the available list — no manual configuration needed.

---

## Voice Interface (v2.5.1)

Requires Termux:API app (Play Store / F-Droid) + `pkg install termux-api`.

```bash
/voice on              # Enable TTS + STT
/voice off             # Disable
/voice listen          # Speak one task, send to agent immediately
/voice rate 1.3        # Speed up speech (default 1.0)
/voice pitch 0.9       # Lower pitch
/voice speak hello     # Test TTS with a word
```

**In voice mode:**
- Every Codey response is spoken aloud (markdown/code stripped to prose)
- Press **Enter on a blank line** to speak your task via STT
- **Ctrl+C** interrupts speech mid-sentence
- Settings are saved across sessions in `~/.config/codey-v2/voice_config.json`

---

## Code Review (v2.5.2)

```bash
/review main.py        # Lint with all available tools
/review core/agent.py  # Shows errors/warnings, offers agent fix
```

**Auto-lint:** Every Python file Codey writes is automatically linted — issues are
fed back to the agent in the same turn so it can self-correct without you asking.

**Pre-write syntax gate:** If Codey generates Python with broken syntax, the write
is blocked and the error is returned as context so the agent can fix it first.

**Install linters for best results:**
```bash
pip install ruff          # Recommended: fastest, comprehensive
pip install flake8        # Classic alternative
pip install mypy          # Type checking
```

Override which linter is used: `CODEY_LINTER=flake8 python main.py`

---

## Git Enhancements (v2.5.5)

```bash
/git                       # Show status
/git branches              # List all branches (current highlighted)
/git branch feature-xyz    # Create and switch to new branch
/git checkout main         # Switch branch (confirmation prompt)
/git merge feature-xyz     # Merge with conflict detection
/git commit                # AI generates message from diff → you approve
/git commit "fix: typo"    # Commit with exact message
/git diff                  # Show current diff
/git push                  # Push to remote
/git conflicts             # List all conflicted files
```

**Smart commit messages:** When you run `/git commit` without a message, Codey reads the current
diff and generates a commit message using the model. If your project already uses
[conventional commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` etc.)
it will match that format automatically. You see the suggested message and can accept or
type a replacement before anything is committed.

**Conflict resolution flow:** After a merge with conflicts, Codey lists the conflicted files
and asks if you want it to resolve them. It parses both sides of each conflict and runs the
agent with full context to propose a resolution, which you review before it is written.

---

## Quick Start

### One-Line Installation

```bash
./install.sh
```

This single command installs everything:
- Python dependencies
- llama.cpp binary
- Both models (7B primary + 1.5B secondary)
- PATH configuration

After installation, restart your terminal and run:

```bash
codeyd2 start              # Start the daemon
codey2 "create hello.py"   # Send your first task
codey2 status              # Check status anytime
```

### Manual Installation

If you prefer to install components separately, follow these steps:

## Requirements

| Requirement | Specification |
|-------------|---------------|
| **OS** | Termux on Android (or Linux) |
| **RAM** | 6GB+ available (dual-model support) |
| **Storage** | ~10GB (7B model + 1.5B model + Codey) |
| **Python** | 3.12+ |
| **Packages** | `rich`, `sentence-transformers`, `numpy`, `watchdog` |

---

## Installation (Manual)

### Step 1: Install Dependencies

```bash
pkg install cmake ninja clang python
pip install rich sentence-transformers numpy watchdog
```

### Step 2: Install llama.cpp

```bash
git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DLLAMA_CURL=OFF
cmake --build build --config Release -j4
```

### Step 3: Download Models

```bash
# Primary model (7B) - ~4.7GB
mkdir -p ~/models/qwen2.5-coder-7b
cd ~/models/qwen2.5-coder-7b
wget https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf

# Secondary model (1.5B) - ~2GB
mkdir -p ~/models/qwen2.5-1.5b
cd ~/models/qwen2.5-1.5b
wget https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q8_0.gguf
```

### Step 4: Clone Codey-v2

```bash
git clone https://github.com/Ishabdullah/Codey.git ~/codey-v2
cd ~/codey-v2
chmod +x codey2 codeyd2
```

### Step 5: Add to PATH

```bash
# Add to your shell config
echo 'export PATH="$HOME/codey-v2:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Or run the setup script
./setup.sh
```

### Step 6: Verify Installation

```bash
codey2 --version
codeyd2 status
```

---

## Commands

### Daemon Management (`codeyd2`)

| Command | Description |
|---------|-------------|
| `codeyd2 start` | Start the daemon in background |
| `codeyd2 stop` | Stop the running daemon |
| `codeyd2 status` | Show daemon status |
| `codeyd2 restart` | Restart the daemon |
| `codeyd2 reload` | Send reload signal (SIGUSR1) |
| `codeyd2 config` | Create default config file |

### CLI Client (`codey2`)

| Command | Description |
|---------|-------------|
| `codey2 "prompt"` | Send a task to the daemon |
| `codey2 status` | Show full daemon status |
| `codey2 task list` | List recent tasks |
| `codey2 task <id>` | Get details of a specific task |
| `codey2 cancel <id>` | Cancel a pending/running task |
| `codey2 --daemon` | Run in foreground daemon mode |

### CLI Flags

| Flag | Description |
|------|-------------|
| `--yolo` | Skip all confirmations |
| `--allow-self-mod` | Enable self-modification (with checkpoint enforcement) |
| `--threads N` | Override thread count |
| `--ctx N` | Override context window size |
| `--read <file>` | Pre-load file into context |
| `--init` | Generate CODEY.md and exit |
| `--fix <file>` | Run file, auto-fix any errors |
| `--tdd <file>` | TDD mode with test file |
| `--no-resume` | Start fresh (ignore saved session) |
| `--plan` | Enable plan mode for complex tasks |
| `--no-plan` | Disable orchestration/planning |

### In-Session Commands

| Command | Description |
|---------|-------------|
| `/review <file.py>` | Lint file with all available tools + optional agent fix (v2.5.2) |
| `/voice` | Show voice status and sub-commands (v2.5.1) |
| `/voice on` / `/voice off` | Enable/disable TTS+STT voice mode |
| `/voice listen` | One-shot voice input → send to agent |
| `/voice rate <n>` | Set TTS speech speed (default 1.0) |
| `/peer` | List available peer CLIs |
| `/peer <name> <task>` | Call a specific peer CLI directly |
| `/peer <task>` | Auto-pick best peer CLI for the task |
| `/learning` | Show learning system status |
| `/read <file>` | Load file into context |
| `/diff [file]` | Show what Codey changed |
| `/undo [file]` | Restore file to previous version |
| `/git` | Git status |
| `/git branches` | List all branches (current highlighted) (v2.5.5) |
| `/git branch <name>` | Create and switch to new branch (v2.5.5) |
| `/git checkout <name>` | Switch branch with confirmation (v2.5.5) |
| `/git merge <branch>` | Merge with conflict detection + resolution (v2.5.5) |
| `/git commit` | AI-generated commit message from diff (v2.5.5) |
| `/git commit <msg>` | Commit with exact message |
| `/git conflicts` | List conflicted files (v2.5.5) |
| `/git diff` | Show current diff |
| `/git push` | Push to remote |
| `/search <pattern>` | Grep across project files |
| `/context` | Show loaded files |
| `/clear` | Clear history and session |
| `/exit` | Save session and quit |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ALLOW_SELF_MOD=1` | Enable self-modification (alternative to `--allow-self-mod`) |
| `CODEY_MODEL` | Override model path |
| `CODEY_THREADS` | Override thread count |
| `CODEY_LINTER` | Override linter: `ruff`, `flake8`, `mypy` (v2.5.2) |

---

## Usage Examples

### Simple Query (uses 1.5B model)
```bash
./codey2 "What is 2+2?"
```

### Complex Task (uses 7B model)
```bash
./codey2 "Create a REST API with user authentication and JWT tokens"
```

### Check Daemon Health
```bash
./codey2 status
```

Output:
```
==================================================
Codey-v2 Status
==================================================

Version:  2.0.0
PID:      12345
Uptime:   3600s

Model:
  Active:       primary
  Temperature:  0.2
  Context:      4096

Tasks:
  Pending:  0
  Running:  0

Memory:
  RSS:        45.2 MB
  Files:      3

Health:
  CPU:        2.5%
  Model:      Loaded

==================================================
```

### List Tasks
```bash
./codey2 task list
```

Output:
```
Tasks:
  [5] ✓ Create Flask hello world app
  [4] ✓ Set up project structure
  [3] ✓ Write tests
  [2] ○ Running: Install dependencies
  [1] ○ Pending: Create requirements.txt
```

### Cancel a Task
```bash
./codey2 cancel 2
```

---

## Fine-tuning (v2.3.0)

Codey-v2 supports personalizing the underlying model using your interaction data.
Heavy training happens off-device (Google Colab free tier), while your phone only
handles lightweight data export and file management.

### Step 1: Export Your Data

```bash
# Export last 30 days with default quality threshold
codey2 --finetune

# Customize export
codey2 --finetune --ft-days 60 --ft-quality 0.6 --ft-model 7b
```

**Options:**
| Flag | Default | Description |
|------|---------|-------------|
| `--ft-days` | 30 | Days of history to include |
| `--ft-quality` | 0.7 | Minimum quality (0.0-1.0) |
| `--ft-model` | both | Model variant: `1.5b`, `7b`, or `both` |
| `--ft-output` | ~/Downloads/codey-finetune | Output directory |

**Output:**
- `codey-finetune-1.5b.jsonl` - Dataset for 1.5B model
- `codey-finetune-7b.jsonl` - Dataset for 7B model
- `codey-finetune-qwen-coder-1.5b.ipynb` - Colab notebook
- `codey-finetune-qwen-coder-7b.ipynb` - Colab notebook

### Step 2: Train on Colab

1. Go to https://colab.research.google.com
2. Upload the generated notebook (`codey-finetune-*.ipynb`)
3. Run all cells (takes 1-4 hours on free T4)
4. Download the `codey-lora-adapter.zip` when complete

**Note:** Training uses Unsloth for 2x speed and 70% less VRAM.

### Step 3: Import Adapter

```bash
# Extract the downloaded adapter
unzip codey-lora-adapter.zip

# Import to Codey-v2
codey2 --import-lora /path/to/codey-lora-adapter --lora-model primary
```

**Options:**
| Flag | Default | Description |
|------|---------|-------------|
| `--lora-model` | primary | `primary` (7B) or `secondary` (1.5B) |
| `--lora-quant` | q4_0 | Quantization: `q4_0`, `q5_0`, `q8_0`, `f16` |
| `--lora-merge` | false | Merge on-device (requires llama.cpp) |

### Merging Adapters (Advanced)

If you have llama.cpp installed and want to merge on-device:

```bash
# Merge adapter with base model (requires ~8GB RAM for 7B)
codey2 --import-lora /path/to/adapter --lora-model primary --lora-merge

# Or manually with llama.cpp:
python ~/llama.cpp/convert-lora.py \
  --base-model ~/models/qwen2.5-coder-7b/model.gguf \
  --lora-adapter /path/to/adapter \
  --output merged.gguf

./quantize merged.gguf merged-q4.gguf q4_0
```

### Rollback

If the fine-tuned model performs worse:

```bash
# Backup is created automatically before import
# Restore original model
codey2 --rollback --lora-model primary
```

### Quality Tips

- **Higher `--ft-quality`** (0.8+): Only best examples, smaller dataset
- **Lower `--ft-quality`** (0.5-0.6): More examples, noisier training
- **More `--ft-days`**: More diverse data, longer training
- **1.5B model**: Faster training (~1 hour), good for style adaptation
- **7B model**: Better reasoning (~4 hours), handles complex tasks

---

## Configuration

### Default Config Location
`~/.codey-v2/config.json`

### Create Default Config
```bash
./codeyd2 config
```

### Configuration Options

```json
{
  "daemon": {
    "pid_file": "~/.codey-v2/codey-v2.pid",
    "socket_file": "~/.codey-v2/codey-v2.sock",
    "log_file": "~/.codey-v2/codey-v2.log",
    "log_level": "INFO"
  },
  "tasks": {
    "max_concurrent": 1,
    "task_timeout": 1800,
    "max_retries": 3
  },
  "health": {
    "check_interval": 60,
    "max_memory_mb": 1500,
    "stuck_task_threshold": 1800
  },
  "state": {
    "db_path": "~/.codey-v2/state.db",
    "cleanup_old_actions_hours": 24
  }
}
```

### Model Configuration

Edit `~/codey-v2/utils/config.py`:

```python
MODEL_CONFIG = {
    "n_ctx":          8192,      # Context window (doubled in v2.6.0)
    "n_threads":      4,         # CPU threads
    "n_gpu_layers":   0,         # GPU offload (0 = CPU only)
    "temperature":    0.2,       # Lower = more deterministic
    "max_tokens":     2048,      # Max response length (doubled in v2.6.0)
    "repeat_penalty": 1.1,
}

ROUTER_CONFIG = {
    "simple_max_chars": 50,      # Under this → 1.5B model
    "simple_keywords": ["hello", "hi", "thanks", "bye"],
    "swap_cooldown_sec": 30,     # Cooldown before swapping
}

THERMAL_CONFIG = {
    "enabled": True,
    "warn_after_sec": 300,       # 5 min → warning
    "reduce_threads_after_sec": 600,  # 10 min → reduce threads
}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   CLI Client (codey2)                   │
│  ── User commands, flags, task queries, /status         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   Daemon Core (codeyd2)                 │
│  ── Main event loop (asyncio)                           │
│  ── Signal handlers (SIGTERM, SIGUSR1)                  │
│  ── Unix socket listener                                │
└─────────────────────────────────────────────────────────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    ▼                     ▼                     ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   Planner        │ │   Memory         │ │   Tools          │
│   • Task queue   │ │   • Working      │ │   • Filesystem   │
│   • Dependencies │ │   • Project      │ │   • Shell        │
│   • Adaptation   │ │   • Long-term    │ │   • Search       │
│   • Background   │ │   • Episodic     │ │                  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   LLM Layer                             │
│  ── Model router (7B ↔ 1.5B hot-swap)                  │
│  ── Chat completions backend (v2.6.0):                  │
│     • /v1/chat/completions with proper ChatML           │
│     • llama-server applies model's chat template        │
│     • HTTP fallback for legacy compatibility            │
│  ── Thermal management                                  │
│  ── 8K context window, 2048 max response tokens         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   State Store (SQLite)                  │
│  ── Persistent memory, task queue, episodic log         │
│  ── Model state, embeddings, checkpoints                │
└─────────────────────────────────────────────────────────┘
```

---

## Memory System

### Four-Tier Architecture

```
┌─────────────────────────────────────────┐
│  Working Memory (in-memory, evicted)    │
│  - Currently edited files               │
│  - Fast access, token-limited           │
│  - Cleared after task completes         │
└─────────────────────────────────────────┘
              │
┌─────────────────────────────────────────┐
│  Project Memory (persistent)            │
│  - Key files: CODEY.md, README.md       │
│  - Never evicted                        │
│  - Loaded at daemon start               │
└─────────────────────────────────────────┘
              │
┌─────────────────────────────────────────┐
│  Long-term Memory (embeddings)          │
│  - sentence-transformers (all-MiniLM)   │
│  - Semantic search via similarity       │
│  - Stored in SQLite                     │
└─────────────────────────────────────────┘
              │
┌─────────────────────────────────────────┐
│  Episodic Memory (action log)           │
│  - Append-only log of all actions       │
│  - "What did I do last week?"           │
│  - SQLite via state store               │
└─────────────────────────────────────────┘
```

### Using Memory

```python
from core.memory_v2 import get_memory

memory = get_memory()

# Working memory (temporary)
memory.add_to_working("file.py", content, tokens)
memory.clear_working()  # After task

# Project memory (persistent)
memory.add_to_project("CODEY.md", content, is_protected=True)

# Long-term memory (semantic search)
memory.store_in_longterm("file.py", content)
results = memory.search("find authentication code", limit=5)

# Episodic memory (log)
memory.log_action("file_modified", "auth.py")
```

---

## Error Recovery

### Strategy Switching

Instead of fixed retries, Codey adapts its approach on failure:

| Error Type | Fallback Strategy | Confidence |
|------------|-------------------|------------|
| `write_file` fails | Try `patch_file` | 0.9 |
| File not found | Create file first | 0.95 |
| Shell command fails | Search for solution | 0.8 |
| Import error | Install package | 0.9 |
| Syntax error | Fix syntax | 0.85 |
| Test failure | Debug test | 0.85 |
| Permission error | Fix permissions | 0.85 |

### Example

```
Error: "Failed to write file: permission denied"
→ Recovery: Trying "use_patch" - Use patch instead of full write
```

---

## Thermal Management

Codey-v2 is optimized for mobile devices:

| Threshold | Action |
|-----------|--------|
| 5 min continuous inference | Log warning |
| 10 min continuous inference | Reduce threads (4→2) |
| Cooldown period | Restore original threads |

### Check Thermal Status

```bash
./codey2 status
```

Output includes:
```
Health:
  CPU:        2.5%
  Model:      Loaded
  Throttled:  No
```

---

## Self-Modification Safety

### Checkpoints

Before modifying any core file, Codey creates a checkpoint:

```bash
# Create checkpoint
from core.checkpoint import create_checkpoint
cp_id = create_checkpoint("Adding new feature")

# List checkpoints
from core.checkpoint import list_checkpoints
cps = list_checkpoints(limit=10)

# Rollback
from core.checkpoint import rollback
rollback(cp_id)
```

### Checkpoint Structure

```
~/.codey-v2/checkpoints/
├── 1772934678/          # Timestamp ID
│   ├── core/
│   │   ├── agent.py
│   │   ├── daemon.py
│   │   └── ...
│   ├── tools/
│   │   └── ...
│   └── main.py
└── 1772934700/
    └── ...
```

---

## Project Structure

```
~/codey-v2/
├── codey2                  # CLI client script
├── codeyd2                 # Daemon manager script
├── main.py                 # Main entrypoint
├── codey-v2.md             # This implementation plan
├── core/
│   ├── daemon.py           # Daemon core with socket server
│   ├── daemon_config.py    # Configuration manager
│   ├── state.py            # SQLite state store
│   ├── task_executor.py    # Task execution with recovery
│   ├── planner_v2.py       # Internal task planner
│   ├── background.py       # Background tasks & file watches
│   ├── filesystem.py       # Direct filesystem access
│   ├── memory_v2.py        # Four-tier memory system
│   ├── embeddings.py       # Sentence-transformers integration
│   ├── router.py           # Model routing heuristic
│   ├── loader_v2.py        # Model loading/hot-swap
│   ├── inference_v2.py     # Chat completions inference (v2.6.0)
│   ├── inference_hybrid.py # Chat completions backend (v2.6.0)
│   ├── checkpoint.py       # Self-modification safety
│   ├── observability.py    # Self-state queries
│   ├── recovery.py         # Error recovery strategies
│   ├── thermal.py          # Thermal management
│   ├── peer_cli.py         # Peer CLI escalation manager (v2.5.0)
│   ├── peer_shell.py       # PTY/subprocess runners for peer CLIs (v2.5.0)
│   ├── learning.py         # Learning system coordinator (v2.2.0+)
│   ├── preferences.py      # User preference learning & NL detection (v2.5.0)
│   ├── voice.py            # TTS + STT via Termux:API (v2.5.1)
│   ├── linter.py           # Static analysis: ruff/flake8/mypy/ast (v2.5.2)
│   └── githelper.py        # Git: branches, merge, conflict detection, smart commits (v2.5.5)
├── tools/
│   └── file_tools.py       # Refactored file operations
├── utils/
│   ├── config.py           # All configuration
│   └── logger.py           # Logging with levels
└── prompts/
    └── system_prompt.py    # System prompt
```

---

## API Reference

### Daemon Functions

```python
from core.daemon import daemon_status, daemon_health, daemon_ping

# Check if daemon is running
status = daemon_status()

# Get health metrics
health = daemon_health()

# Ping daemon
pong = daemon_ping()
```

### State Store

```python
from core.state import get_state_store

state = get_state_store()

# Key-value operations
state.set("key", "value")
value = state.get("key")
state.delete("key")

# Task operations
task_id = state.add_task("description")
state.start_task(task_id)
state.complete_task(task_id, "result")
state.fail_task(task_id, "error")

# Episodic log
state.log_action("action", "details")
actions = state.get_recent_actions(limit=50)
```

### Planner

```python
from core.planner_v2 import get_planner

planner = get_planner()

# Add tasks
task_id = planner.add_task("Build a REST API")
task_ids = planner.add_tasks([
    "Set up project structure",
    "Create main application",
    "Write tests",
])

# Get next ready task
task = planner.get_next_task()

# Break down complex task
subtasks = planner.breakdown_complex_task("Build a Flask app")

# Adapt on failure
alternative = planner.adapt(task_id, "Permission denied")
```

### Observability

```python
from core.observability import get_state

state = get_state()

# Query properties
tokens = state.tokens_used
memory = state.memory_loaded
pending = state.tasks_pending
model = state.model_active
temp = state.temperature

# Full status
status = state.get_full_status()
```

---

## Performance

### Model Performance

| Metric | Value |
|--------|-------|
| **Primary Model** | Qwen2.5-Coder-7B-Instruct Q4_K_M |
| **Secondary Model** | Qwen2.5-1.5B-Instruct Q8_0 |
| **RAM Usage (idle)** | ~200MB |
| **RAM Usage (7B)** | ~4.4GB |
| **RAM Usage (1.5B)** | ~1.2GB |
| **Context Window** | 8192 tokens |
| **Threads** | 4 (reducible to 2) |
| **Speed (7B)** | ~7-8 t/s |
| **Speed (1.5B)** | ~20-25 t/s |
| **Hot-swap Delay** | 2-3 seconds (LRU cached) |

### Backend Latency (v2.6.0)

| Backend | Overhead per Call | Availability |
|---------|-------------------|--------------|
| **Chat completions** | ~400-600ms | Default — `/v1/chat/completions` with ChatML |
| **HTTP fallback** | ~400-600ms | Legacy `core/inference.py` on port 8081 |

**Note:** Actual latency depends on prompt length, model size, and device thermal state. The v2.6.0 simplified backend removed direct binding and Unix socket backends that never worked reliably on Termux.

---

## Troubleshooting

### Daemon Won't Start

```bash
# Check for stale PID file
rm -f ~/.codey-v2/codey-v2.pid

# Check logs
cat ~/.codey-v2/codey-v2.log

# Restart
./codeyd2 restart
```

### Socket Connection Failed

```bash
# Verify daemon is running
./codeyd2 status

# Check socket exists
ls -la ~/.codey-v2/codey-v2.sock
```

### Model Not Found

```bash
# Verify model paths
ls -la ~/models/qwen2.5-coder-7b/
ls -la ~/models/qwen2.5-1.5b/
```

### High Memory Usage

```bash
# Check status
./codey2 status

# Restart daemon (clears working memory)
./codeyd2 restart
```

---

## Known Limitations

### Platform Constraints

| Limitation | Impact | Workaround / Status |
|------------|--------|---------------------|
| **HTTP API overhead** | ~400-600ms per inference call via `/v1/chat/completions` | Simplified in v2.6.0 — single reliable backend instead of three unreliable ones |
| **File watches require `watchdog`** | Background file monitoring disabled if not installed | Install with `pip install watchdog` (optional) |
| **No NPU acceleration** | CPU-only inference (~3-5 t/s at 4 threads) | Thermal management prevents throttling |
| **Single-device only** | State not synced across devices | Intentional design for local-only privacy |
| **Peer CLIs with node-pty** | CLIs that bundle native node-pty module (e.g. GitHub Copilot standalone) crash on Android ARM64 — no prebuilt `pty.node` for this platform | Auto-detected and excluded at startup; Claude Code, Gemini CLI, and Qwen Code all work via `-p` non-interactive mode |

### Technical Notes (v2.6.0)

**Chat Completions Backend:**
- Uses `/v1/chat/completions` endpoint exclusively — llama-server applies the model's ChatML template automatically
- Previous versions (v2.4.0) used `/completion` with manual prompt formatting, bypassing ChatML — this was the root cause of most instruction-following failures
- Simplified from 3 backends (direct binding, Unix socket, TCP HTTP) to 1 reliable backend
- Falls back to legacy HTTP backend (`core/inference.py`) if chat completions unavailable

**Context & Token Budget (v2.6.0):**
- Context window doubled from 4096 → 8192 tokens
- Max response tokens doubled from 1024 → 2048 (complete files no longer truncated)
- Memory budgets recalculated: system 500, summary 400, files 1600, turns 1000, message 400, response 2048
- Subtask orchestrator now injects file contents between steps (step 2 sees what step 1 wrote)

**Migration Notes (v2.5.x → v2.6.0):**
- No breaking changes to CLI interface
- `core/inference_hybrid.py` completely rewritten (764→160 lines)
- System prompt trimmed from 50→22 lines; domain guidance moved to contextual injection
- Result validation added to orchestrator (catches false success claims)

---

## Version History

| Version | Highlights |
|---------|------------|
| **v2.6.0** | **Inference Pipeline Rewrite** — Fixed ChatML prompt formatting (root cause of ~70% failures); `/v1/chat/completions` with proper message arrays; context window 4K→8K, max_tokens 1024→2048; subtask file context passing; result validation catches false success claims; system prompt trimmed 50→22 lines with contextual domain guidance injection; simplified inference stack from 3 backends to 1 |
| **v2.5.5** | **Git Enhancements** — Branch management (`/git branches/branch/checkout/merge`); AI-generated commit messages with conventional commits detection; merge conflict detection, parsing, and agent-assisted resolution; `/git commit` interactive approve flow; `/git diff` and `/git conflicts` commands |
| **v2.5.4** | **Peer delegation + QA classifier fixes** — "ask gemini/claude/qwen to X" now actually calls that peer CLI and applies the result; added "replace", "rename", "change", "ask", "call" etc to action keywords (fixes "could you replace" being classified as QA); `enrich_message` patch_file hints now include replace/rename/append |
| **v2.5.3** | **Bug fixes** — Agent loop after simple writes fixed: added `\nUser:` / `\nHuman:` / `\nA:` stop sequences to MODEL_CONFIG + HALLUCINATION_MARKERS; fixed `extra_stop` tokens (e.g. `</tool>`) never reaching llama-server (now passed through `server.infer(stop=...)`); auto-lint only injects errors to agent context (warnings go to terminal only, preventing unused-import loop); CPU monitor fixed with 250ms self-contained mini-sample when delta is near-zero |
| **v2.5.2** | **Static Analysis & Code Review** — Auto-lint after every Python write; pre-write syntax gate blocks broken files; `/review <file>` multi-linter scan (ruff/flake8/mypy) with agent fix; `core/linter.py` |
| **v2.5.1** | **Voice Interface** — TTS via `termux-tts-speak`, STT via `termux-speech-to-text`; `/voice on/off/listen/rate/pitch`; blank-Enter triggers voice input in REPL; settings persist across sessions; `core/voice.py` |
| **v2.5.0** | **Peer CLI Escalation** - Auto-escalate to Claude Code, Gemini CLI, Qwen CLI on retry exhaustion; `/peer` command for manual escalation; crash detection for Android ARM64 native module issues; enhanced learning with NL preference extraction, expanded categories, CODEY.md sync; self-review fix auto-loads own source files |
| **v2.4.0** | **Hybrid Inference Backend** - Direct llama-cpp-python + Unix socket HTTP + TCP HTTP fallback; accurate architecture diagram; documented Termux constraints |
| **v2.3.0** | **Fine-tuning Support** - Export interaction data, Unsloth Colab notebooks, LoRA adapter import, off-device training workflow |
| **v2.2.0** | **Machine Learning** - User preference learning, error pattern database, strategy effectiveness tracking, adaptive behavior |
| **v2.1.0** | **Security & Reliability Hardening** - Shell injection prevention, self-mod opt-in, LRU model cache, JSON parser improvements, hallucination detection, orchestration filters, context budget |
| **v2.0.0** | **Complete 7-phase implementation** - Daemon, Memory, Dual-Model, Planner, Checkpoints, Observability, Recovery |
| v1.0.0 | Original Codey - Session-based CLI with ReAct agent |

---

## Testing

Codey-v2 includes a comprehensive test suite:

```bash
# Run all tests
pytest tests/ -v

# Run security tests
pytest tests/security/ -v

# Run specific test modules
pytest tests/test_shell_injection.py -v
pytest tests/test_hallucination.py -v
pytest tests/test_orchestration.py -v
pytest tests/test_json_parser.py -v
pytest tests/test_self_modification.py -v
```

### Test Coverage

| Module | Tests | Coverage |
|--------|-------|----------|
| Shell Injection | 16 | Command validation, metacharacter blocking |
| Self-Modification | 8 | Opt-in enforcement, checkpoint creation |
| JSON Parser | 16 | Escape handling, malformed input recovery |
| Hallucination Detection | 18 | Past/future tense analysis |
| Orchestration | 24 | Conversational filters, complexity heuristics |
| **Learning Systems** | **25** | **Preferences, error database, strategy tracking** |

---

## License

MIT License - See LICENSE file for details.

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

---

## Acknowledgments

- [llama.cpp](https://github.com/ggerganov/llama.cpp) for efficient LLM inference
- [Qwen](https://huggingface.co/Qwen) for the excellent code models
- [sentence-transformers](https://github.com/UKPLab/sentence-transformers) for embeddings
