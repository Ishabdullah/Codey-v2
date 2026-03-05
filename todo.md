# Codey v0.9.2 Implementation Todo

## P1 — Stability (Final)

- [x] 1. Fix brittle JSON parser (core/agent.py)
- [x] 2. Fix patch_file collision risk (tools/patch_tools.py)
- [x] 3. Add .codeyignore support (core/context.py)
- [x] 4. Portable paths (Move llama-server/model paths to config.py with auto-detect)

## P2 — Security Hardening

- [x] 5. Harden shell blacklist -> allowlist approach (tools/shell_tools.py)
    - Warning + confirmation for rm, curl, wget, chmod, dd, mkfs.
- [x] 6. Mask secrets in session saves (core/sessions.py)
    - Redact API keys, passwords, tokens from history before saving.
- [x] 7. Workspace root restriction
    - Block file operations outside the workspace unless explicitly confirmed.

## Release

- [x] 8. Update task-list.txt
- [x] 9. Bump version to 0.9.2
- [ ] 10. Push to GitHub
