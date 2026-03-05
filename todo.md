# Codey v0.9.5 Implementation Todo

## Bug Fixes & Improvements

- [x] 1. Strip "Final Answer:" prefixes in task checklist (core/orchestrator.py)
    - Strip "Final Answer: ", "Final answer: ", "Done. Final Answer: ", "Final answer:".
- [x] 2. Test and fix orchestrator planner prompt (core/orchestrator.py)
    - Reproduce complex task and verify steps.
    - Tighten `PLAN_PROMPT` if "Open in editor" style steps appear.

## Documentation

- [x] 3. Update README.md
    - .codeyignore
    - Workspace restriction
    - Repo map
    - Auto-commit
    - --no-plan flag
    - /ignore command
    - Version history (v0.9.1 - v0.9.4)

## Release

- [x] 4. Bump version to 0.9.5 (utils/config.py)
- [x] 5. Push to GitHub
