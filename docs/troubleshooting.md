# Troubleshooting

## Common Issues

### Daemon won't start

```bash
# Remove a stale PID file left by a crash
rm -f ~/.codey-v2/codey-v2.pid

# Check the log for the actual error
cat ~/.codey-v2/codey-v2.log

# Restart cleanly
codeyd2 restart
```

### Socket connection failed

```bash
# Confirm the daemon is running
codeyd2 status

# Confirm the socket exists with correct permissions
ls -la ~/.codey-v2/codey-v2.sock
# Expected: srw------- (0600, owner only)
```

### Model not found

```bash
ls -la ~/models/qwen2.5-coder-7b/
ls -la ~/models/qwen2.5-0.5b/
ls -la ~/models/nomic-embed/
```

Check that the filenames match the paths in `utils/config.py`, or set `CODEY_MODEL`, `CODEY_PLANNER_MODEL`, and `CODEY_EMBED_MODEL` environment variables to the correct paths.

### High memory usage

```bash
codeyd2 status   # Check RAM and task queue

codeyd2 restart  # Clears working memory
```

If the 7B model alone is using more than ~5 GB, verify that `CODEY_7B_MMAP=1` is set (default). Memory-mapped weights only load touched pages into RAM.

### Planner / summarizer not responding

The 0.5B model on port 8081 may have failed to start or crashed.

```bash
cat ~/.codey-v2/plannd.log        # Check planner log
cat ~/.codey-v2/plannd-llama.log  # Check llama-server log

codeyd2 restart                   # Restart all daemons
```

If port 8081 is unreachable, task planning falls back to heuristic decomposition and context compression skips the micro-summary step. The agent continues working normally.

### Peer CLI crashes on startup

On Android ARM64, some CLIs bundle native Node.js modules (e.g., `node-pty`) that have no ARM64 prebuilt. Codey detects this automatically at startup and excludes broken CLIs from the available list. No manual configuration is needed.

To check which peers are available:

```bash
codey2   # then type /peer
```

---

## Performance Reference

| Metric | Value |
|--------|-------|
| Primary model | Qwen2.5-Coder-7B-Instruct Q4_K_M |
| Planner / summarizer | Qwen2.5-0.5B-Instruct Q8_0 |
| Embedding model | nomic-embed-text-v1.5 Q4_K_M |
| RAM (idle) | ~200 MB |
| RAM (7B loaded) | ~4.4 GB |
| RAM (0.5B loaded) | ~400 MB |
| RAM (embed loaded) | ~80 MB |
| Context window | 32,768 tokens |
| Max response tokens | 2,048 |
| Speed — 7B | ~7–8 t/s |
| Speed — 0.5B | ~40–60 t/s |
| Inference backend | `/v1/chat/completions` over localhost HTTP |
| Backend overhead | ~400–600 ms per call |

---

## Known Limitations

| Limitation | Impact | Status |
|------------|--------|--------|
| HTTP API overhead | ~400–600 ms per inference call | Single reliable HTTP backend; direct socket path not available on Android |
| CPU-only inference | ~7–8 t/s at 4 threads on S24 Ultra | Thermal management prevents sustained throttling |
| No NPU / GPU acceleration | Cannot offload to device accelerator | `n_gpu_layers=0` — CPU path only on Android |
| `watchdog` optional | Background file monitoring disabled without it | `pip install watchdog` to enable |
| Single-device only | State is not synced across devices | Intentional — local privacy by design |
| Peer CLIs with `node-pty` | CLIs that bundle ARM64-incompatible native modules crash on Android | Auto-detected and excluded at startup |
| No encrypted memory | `~/.codey-v2/` stored in plaintext | Encryption planned for a future release |

---

## Logs Reference

| Log file | Contents |
|----------|----------|
| `~/.codey-v2/codey-v2.log` | Main daemon log |
| `~/.codey-v2/plannd.log` | 0.5B planner daemon log |
| `~/.codey-v2/plannd-llama.log` | llama-server log for the 0.5B model |
| `~/.codey-v2/embed-server.log` | nomic-embed llama-server log |
