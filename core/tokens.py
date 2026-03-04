"""
Token usage tracking — show context window utilization.
"""
from utils.config import MODEL_CONFIG

def estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 chars."""
    return len(text) // 4

def estimate_messages_tokens(messages: list[dict]) -> int:
    total = sum(estimate_tokens(m.get("content", "")) for m in messages)
    # Add ~4 tokens per message for role/formatting overhead
    total += len(messages) * 4
    return total

def usage_bar(used: int, total: int, width: int = 20) -> str:
    """Return a simple ASCII usage bar."""
    import core.inference as _inf
    pct = min(used / total, 1.0)
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    color = "green" if pct < 0.6 else "yellow" if pct < 0.85 else "red"
    tps = f" [dim]· {_inf.last_tps} t/s[/dim]" if _inf.last_tps > 0 else ""
    return f"[{color}]{bar}[/{color}] {used}/{total} tokens ({pct*100:.0f}%){tps}"

def get_context_usage(messages: list[dict]) -> tuple[int, int]:
    """Return (used_tokens, max_tokens)."""
    used = estimate_messages_tokens(messages)
    max_ctx = MODEL_CONFIG["n_ctx"]
    return used, max_ctx
