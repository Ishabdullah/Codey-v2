"""
plannd — Task planner for Codey-v2

Provides get_plan(): sends a user prompt to the 0.5B model on port 8081
and returns a numbered step list for the 7B agent to execute.

Port assignments:
  8080 — Qwen2.5-Coder-7B  (agent execution only)
  8081 — Qwen2.5-0.5B       (planning + summarization)
  8082 — nomic-embed-text    (embeddings)
"""

import json
import re
import urllib.request
import urllib.error
from typing import Optional, List


# ── Planner prompt ────────────────────────────────────────────────────────────
# Single prompt used by ALL backends: local 0.5B, OpenRouter, UnlimitedClaude.
# Test and tune this prompt against remote models (faster iteration), then
# the same prompt runs on local — results are directly comparable.

PLANNER_PROMPT = (
    "You are a task planner. Write a numbered list of 2 to 8 steps.\n"
    "Your plan is executed AS-IS by a code agent. Every filename and path in your plan\n"
    "will be used exactly as you write it. Do not abbreviate, paraphrase, or assume.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "CRITICAL RULE: FILENAMES AND PATHS\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "• EXTRACT the exact filenames from the user's message FIRST. Highlight them mentally.\n"
    "• COPY them AS-IS into your plan. Do not abbreviate, shorten, or 'clean up' names.\n"
    "• EVERY mention of a filename in your plan must be identical to the user's original.\n"
    "• Use the SAME filename consistently across ALL steps (Create, Run, Verify).\n"
    "• Do NOT invent subdirectory paths (e.g. do NOT write 'data/results.py' unless the\n"
    "  user explicitly said 'data/results.py'). Files go in the current working directory.\n\n"
    "VIOLATIONS (these are WRONG):\n"
    "  ✗ User says 'fibonacci.py' → you write 'fib.py' (abbreviation)\n"
    "  ✗ User says 'fibonacci.py' → you write 'fibonacci.py' in step 1 but 'fib.py' in step 2\n"
    "  ✗ User says 'fibonacci.py' → you write 'src/fibonacci.py' (invented path)\n"
    "  ✗ User says 'results.json' → you write 'out.json' (different name)\n\n"
    "CORRECT PATTERN:\n"
    "  User says: 'Create fibonacci.py that prints 20 Fibonacci numbers, then run it'\n"
    "  You write:\n"
    "    1. Create fibonacci.py: accepts n, prints each Fibonacci number on its own line\n"
    "    2. Run: python fibonacci.py 20\n"
    "  ✓ Both steps use 'fibonacci.py' — identical, no abbreviation, no extra paths.\n\n"
    "STEP TEMPLATES:\n"
    "  Create <file>: accepts <input>, <feature1>, <feature2>, ..., prints <format>\n"
    "  Run: python <exact filename from user> <exact value from user>\n"
    "  Run: pytest <file>\n"
    "  Verify: <expected outcome>\n\n"
    "RULES:\n"
    "1. Create step: use the format above. List every feature after the colon, "
    "comma-separated. Read the full user message. Include ALL of: input args, processing, "
    "file saves, timestamps, print format. Keep adding features until complete.\n"
    "2. Run: copy the exact filename and argument from the user's message word for word. "
    "One Run step per execution. Use the SAME filename as in the Create step.\n"
    "3. Verify: describes what should be true — never a command.\n"
    "4. No two steps repeat the same action. EXCEPTION: if the user explicitly asks to run "
    "something multiple times, include a Run step for each run.\n"
    "5. Use 'pytest' for test files, not 'python'.\n"
    "6. No code, no markdown, no extra text. Plain English step descriptions only.\n"
    "7. Never invent capabilities. Only describe what the user explicitly stated.\n"
    "8. Peer CLI steps: if the user says 'ask claude to X', 'have gemini do X', 'use qwen to X', "
    "etc., copy that instruction EXACTLY as: 'Ask claude to X'. Never rephrase.\n\n"
    "EXAMPLE — user says:\n"
    "'Create a Python script called fibonacci.py that generates the first 20 fibonacci "
    "numbers and prints them one per line then runs it to show the output'\n\n"
    "Your plan:\n"
    "1. Create fibonacci.py: accepts n, prints each Fibonacci number on its own line\n"
    "2. Run: python fibonacci.py 20\n\n"
    "NOTE: User said 'fibonacci.py', so you MUST use 'fibonacci.py' in both steps.\n"
    "Do NOT write 'fib.py', 'fib', 'fibonacci', or any other variation.\n\n"
    "ANOTHER EXAMPLE — user says:\n"
    "'Create xform.py that accepts a corpus.txt path, counts tokens/lines, appends each result "
    "with a timestamp to tally.json, prints a clean summary; run on corpus.txt twice, "
    "verify tally.json has 2 entries'\n\n"
    "Your plan:\n"
    "1. Create xform.py: accepts a path, counts tokens and lines, "
    "appends result with timestamp to tally.json, prints a clean summary\n"
    "2. Run: python xform.py corpus.txt\n"
    "3. Run: python xform.py corpus.txt\n"
    "4. Verify: tally.json contains exactly 2 entries with timestamps\n\n"
    "NOTE: User said 'xform.py', 'corpus.txt', 'tally.json'. Plan uses these exact names."
)


