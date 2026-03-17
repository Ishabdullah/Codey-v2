"""
Skill loader — Phase 5 (v2.6.5)

Searches the knowledge base for skill definitions from cloned external repos
(awesome-claude-skills, superpowers, skil, etc.) and returns a formatted
## Relevant Skills block for injection into the system prompt.

Skills are stored under knowledge/skills/ and indexed by tools/setup_skills.sh.
If no skill repos are indexed, load_relevant_skills() returns "" silently.

Usage:
    from core.skills import load_relevant_skills, list_available_skills

    # Inject into system prompt (called from layered_prompt._build_draft_prompt)
    block = load_relevant_skills(user_message, budget_chars=800)
    # Returns "" if no skills indexed or nothing relevant found

    # List what's installed
    repos = list_available_skills()
    # ['awesome-claude-skills', 'superpowers', 'skil', ...]
"""

from pathlib import Path
from utils.config import CODEY_DIR

SKILL_DIR = CODEY_DIR / "knowledge" / "skills"


def load_relevant_skills(user_message: str, budget_chars: int = 800) -> str:
    """
    Search KB skill repos for definitions matching the current task.

    Uses a skill-biased query ("skill template pattern: <task>") to surface
    skill definitions over generic documentation chunks.

    Args:
        user_message: The user's current request
        budget_chars: Max characters to return (~200 tokens at budget=800)

    Returns:
        A '## Relevant Skills' block ready for system prompt injection,
        or "" if skill repos are not indexed or nothing relevant found.
        Never raises.
    """
    if not user_message or not user_message.strip():
        return ""

    # Skip if skill repos haven't been set up — avoids spurious doc results
    if not SKILL_DIR.exists():
        return ""
    try:
        if not any(True for _ in SKILL_DIR.iterdir()):
            return ""
    except Exception:
        return ""

    try:
        from core.retrieval import retrieve
        raw = retrieve(
            f"skill template pattern: {user_message}",
            budget_chars=budget_chars,
        )
        if not raw:
            return ""
        # Rename generic RAG header to be skill-specific
        return raw.replace("## Reference Material", "## Relevant Skills", 1)
    except Exception:
        return ""


def list_available_skills() -> list:
    """Return names of cloned skill repositories, or [] if none."""
    if not SKILL_DIR.exists():
        return []
    try:
        return [
            d.name for d in sorted(SKILL_DIR.iterdir())
            if d.is_dir() and not d.name.startswith(".")
        ]
    except Exception:
        return []
