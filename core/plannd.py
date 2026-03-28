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

PLANNER_PROMPT = (
    "You are a task planner. Write a numbered list of 2 to 5 steps.\n\n"
    "STEP TEMPLATES:\n"
    "  Create <file>.py: accepts <input>, <feature1>, <feature2>, ..., prints <format>\n"
    "  Run: python <exact filename from user> <exact value from user>\n"
    "  Run: pytest <file>.py\n"
    "  Verify: <expected outcome>\n\n"
    "RULES:\n"
    "1. Create step: use the colon format above. List every feature after the colon, "
    "comma-separated. Read the full user message. Include ALL of: input args, processing, "
    "file saves, timestamps, print format. Keep adding features until you have listed everything.\n"
    "2. Run: use the exact filename and values from the user's message. "
    "Do not invent filenames. One Run step per execution requested.\n"
    "3. Verify: describes what should be true — never a command.\n"
    "4. No two steps repeat the same action.\n"
    "5. Use 'pytest' for test files, not 'python'.\n"
    "6. No code, no markdown, no extra text.\n\n"
    "EXAMPLE — user says "
    "'Create fib.py that prints the first 20 Fibonacci numbers one per line, then run it':\n"
    "1. Create fib.py: accepts n, prints each Fibonacci number on its own line\n"
    "2. Run: python fib.py 20\n\n"
    "EXAMPLE — user says "
    "'Create wc.py that accepts a filename, counts words/lines/chars, appends each result "
    "with a timestamp to out.json, prints a clean summary; run on main.py twice, "
    "verify out.json has 2 entries':\n"
    "1. Create wc.py: accepts a filename, counts words, lines, and characters, "
    "appends result with timestamp to out.json, prints a clean summary\n"
    "2. Run: python wc.py main.py\n"
    "3. Run: python wc.py main.py\n"
    "4. Verify: out.json contains exactly 2 entries with timestamps"
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
    r"^(create|write|build|add|run|execute|install|verify|check|test|confirm|update|delete|remove)\b",
    re.IGNORECASE,
)

def filter_tool_steps(steps: List[str]) -> List[str]:
    """
    Keep only steps that correspond to real tool calls (create file, run
    command, verify output).  Drops implementation-detail steps the 0.5B
    model sometimes emits (e.g. "Count lines using os.linesep").

    Rules:
    - Step 1 is always kept (create/write the file — enriched with full prompt).
    - Subsequent steps are kept only if they start with a recognised action verb
      or contain 'Run:' / 'Verify' / 'Check'.
    """
    if not steps:
        return steps
    kept = [steps[0]]
    for step in steps[1:]:
        if _TOOL_VERBS.match(step) or re.search(r"\bRun:|Verify|Check\b", step, re.IGNORECASE):
            kept.append(step)
    return kept if len(kept) > 1 else steps[:2]  # fallback: keep first two


# ── Planning via 0.5B on port 8081 ───────────────────────────────────────────

def get_plan(prompt: str) -> Optional[List[str]]:
    """
    Ask the 0.5B model on port 8081 to break *prompt* into a numbered plan.

    Makes a direct HTTP call to the llama-server /v1/chat/completions endpoint
    with a planning-specific system prompt, low temperature, and a tight token
    budget.  Returns the parsed step list, or None on any failure so the caller
    can fall through to direct execution.
    """
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
