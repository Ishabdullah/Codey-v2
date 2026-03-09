# Codey-v2

**A persistent, daemon-like AI agent that lives on your device.**

Codey-v2 transforms Codey-v2 from a session-based CLI tool into a continuous AI agent—maintaining state, managing background tasks, and adapting to work without constant supervision. All while running locally on your Android device with dual-model hot-swap for thermal and memory efficiency.

```
  ██████╗ ██████╗ ██████╗ ███████╗██╗   ██╗
 ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗ ██╔╝
 ██║     ██║   ██║██║  ██║█████╗   ╚████╔╝
 ██║     ██║   ██║██║  ██║██╔══╝    ╚██╔╝
 ╚██████╗╚██████╔╝██████╔╝███████╗   ██║
  ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝
  v2.0.0 · Persistent AI Agent · Termux
```

---

## Key Features

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
- 30-second cooldown to prevent thrashing

### 📋 Internal Planning
- Native task queue with dependency tracking
- Automatic task breakdown for complex requests
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
    "n_ctx":          4096,      # Context window
    "n_threads":      4,         # CPU threads
    "n_gpu_layers":   0,         # GPU offload (0 = CPU only)
    "temperature":    0.2,       # Lower = more deterministic
    "max_tokens":     1024,      # Max response length
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
│  ── Direct llama.cpp binding                            │
│  ── Thermal management                                  │
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
│   ├── inference_v2.py     # Dual-model inference
│   ├── checkpoint.py       # Self-modification safety
│   ├── observability.py    # Self-state queries
│   ├── recovery.py         # Error recovery strategies
│   └── thermal.py          # Thermal management
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

| Metric | Value |
|--------|-------|
| **Primary Model** | Qwen2.5-Coder-7B-Instruct Q4_K_M |
| **Secondary Model** | Qwen2.5-1.5B-Instruct Q8_0 |
| **RAM Usage (idle)** | ~200MB |
| **RAM Usage (7B)** | ~4.4GB |
| **RAM Usage (1.5B)** | ~1.2GB |
| **Context Window** | 4096 tokens |
| **Threads** | 4 (reducible to 2) |
| **Speed (7B)** | ~7-8 t/s |
| **Speed (1.5B)** | ~20-25 t/s |
| **Hot-swap Delay** | 2-3 seconds |

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

## Version History

| Version | Highlights |
|---------|------------|
| **v2.0.0** | **Complete 7-phase implementation** - Daemon, Memory, Dual-Model, Planner, Checkpoints, Observability, Recovery |
| v1.0.0 | Original Codey - Session-based CLI with ReAct agent |

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
