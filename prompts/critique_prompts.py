"""
Self-critique prompt templates — Phase 2 (v2.6.2)

Used by core/recursive.py to prompt the model to review its own output
before it is returned as the final response.

Three templates cover the main task types:
  CRITIQUE_CODE  — write_file, patch_file, general code generation
  CRITIQUE_TOOL  — tool call validation (format, completeness)
  CRITIQUE_PLAN  — orchestration plan review

Each template asks the model to:
  1. Rate quality 1-10 (parsed by extract_rating() in recursive.py)
  2. List specific issues (triggers refinement if critical ones found)
  3. Emit "NEED_DOCS: <topic>" when it is unsure about an API or library
     (extracted by extract_doc_needs() and triggers targeted KB retrieval)

The critique response must be PLAIN TEXT only — no tool calls, no code blocks.
"""

# ── Code / File Write Critique ────────────────────────────────────────────────

CRITIQUE_CODE = """\
Review the response you just wrote. Check for:
1. Syntax errors or typos
2. Logic bugs (off-by-one errors, missing edge cases, wrong return types)
3. Missing imports or undefined variables
4. Whether it completely solves the user's request (no stubs, no "...")
5. Security issues (injection, hardcoded secrets, path traversal)
6. Any APIs, methods, or library calls you are not 100% sure about

Rate the quality 1-10. List specific issues found.
If you're unsure about any API or library, write "NEED_DOCS: <topic>" on its own line.
If there are no issues, write "Quality: 9/10. No issues found." and nothing else.
Output ONLY your critique — no revised code yet."""

# ── Tool Call Critique ────────────────────────────────────────────────────────

CRITIQUE_TOOL = """\
Review the tool call you are about to make. Check:
1. Is the file path correct and consistent with the user's project?
2. Is the content complete? (no stubs, no "...", no TODO placeholders)
3. Does it actually accomplish what the user asked for?
4. Are there any syntax errors in the content?
5. Is the JSON properly escaped and well-formed?

Rate confidence 1-10. List any concerns.
If there are no issues, write "Quality: 9/10. No issues found." and nothing else.
Output ONLY your critique — no revised tool call yet."""

# ── Orchestration Plan Critique ───────────────────────────────────────────────

CRITIQUE_PLAN = """\
Review the plan you just wrote. Check:
1. Does each step have exactly ONE concrete action?
2. Are there any redundant or unnecessary steps?
3. Does the order make sense? (dependencies resolved before dependents)
4. Will this actually accomplish the user's full request?
5. Are there any missing steps?

Rate quality 1-10. List issues.
If there are no issues, write "Quality: 9/10. No issues found." and nothing else.
Output ONLY your critique — no revised plan yet."""

# ── Prompt Selection ──────────────────────────────────────────────────────────

def select_critique_prompt(task_type: str) -> str:
    """
    Select the appropriate critique prompt for a given task type.

    Args:
        task_type: "code", "write_file", "patch_file", "plan", "orchestrate", or other

    Returns:
        Critique prompt string
    """
    if task_type in ("write_file", "patch_file", "code"):
        return CRITIQUE_CODE
    if task_type in ("plan", "orchestrate"):
        return CRITIQUE_PLAN
    return CRITIQUE_TOOL
