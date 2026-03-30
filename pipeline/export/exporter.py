"""
Exporter — writes pipeline output artifacts.

Outputs:
  training_data.jsonl   — ShareGPT-format records for Unsloth fine-tuning
  pipeline_errors.jsonl — skipped records with reasons
  pipeline_stats.json   — run summary (counts, quality histogram, tool breakdown)
"""

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

# Import the actual Codey-v2 system prompt so training data is consistent
try:
    import sys
    import os
    _repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_repo_root))
    from prompts.system_prompt import SYSTEM_PROMPT
except ImportError:
    SYSTEM_PROMPT = (
        "You are Codey-v2, a local AI coding assistant running on Termux.\n"
        "YOUR RESPONSE IS ALWAYS ONE TOOL CALL. Output exactly this structure:\n"
        "<tool>\n{\"name\": \"TOOL_NAME\", \"args\": {\"ARG\": \"VALUE\"}}\n</tool>"
    )


def _format_tool_calls_as_assistant(tool_calls: List[Dict]) -> str:
    """
    Serialize tool_calls to the assistant response format Codey-v2 uses:

    <tool>
    {"name": "shell", "args": {"command": "pkg install python"}}
    </tool>
    <tool>
    ...
    </tool>
    """
    parts = []
    for tc in tool_calls:
        body = json.dumps({"name": tc["name"], "args": tc["args"]}, ensure_ascii=False)
        parts.append(f"<tool>\n{body}\n</tool>")
    return "\n".join(parts)


class Exporter:
    """
    Writes training JSONL and stats for a pipeline run.

    Args:
        output_dir: Directory to write all output files
    """

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._training_path = self.output_dir / "training_data.jsonl"
        self._errors_path   = self.output_dir / "pipeline_errors.jsonl"
        self._stats_path    = self.output_dir / "pipeline_stats.json"

        self._training_fh   = None
        self._errors_fh     = None

        # Stats counters
        self._stats = {
            "start_time":       int(time.time()),
            "end_time":         None,
            "total_input":      0,
            "total_output":     0,
            "total_errors":     0,
            "by_source":        defaultdict(int),
            "by_tool":          defaultdict(int),
            "by_num_steps":     defaultdict(int),
            "quality_buckets":  defaultdict(int),  # 0-0.5, 0.5-0.7, 0.7-0.9, 0.9-1.0
        }

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        self._training_fh = open(self._training_path, "w", encoding="utf-8")
        self._errors_fh   = open(self._errors_path,   "w", encoding="utf-8")
        return self

    def __exit__(self, *_):
        if self._training_fh:
            self._training_fh.close()
        if self._errors_fh:
            self._errors_fh.close()
        self._write_stats()

    # ── Writing ───────────────────────────────────────────────────────────────

    def write_record(self, record: Dict) -> None:
        """Write one output record to training_data.jsonl (ShareGPT format)."""
        sharegpt = self._to_sharegpt(record)
        self._training_fh.write(json.dumps(sharegpt, ensure_ascii=False) + "\n")
        self._update_stats(record)

    def write_error(self, error: Dict) -> None:
        """Write one error record to pipeline_errors.jsonl."""
        self._errors_fh.write(json.dumps(error, ensure_ascii=False) + "\n")
        self._stats["total_errors"] += 1

    def increment_input(self) -> None:
        self._stats["total_input"] += 1

    # ── Format conversion ─────────────────────────────────────────────────────

    @staticmethod
    def _to_sharegpt(record: Dict) -> Dict:
        """
        Convert an output record to ShareGPT JSONL format.

        {
          "conversations": [
            {"role": "system",    "content": "<Codey-v2 system prompt>"},
            {"role": "user",      "content": "install python in termux"},
            {"role": "assistant", "content": "<tool>\n{...}\n</tool>"}
          ],
          "metadata": {...}
        }
        """
        assistant_content = _format_tool_calls_as_assistant(record["tool_calls"])
        return {
            "conversations": [
                {"role": "system",    "content": SYSTEM_PROMPT},
                {"role": "user",      "content": record["user"]},
                {"role": "assistant", "content": assistant_content},
            ],
            "metadata": record.get("metadata", {}),
        }

    # ── Stats ─────────────────────────────────────────────────────────────────

    def _update_stats(self, record: Dict) -> None:
        self._stats["total_output"] += 1

        meta = record.get("metadata", {})
        source     = meta.get("source", "unknown")
        tool_names = meta.get("tool_names", [])
        num_steps  = meta.get("num_steps", 1)
        quality    = meta.get("quality", 0.5)

        self._stats["by_source"][source]         += 1
        self._stats["by_num_steps"][num_steps]   += 1

        for tool in tool_names:
            self._stats["by_tool"][tool] += 1

        if quality < 0.5:
            bucket = "0.0-0.5"
        elif quality < 0.7:
            bucket = "0.5-0.7"
        elif quality < 0.9:
            bucket = "0.7-0.9"
        else:
            bucket = "0.9-1.0"
        self._stats["quality_buckets"][bucket] += 1

    def _write_stats(self) -> None:
        self._stats["end_time"] = int(time.time())
        elapsed = self._stats["end_time"] - self._stats["start_time"]

        # Convert defaultdicts to regular dicts for JSON serialisation
        stats_out = {
            "start_time":       self._stats["start_time"],
            "end_time":         self._stats["end_time"],
            "elapsed_seconds":  elapsed,
            "total_input":      self._stats["total_input"],
            "total_output":     self._stats["total_output"],
            "total_errors":     self._stats["total_errors"],
            "retention_rate":   round(
                self._stats["total_output"] / max(self._stats["total_input"], 1), 3
            ),
            "by_source":        dict(self._stats["by_source"]),
            "by_tool":          dict(self._stats["by_tool"]),
            "by_num_steps":     {str(k): v for k, v in self._stats["by_num_steps"].items()},
            "quality_buckets":  dict(self._stats["quality_buckets"]),
        }

        with open(self._stats_path, "w") as f:
            json.dump(stats_out, f, indent=2)

    # ── Summary print ─────────────────────────────────────────────────────────

    def print_summary(self) -> None:
        """Print a human-readable pipeline summary."""
        s = self._stats
        elapsed = (s["end_time"] or int(time.time())) - s["start_time"]
        retention = s["total_output"] / max(s["total_input"], 1) * 100

        print(f"\n{'='*60}")
        print(f"  Pipeline complete")
        print(f"{'='*60}")
        print(f"  Input records:   {s['total_input']:,}")
        print(f"  Output records:  {s['total_output']:,}  ({retention:.1f}% retention)")
        print(f"  Errors/skipped:  {s['total_errors']:,}")
        print(f"  Elapsed:         {elapsed}s")
        print(f"\n  Tool breakdown:")
        for tool, count in sorted(s["by_tool"].items(), key=lambda x: -x[1]):
            print(f"    {tool:<16} {count:,}")
        print(f"\n  Quality distribution:")
        for bucket, count in sorted(s["quality_buckets"].items()):
            print(f"    {bucket}   {count:,}")
        print(f"\n  Output: {self._training_path}")
        print(f"  Stats:  {self._stats_path}")
        print(f"{'='*60}\n")