# ── Step parser ───────────────────────────────────────────────────────────────

def parse_steps(raw: str) -> List[str]:
    """
    Extract numbered steps from model output.

    Strips <think>...</think> blocks (R1-style reasoning traces),
    then collects lines matching "N. step" or "N) step".
    """
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    steps: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        if m:
            step = m.group(2).strip()
            if step:
                steps.append(step)
    if steps:
        last = steps[-1]
        if last and last[-1] not in ".!?)" and last[-1].isalpha():
            print(
                "[plannd] plan may be truncated — consider increasing max_tokens",
                flush=True,
            )
    return steps


# ── Tool-call step filter ─────────────────────────────────────────────────────

_TOOL_VERBS = re.compile(
    r"^(create|write|build|add|run|execute|install|verify|check|test|confirm|update|delete|remove"
    r"|ask|have|use|tell|call|let|get|initialize|init|commit|push)\b",
    re.IGNORECASE,
)

# Peer CLI names — steps mentioning these are always kept regardless of verb
_PEER_NAME_RE = re.compile(r'\b(claude|gemini|qwen)\b', re.IGNORECASE)

def filter_tool_steps(steps: List[str]) -> List[str]:
    """
    Keep only steps that correspond to real tool calls (create file, run
    command, verify output).  Drops implementation-detail steps the 0.5B
    model sometimes emits (e.g. "Count lines using os.linesep").

    Rules:
    - Step 1 is always kept (create/write the file — enriched with full prompt).
    - Subsequent steps are kept if they start with a recognised action verb,
      contain 'Run:' / 'Verify' / 'Check', or mention a peer CLI by name
      (claude/gemini/qwen — these are delegation steps and must be preserved).
    """
    if not steps:
        return steps
    kept = [steps[0]]
    for step in steps[1:]:
        if (
            _TOOL_VERBS.match(step)
            or re.search(r"\bRun:|Verify|Check\b", step, re.IGNORECASE)
            or _PEER_NAME_RE.search(step)
        ):
            kept.append(step)
    return kept if len(kept) > 1 else steps[:2]  # fallback: keep first two


# ── Planning via 0.5B on port 8081 (or remote when CODEY_BACKEND_P is set) ──

