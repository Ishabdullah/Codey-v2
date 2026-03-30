"""
Quality scorer for normalized examples.

Returns a float 0.0–1.0. Records below the configured threshold are dropped.
"""

import re
from typing import Dict

# Patterns that indicate placeholder / incomplete content
_PLACEHOLDER_RE = re.compile(
    r"\.\.\.|TODO|FIXME|<insert|<your|<add|pass\s*$|raise NotImplementedError",
    re.IGNORECASE,
)

# Patterns that indicate hallucinated web references
_URL_REF_RE = re.compile(r"https?://\S+|www\.\S+")

# Minimum lengths (characters)
_MIN_INSTRUCTION_LEN = 15
_MIN_RESPONSE_LEN    = 10
_MIN_CONTENT_LEN     = 20   # for write_file content


def score(record: Dict) -> float:
    """
    Score a normalized intermediate record.

    Args:
        record: dict with keys: instruction, response_type, raw_response,
                source_dataset, language (optional)

    Returns:
        Quality score 0.0–1.0
    """
    score_val = 0.5  # Base

    instruction  = record.get("instruction", "")
    raw_response = record.get("raw_response", "")
    source       = record.get("source_dataset", "")
    resp_type    = record.get("response_type", "unknown")

    # ── Instruction quality ───────────────────────────────────────────────────
    instr_words = len(instruction.split())

    if instr_words >= 5:
        score_val += 0.10
    if instr_words >= 10:
        score_val += 0.05
    if len(instruction) < _MIN_INSTRUCTION_LEN:
        score_val -= 0.30
    if instr_words <= 2:
        score_val -= 0.30

    # ── Response quality ──────────────────────────────────────────────────────
    if len(raw_response) >= _MIN_RESPONSE_LEN:
        score_val += 0.10
    if len(raw_response) >= _MIN_CONTENT_LEN:
        score_val += 0.05

    # Placeholder / incomplete content
    if _PLACEHOLDER_RE.search(raw_response):
        score_val -= 0.50

    # Hallucinated web URLs in the response body
    url_count = len(_URL_REF_RE.findall(raw_response))
    if url_count > 2:
        score_val -= 0.20

    # ── Source quality bonus ──────────────────────────────────────────────────
    curated_sources = {
        "hermes-function-calling-v1",
        "glaive-function-calling-v2",
        "xlam-function-calling-60k",
        "mbpp", "humanevalplus", "bigcodebench", "humanevalpack",
    }
    generic_sources = {"alpaca-cleaned", "alpaca_general"}

    if any(s in source for s in curated_sources):
        score_val += 0.15
    elif any(s in source for s in generic_sources):
        score_val -= 0.05

    # Synthetic data gets a small bonus (hand-validated templates)
    if record.get("is_synthetic", False):
        score_val += 0.10

    # ── Multi-step bonus ──────────────────────────────────────────────────────
    if resp_type == "multi_step":
        score_val += 0.10

    # ── Tool-call datasets: verified execution is a big quality signal ────────
    if record.get("execution_verified", False):
        score_val += 0.15

    return max(0.0, min(1.0, score_val))


def has_placeholder(text: str) -> bool:
    """Quick check for stub/placeholder content."""
    return bool(_PLACEHOLDER_RE.search(text))
