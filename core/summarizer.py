"""
Conversation summarization.
When history gets too long, compress it to save context window space.
Inspired by Claude Code's conversation summarization agent prompt.
"""
from utils.logger import info, warning
from utils.config import AGENT_CONFIG
from core.tokens import estimate_messages_tokens

# Token estimate threshold before we summarize
SUMMARY_THRESHOLD = 1500  # ~6000 chars

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

def should_summarize(history: list[dict]) -> bool:
    """Return True if history is getting too large."""
    return estimate_messages_tokens(history) > SUMMARY_THRESHOLD

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

    info("Summarizing conversation history to save context...")

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
        summary = infer(summary_messages, stream=False)
        if summary and not summary.startswith("[ERROR]"):
            summary_message = {
                "role": "user",
                "content": f"[CONVERSATION SUMMARY]\n{summary}\n[END SUMMARY]"
            }
            new_history = [summary_message] + keep_recent
            info(f"History compressed: {len(history)} → {len(new_history)} messages")
            return new_history
    except Exception as e:
        warning(f"Summarization failed: {e}")

    return history
