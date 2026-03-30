"""
TransformationEngine — converts normalized intermediates to final
Codey-v2 tool-call records ready for export and embedding.

Output record format:
{
    "user":       str,          # lowercased user instruction
    "tool_calls": List[Dict],   # [{"name": ..., "args": {...}}, ...]
    "metadata":   {
        "id":           str,    # sha256[:16] of user text
        "source":       str,
        "quality":      float,
        "language":     str|None,
        "num_steps":    int,
        "tool_names":   List[str],
        "has_test":     bool,
        "is_synthetic": bool,
        "created_at":   int,
    }
}
"""

import hashlib
import time
from typing import Dict, List, Optional

from .rules import apply_rules
from .validator import validate_record, coerce_args


class TransformationEngine:
    """
    Transforms a normalized intermediate record into a Codey-v2 output record.

    Args:
        skip_invalid: If True, silently drop invalid records (default True).
                      If False, raise ValueError on invalid records.
    """

    def __init__(self, skip_invalid: bool = True):
        self.skip_invalid = skip_invalid
        self._errors: List[Dict] = []   # pipeline_errors log

    @property
    def errors(self) -> List[Dict]:
        return self._errors

    def transform(self, intermediate: Dict) -> Optional[Dict]:
        """
        Convert one intermediate record to output format.

        Returns None if the record cannot be transformed or fails validation.
        """
        try:
            # Apply mapping rules → raw tool_calls
            tool_calls = apply_rules(intermediate)

            if not tool_calls:
                self._log_error(intermediate, "no tool calls produced by rules")
                return None

            # Coerce all args to strings, accept "arguments" alias
            tool_calls = [coerce_args(tc) for tc in tool_calls]

            # Validate the full record
            ok, err = validate_record(tool_calls)
            if not ok:
                self._log_error(intermediate, err)
                if not self.skip_invalid:
                    raise ValueError(f"Invalid tool call: {err}")
                return None

            # Build output record
            user = intermediate["instruction"]
            record = {
                "user":       user,
                "tool_calls": tool_calls,
                "metadata":   self._build_metadata(intermediate, tool_calls),
            }
            return record

        except Exception as e:
            self._log_error(intermediate, str(e))
            if not self.skip_invalid:
                raise
            return None

    def _build_metadata(self, intermediate: Dict, tool_calls: List[Dict]) -> Dict:
        user = intermediate["instruction"]
        tool_names = [tc["name"] for tc in tool_calls]
        has_test   = "test_solution.py" in str(tool_calls)

        return {
            "id":           hashlib.sha256(user.encode()).hexdigest()[:16],
            "source":       intermediate.get("source_dataset", "unknown"),
            "quality":      round(intermediate.get("quality", 0.5), 3),
            "language":     intermediate.get("language"),
            "num_steps":    len(tool_calls),
            "tool_names":   tool_names,
            "has_test":     has_test,
            "is_synthetic": intermediate.get("is_synthetic", False),
            "created_at":   int(time.time()),
        }

    def _log_error(self, intermediate: Dict, reason: str) -> None:
        self._errors.append({
            "instruction": intermediate.get("instruction", "")[:100],
            "source":      intermediate.get("source_dataset", ""),
            "reason":      reason,
        })
