# Codey v0.9.1 Implementation Todo

## P1 — Stability

- [x] 1. Fix brittle JSON parser (core/agent.py)
    - Replace regex depth-counting with a proper lazy JSON extractor.
- [x] 2. Fix patch_file collision risk (tools/patch_tools.py)
    - Add uniqueness check: if old_str appears more than once, reject.
    - Add line count to error message.
- [x] 3. Add .codeyignore support
    - Prevent auto_load_from_prompt and /load from reading .env, *.pem, *.key, secrets.
    - Check pattern file in project root before any file load.

## Release

- [x] 4. Bump version to 0.9.1
- [ ] 5. Push to GitHub