def _get_plan_remote(prompt: str) -> Optional[List[str]]:
    """Route planning through the active planner backend (OpenRouter or UnlimitedClaude)."""
    try:
        from utils.config import (
            PLANNER_TEMPERATURE, PLANNER_MAX_TOKENS, CODEY_PLANNER_BACKEND,
            OPENROUTER_PLANNER_MODEL, OPENROUTER_BASE_URL, OPENROUTER_API_KEY,
            UNLIMITEDCLAUDE_PLANNER_MODEL, UNLIMITEDCLAUDE_BASE_URL, UNLIMITEDCLAUDE_API_KEY,
        )
        from utils.logger import info, warning

        if CODEY_PLANNER_BACKEND == "unlimitedclaude":
            planner_model = UNLIMITEDCLAUDE_PLANNER_MODEL
            base_url      = UNLIMITEDCLAUDE_BASE_URL.rstrip("/")
            api_key       = UNLIMITEDCLAUDE_API_KEY
            backend_label = "unlimitedclaude"
        else:
            planner_model = OPENROUTER_PLANNER_MODEL
            base_url      = OPENROUTER_BASE_URL.rstrip("/")
            api_key       = OPENROUTER_API_KEY
            backend_label = "openrouter"

        messages = [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user",   "content": prompt},
        ]

        # Use the dedicated planner model and low temperature (0.2 not 0.7)
        import json as _json
        import urllib.request as _req
        payload = {
            "model": planner_model,
            "messages": messages,
            "max_tokens": PLANNER_MAX_TOKENS,
            "temperature": PLANNER_TEMPERATURE,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/codey-v2",
            "X-Title": "Codey-v2",
        }
        request = _req.Request(
            f"{base_url}/chat/completions",
            data=_json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with _req.urlopen(request, timeout=60) as resp:
                result = _json.loads(resp.read().decode("utf-8"))
            msg = result["choices"][0].get("message", {})
            # content can be null when the model returns a tool_call instead of text
            content = msg.get("content") or ""
            # Qwen3 / thinking models put output in reasoning_content when content is empty
            if not content:
                content = msg.get("reasoning_content") or ""
            # some models return text inside tool_calls[0].function.arguments
            if not content and "tool_calls" in msg:
                try:
                    content = msg["tool_calls"][0]["function"]["arguments"]
                except (KeyError, IndexError):
                    pass
            raw = content.strip()
        except Exception as e:
            warning(f"[plannd] {backend_label} plan request failed: {e}")
            return None

        if not raw:
            warning(f"[plannd] {backend_label} returned empty plan response")
            return None

        steps = parse_steps(raw)
        steps = filter_tool_steps(steps)
        if not steps:
            warning(f"[plannd] {backend_label} response had no parseable steps. Raw: {raw[:120]}")
            return None
        info(f"[plannd] {backend_label} plan ({planner_model}): {len(steps)} steps")
        return steps
    except Exception as e:
        from utils.logger import warning
        warning(f"[plannd] remote planning failed: {e}")
        return None


def get_plan(prompt: str) -> Optional[List[str]]:
    """
    Break *prompt* into a numbered plan.

    Uses the local 0.5B on port 8081 by default.
    When CODEY_BACKEND_P (or CODEY_BACKEND) is a remote backend, routes
    there instead so the 0.5B server does not need to be running.
    """
    try:
        from utils.config import is_remote_planner_backend
        if is_remote_planner_backend():
            return _get_plan_remote(prompt)
    except ImportError:
        pass

    try:
        from utils.config import PLANNER_TEMPERATURE, PLANNER_MAX_TOKENS
        temperature = PLANNER_TEMPERATURE
        max_tokens  = PLANNER_MAX_TOKENS
    except ImportError:
        temperature = 0.2
        max_tokens  = 512

    try:
        from utils.config import PLANND_SERVER_PORT
        port = PLANND_SERVER_PORT
    except ImportError:
        port = 8081

    payload = {
        "model": "plannd",
        "messages": [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            choices = result.get("choices", [])
            if not choices:
                return None
            raw = choices[0].get("message", {}).get("content", "").strip()
            if not raw:
                return None
            steps = parse_steps(raw)
            steps = filter_tool_steps(steps)
            return steps if steps else None
    except Exception as e:
        print(f"[plannd] get_plan error: {e}", flush=True)
        return None
