"""
Token usage tracking — show context window utilization.
"""
from utils.config import MODEL_CONFIG

def estimate_tokens(text: str, path: str = None) -> int:
    """
    Smarter heuristic:
    - Code files (.py, .js, .ts, .c, .cpp, .rs, .go): 1 token ≈ 3 chars
    - Prose/Other (.md, .txt, JSON, etc.): 1 token ≈ 4 chars
    """
    if path:
        code_exts = {".py", ".js", ".ts", ".c", ".cpp", ".h", ".rs", ".go"}
        if any(path.endswith(ext) for ext in code_exts):
            return len(text) // 3
    return len(text) // 4

def estimate_messages_tokens(messages: list[dict]) -> int:
    total = sum(estimate_tokens(m.get("content", "")) for m in messages)
    # Add ~4 tokens per message for role/formatting overhead
    total += len(messages) * 4
    return total

def usage_bar(used: int, total: int, width: int = 20) -> str:
    """Return a simple ASCII usage bar."""
    pct = min(used / total, 1.0)
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    color = "green" if pct < 0.6 else "yellow" if pct < 0.85 else "red"
    tps = ""
    try:
        import core.inference_v2 as _inf
        if hasattr(_inf, "last_tps") and _inf.last_tps > 0:
            tps = f" [dim]· {_inf.last_tps:.1f} t/s[/dim]"
    except Exception:
        pass
    return f"[{color}]{bar}[/{color}] {used}/{total} tokens ({pct*100:.0f}%){tps}"

def get_context_usage(messages: list[dict]) -> tuple[int, int]:
    """Return (used_tokens, max_tokens)."""
    used = estimate_messages_tokens(messages)
    max_ctx = MODEL_CONFIG["n_ctx"]
    return used, max_ctx
