"""
Conversation summarization — adaptive context management.

Summarization triggers when context usage exceeds 75% of n_ctx.
After that threshold, the agent becomes context-aware and decides
when compression is needed based on remaining headroom.
"""
from utils.logger import info, warning
from utils.config import AGENT_CONFIG, MODEL_CONFIG
from core.tokens import estimate_messages_tokens

# Summarize when total message tokens exceed this fraction of n_ctx
SUMMARIZE_THRESHOLD_PCT = 0.75

SUMMARIZE_PROMPT = """You are summarizing a coding assistant conversation to save context space.

Create a compact summary that captures:
1. What the user was trying to accomplish
2. What files were created or modified (with their paths)
3. What commands were run and their results
4. Any errors encountered and how they were fixed
5. Current state — what is done, what might still be needed

Keep the summary under 200 words. Be specific about file names, error messages, and outcomes.
Write in past tense. Start with: "Previously: "
"""


def should_summarize(history: list[dict], system_messages: list[dict] = None) -> bool:
    """
    Return True if context usage has crossed the 75% threshold.

    Args:
        history: Conversation history messages
        system_messages: Optional full messages array (system + history + current).
                         If provided, uses this for a more accurate usage estimate.
    """
    if not history or len(history) < 4:
        return False

    msgs = system_messages if system_messages else history
    used = estimate_messages_tokens(msgs)
    budget = MODEL_CONFIG["n_ctx"]
    response_reserve = MODEL_CONFIG.get("max_tokens", 2048)

    # Trigger when used + response reserve > 75% of total context
    return (used + response_reserve) > (budget * SUMMARIZE_THRESHOLD_PCT)


def summarize_history(history: list[dict]) -> list[dict]:
    """
    Compress history into a single summary message.
    Keeps the last 2 turns intact for immediate context.
    """
    if len(history) < 4:
        return history

    from core.inference_v2 import infer

    # Keep last 2 turns (4 messages) fresh
    to_summarize = history[:-4] if len(history) > 4 else history[:-2]
    keep_recent  = history[-4:] if len(history) > 4 else history[-2:]

    if not to_summarize:
        return history

    old_tokens = estimate_messages_tokens(history)
    info(f"Compressing context ({old_tokens} tokens, {len(history)} messages)...")

    # Build summary request
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content'][:300]}"
        for m in to_summarize
    )

    summary_messages = [
        {"role": "system", "content": SUMMARIZE_PROMPT},
        {"role": "user",   "content": f"Conversation to summarize:\n{history_text}"}
    ]

    try:
        summary = infer(summary_messages, stream=False, max_tokens=300)
        if summary and not summary.startswith("[ERROR]"):
            summary_message = {
                "role": "user",
                "content": f"[CONVERSATION SUMMARY]\n{summary}\n[END SUMMARY]"
            }
            new_history = [summary_message] + keep_recent
            new_tokens = estimate_messages_tokens(new_history)
            info(f"Context compressed: {len(history)} → {len(new_history)} messages, "
                 f"{old_tokens} → {new_tokens} tokens")
            return new_history
    except Exception as e:
        warning(f"Summarization failed: {e}")

    return history
