"""
Conversation summarization — adaptive context management.

Strategy (in order):
  1. Trigger at 55% context usage — gives headroom before the wall.
  2. Pin important messages (file writes, errors, existing summaries) — never drop these.
  3. Drop oldest unpinned turns until usage falls to 40% — no model call needed.
  4. After dropping, call the 0.5B model on port 8081 for a ≤100-word "Previously:"
     micro-summary of only the dropped turns. Prepend to compressed history.
  5. Never re-summarize an existing [CONVERSATION SUMMARY] — it stays pinned.

The 0.5B call is best-effort: if port 8081 is unreachable the drop still happens,
we just skip the micro-summary line.
"""
import json
import urllib.request
import urllib.error
from utils.logger import info, warning
from utils.config import MODEL_CONFIG
from core.tokens import estimate_messages_tokens

# ── Thresholds ────────────────────────────────────────────────────────────────

# Fire when (used + response_reserve) exceeds this fraction of n_ctx
# Raised from 0.55 to 0.75 for 32k context — was triggering way too early
SUMMARIZE_THRESHOLD_PCT = 0.75

# After compression, target this fraction of n_ctx
DROP_TARGET_PCT = 0.55

# Max chars per message fed to the 0.5B summarizer (generous — it's small model)
MICRO_SUMMARY_MSG_LIMIT = 2000

# 0.5B model endpoint — uses plannd port from config to avoid hardcoded collision
try:
    from utils.config import PLANND_SERVER_PORT
    _05B_PORT = PLANND_SERVER_PORT
except ImportError:
    _05B_PORT = 8081
_05B_HOST = "127.0.0.1"

_MICRO_SUMMARY_SYSTEM = (
    "You are compressing a coding assistant conversation into one short paragraph. "
    "Capture: what the user wanted, what files were changed, any errors and fixes, "
    "and the current state. Be specific about file names and error messages. "
    "Under 100 words. Start with: Previously: "
)


# ── Pin detection ─────────────────────────────────────────────────────────────

_PIN_SIGNALS = (
    "write_file",
    "patch_file",
    "[ERROR]",
    "[PATCH_FAILED]",
    "[BLOCKED]",
    "[CONVERSATION SUMMARY]",
    "Tool error:",
    "shell",        # shell tool results often contain critical output
)

def _is_pinned(msg: dict) -> bool:
    """
    Return True if this message must never be dropped or re-summarized.

    Pinned messages are:
    - Anything containing a file-write or patch operation
    - Error or failure markers
    - Existing conversation summaries
    - Shell tool results (heuristic: content contains 'shell' keyword in tool context)
    """
    content = msg.get("content", "")
    if not isinstance(content, str):
        return False
    return any(sig in content for sig in _PIN_SIGNALS)


# ── 0.5B micro-summary ────────────────────────────────────────────────────────

def _call_05b(dropped_msgs: list[dict]) -> str | None:
    """
    Summarize dropped messages using the 0.5B on port 8081, or OpenRouter
    when CODEY_BACKEND=openrouter.  Returns the summary string or None.
    """
    if not dropped_msgs:
        return None

    history_text = "\n".join(
        f"{m['role'].upper()}: {m.get('content', '')[:MICRO_SUMMARY_MSG_LIMIT]}"
        for m in dropped_msgs
    )

    messages = [
        {"role": "system", "content": _MICRO_SUMMARY_SYSTEM},
        {"role": "user",   "content": f"Conversation:\n{history_text}"},
    ]

    # Route to remote planner backend when active — avoids needing the local 0.5B server
    try:
        from utils.config import is_remote_planner_backend, CODEY_PLANNER_BACKEND
        if is_remote_planner_backend():
            from core.inference_openrouter import get_remote_backend
            backend = get_remote_backend(CODEY_PLANNER_BACKEND)
            result = backend.infer(messages, max_tokens=160, stream=False)
            if result:
                text, _, _ = result
                return text if text else None
            return None
    except Exception as e:
        warning(f"[summarizer] remote micro-summary failed: {e}")
        return None

    # Local 0.5B path
    payload = {
        "model": "codey-planner",
        "messages": messages,
        "max_tokens": 160,
        "temperature": 0.2,
        "stream": False,
    }

    url = f"http://{_05B_HOST}:{_05B_PORT}/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            choices = result.get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content", "").strip()
                return text if text else None
    except Exception as e:
        warning(f"[summarizer] 0.5B micro-summary failed (port {_05B_PORT} down?): {e}")
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def should_summarize(history: list[dict], system_messages: list[dict] = None) -> bool:
    """
    Return True if context usage has crossed the 55% threshold.

    Args:
        history:         Conversation history messages.
        system_messages: Full messages array (system + history + current) for a
                         more accurate estimate. Falls back to history alone.
    """
    if not history or len(history) < 4:
        return False

    msgs  = system_messages if system_messages else history
    used  = estimate_messages_tokens(msgs)
    budget = MODEL_CONFIG["n_ctx"]
    response_reserve = MODEL_CONFIG.get("max_tokens", 2048)

    return (used + response_reserve) > (budget * SUMMARIZE_THRESHOLD_PCT)


def summarize_history(history: list[dict]) -> list[dict]:
    """
    Compress history using sliding-window drop + optional 0.5B micro-summary.

    Steps:
      1. Always keep the last 4 messages (2 turns) regardless of pin status.
      2. Walk remaining messages oldest-first; collect unpinned ones as candidates.
      3. Drop candidates until token usage is at or below DROP_TARGET_PCT of n_ctx.
      4. Ask 0.5B for a micro-summary of the dropped messages (best-effort).
      5. Prepend the micro-summary to the compressed history if we got one.
      6. Existing [CONVERSATION SUMMARY] messages are pinned and survive untouched.
    """
    if len(history) < 4:
        return history

    budget          = MODEL_CONFIG["n_ctx"]
    drop_target     = int(budget * DROP_TARGET_PCT)
    response_reserve = MODEL_CONFIG.get("max_tokens", 2048)

    old_tokens = estimate_messages_tokens(history)
    info(f"[summarizer] Compressing context ({old_tokens} tokens, {len(history)} messages)")

    # Always keep the 4 most recent messages intact
    keep_tail    = history[-4:]
    candidates   = history[:-4]          # everything older, oldest-first

    pinned   : list[dict] = []
    droppable: list[dict] = []

    for msg in candidates:
        if _is_pinned(msg):
            pinned.append(msg)
        else:
            droppable.append(msg)

    # Drop oldest droppable messages until we hit the target
    dropped : list[dict] = []
    kept_droppable = list(droppable)  # copy; we'll pop from front

    while kept_droppable:
        # Would dropping the oldest bring us under target?
        candidate_history = pinned + kept_droppable[1:] + keep_tail
        projected = estimate_messages_tokens(candidate_history) + response_reserve
        if projected <= drop_target:
            dropped.append(kept_droppable.pop(0))
            break
        dropped.append(kept_droppable.pop(0))

    compressed = pinned + kept_droppable + keep_tail

    # Best-effort micro-summary of what we dropped
    micro = None
    if dropped:
        micro = _call_05b(dropped)

    if micro:
        summary_msg = {
            "role":    "user",
            "content": f"[CONVERSATION SUMMARY]\n{micro}\n[END SUMMARY]",
        }
        compressed = [summary_msg] + compressed

    new_tokens = estimate_messages_tokens(compressed)
    info(
        f"[summarizer] Done: {len(history)} → {len(compressed)} messages, "
        f"{old_tokens} → {new_tokens} tokens "
        f"({'with' if micro else 'without'} micro-summary)"
    )

    return compressed
