# Security

Codey-v2 is a persistent, autonomous coding agent that runs as a background daemon, executes shell commands, maintains long-term memory, and loads local LLMs. These capabilities make it powerful but introduce non-trivial risks compared to a simple chat tool.

**This is early-stage open-source software. Use with caution on devices with sensitive data. Always review generated code and commands before execution.**

---

## Key Risks and Mitigations

### 1. Persistent Daemon

The daemon runs continuously with a Unix socket (`~/.codey-v2/codey-v2.sock`) for IPC.

**Risk:** If the socket has permissive permissions or is in a shared location, unauthorized local processes could send commands.

**Mitigations:**
- Socket created with `0600` permissions (owner-only read/write).
- Daemon runs under your Termux/Linux user — no root required.

**Recommendation:** Stop the daemon when not in use (`codeyd2 stop`). Only run on trusted, single-user devices.

---

### 2. Shell Command Execution

Tools can execute shell commands based on agent decisions.

**Risk:** Prompt injection or hallucinated output could lead to unintended commands (`rm -rf`, data exfiltration, etc.).

**Mitigations:**
- All shell commands (including compound commands with `&&`, `|`, `;`, etc.) require explicit user confirmation before running. Dangerous commands (`rm`, `curl`, `wget`, `chmod`, etc.) receive an additional warning before the prompt.
- YOLO mode (`--yolo`) disables confirmation prompts — use only in trusted, non-interactive contexts.
- Commands run in user context only — no privilege escalation.
- Shell timeout defaults to **30 minutes (1800 s)** to support long builds; configurable per-call.
- Daemon mode blocks commands not in an explicit allowlist (`core/task_executor.py`).

**Recommendation:** Review `--plan` output before execution. Use `--no-execute` for dry runs.

---

### 3. Self-Modification

Opt-in feature that allows the agent to patch its own code and files.

**Risk:** If enabled and manipulated via clever prompts, it could introduce backdoors, delete data, or persist damage.

**Mitigations:**
- Requires explicit `--allow-self-mod` flag **or** `ALLOW_SELF_MOD=1` env var.
- Auto-creates checkpoints and full backups before any core file change.
- Git integration for versioning and rollback.
- Workspace boundary enforcement: files outside the workspace are blocked unless self-mod is active.

**Recommendation:** Keep disabled by default. Enable only for intentional experimentation. Review diffs and checkpoints immediately after any modification.

---

### 4. Memory and State Persistence

Hierarchical memory stored in SQLite (`~/.codey-v2/`).

**Risk:** Sensitive code snippets or personal data could be stored and leaked if the device is compromised or backups are mishandled.

**Mitigations:**
- Data stored in Termux app-private directories.
- No unsolicited network calls. Exception: peer CLI escalation (Claude Code, Gemini CLI, Qwen CLI) can send local file contents to external LLMs when triggered — requires explicit user confirmation before any files are shared (see [Peer CLI Escalation](../README.md#peer-cli-escalation)).
- Encryption is not yet implemented (planned).

**Recommendation:** Avoid feeding sensitive information (API keys, passwords) to the agent. Periodically review or clear state:
- **In-chat:** type `/clear` to wipe history, context, undo history, and saved session
- **CLI flag:** `codey2 --clear-session` to clear the saved session before starting
- **Manual:** `rm -f ~/.codey_sessions/*.json` to delete all saved sessions

---

### 5. Model Loading and Fine-tuning

Loads external GGUF files; supports importing LoRA adapters.

**Risk:** Malicious or poisoned model files could cause unexpected behavior or OOM crashes.

**Mitigations:**
- Models are downloaded manually — no auto-download.
- LoRA import creates a full backup before modifying the active model.

**Recommendation:** Only use models from trusted sources (Hugging Face official repos). Verify file hashes when possible. Test untrusted adapters on an isolated device.

---

### 6. Android / Termux Constraints

Runs with Termux permissions (storage, potentially network if tools are expanded).

**Risk:** Long inference sessions can cause thermal stress or battery drain.

**Mitigations:**
- CPU-only inference — no GPU or NPU access.
- Built-in thermal management: warning at 5 minutes, thread reduction at 10 minutes.
- Adaptive recursion depth based on device temperature and battery level.

**Recommendation:** Monitor device temperature and battery. Use `codeyd2 status` to check thermal state.

---

## Current Hardening Summary

- User confirmation required for all shell commands; dangerous commands receive an explicit warning
- Opt-in self-modification with mandatory checkpoints
- Workspace and file boundary enforcement
- Socket permissions locked to owner-only (`0600`)
- Fully local — no network calls by default
- Thermal throttling prevents sustained CPU abuse
- Daemon mode shell allowlist (explicit prefix-based)

---

## Planned Improvements

- Encrypted memory and state storage
- Runtime sandboxing (bubblewrap / seccomp on Linux)
- Model file hash verification
- Audit logs and anomaly detection

---

## Reporting Vulnerabilities

The full source is open. If you find a vulnerability, please report it responsibly — open a GitHub issue with the `security` label or DM the maintainer. Contributions to security features are especially welcome.

**Use at your own risk.** This project is experimental and carries no warranties. Start small, monitor closely, and disable risky features until you are comfortable.
