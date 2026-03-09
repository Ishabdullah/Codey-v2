# Project
Codey-v2 is a local AI coding assistant for Termux that runs Qwen2.5-Coder-7B-Instruct via llama-server and can create files, run shell commands, and fix errors autonomously.

# Stack
- Python 3.12
- llama-server (llama.cpp binary at ~/llama.cpp/build/bin/)
- Model: Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf at ~/models/qwen2.5-coder-7b/
- rich (terminal UI)

# Structure
- main.py — CLI entrypoint, REPL loop, command handling
- core/agent.py — ReAct tool loop, parses tool calls, executes tools
- core/inference.py — llama-server HTTP client, starts/stops server
- core/loader.py — validates binary and model paths
- core/context.py — file context injection (/read command)
- core/project.py — project type detection from cwd
- core/codeymd.py — CODEY.md read/write/generate
- core/summarizer.py — compresses long conversation history
- prompts/system_prompt.py — system prompt and tool format
- tools/file_tools.py — read/write/append/list with confirmation
- tools/shell_tools.py — shell execution with safety checks
- utils/config.py — all settings (model path, threads, context size)
- utils/logger.py — rich terminal output helpers

# Commands
- Run: codey-v2 "task"
- Interactive: codey-v2
- Skip confirms: codey-v2 --yolo "task"
- Pre-load file: codey-v2 --read file.py "task"
- Generate memory: codey-v2 --init

# Conventions
- Tool calls use <tool>{"name": "...", "args": {...}}</tool> format
- llama-server runs on port 8081, started automatically
- Confirmations on by default, disabled with --yolo
- Context window: 1024 tokens (mobile RAM constraint)
- All files written to cwd unless absolute path given

# Notes
- Model loads in ~15s on first query, stays hot for session
- If phone crashes: reduce n_ctx in utils/config.py to 512
- CODEY_MODEL env var overrides model path
- CODEY_THREADS env var overrides thread count
