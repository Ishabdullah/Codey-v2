#!/usr/bin/env python3
"""
Static analysis tools for Codey-v2 — Phase 2 (v2.5.2).

Provides:
  - Syntax checking via ast.parse (no tools required)
  - Linter integration: ruff → flake8 (first available wins)
  - Full multi-linter scan for /review command (ruff + flake8 + mypy)
  - Auto-lint hook: runs after every successful file write
  - Pre-write syntax gate: blocks writes with broken Python syntax

Linter preference order: ruff > flake8 > mypy > ast (syntax-only)
User can override by setting CODEY_LINTER env var to "ruff", "flake8", etc.
"""

import ast
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class LintIssue:
    file: str
    line: int
    col: int
    code: str
    message: str
    severity: str   # "error" | "warning" | "info"

    def __str__(self):
        return f"Line {self.line}:{self.col} [{self.code}] {self.message}"


# ── Syntax check (free, no external tools) ────────────────────────────────────

def check_syntax(content: str, filename: str = "<string>") -> Optional[str]:
    """
    Check Python syntax using ast.parse.
    Returns a human-readable error string on failure, None if valid.
    """
    try:
        ast.parse(content, filename=filename)
        return None
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return f"Parse error: {e}"


# ── Output parsers ─────────────────────────────────────────────────────────────

def _parse_colon_format(output: str, filepath: str) -> List[LintIssue]:
    """
    Parse standard 'file:line:col: CODE message' format used by ruff and flake8.
    """
    issues = []
    fname = Path(filepath).name
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Found") or line.startswith("All checks"):
            continue
        # Strip leading filename prefix if present
        for prefix in (filepath + ":", fname + ":"):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        parts = line.split(":", 2)
        if len(parts) >= 3:
            try:
                lineno = int(parts[0])
                col = int(parts[1]) if parts[1].strip().isdigit() else 0
                rest = parts[2].strip()
                # Split code from message: "E302 expected 2 blank lines..."
                space = rest.find(" ")
                code = rest[:space].strip() if space > 0 else rest
                msg = rest[space + 1:].strip() if space > 0 else ""
                if not code:
                    continue
                severity = "error" if code and code[0] in ("E", "F") else "warning"
                issues.append(LintIssue(filepath, lineno, col, code, msg, severity))
            except (ValueError, IndexError):
                continue
    return issues


def _parse_mypy_output(output: str, filepath: str) -> List[LintIssue]:
    """Parse mypy output: file.py:line: error: message"""
    issues = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Found") or line.startswith("Success"):
            continue
        for sev in ("error", "warning", "note"):
            marker = f": {sev}: "
            if marker in line:
                pre = line.split(marker)[0]
                msg = line.split(marker, 1)[1]
                parts = pre.rsplit(":", 1)
                try:
                    lineno = int(parts[-1]) if len(parts) > 1 else 0
                except ValueError:
                    lineno = 0
                issues.append(LintIssue(filepath, lineno, 0, "mypy", msg,
                                        "error" if sev == "error" else "warning"))
                break
    return issues


# ── Single-linter runner ───────────────────────────────────────────────────────

def run_linter(filepath: str, content: str = None) -> Tuple[List[LintIssue], str]:
    """
    Run the best available linter on a Python file.

    Priority: env CODEY_LINTER override → ruff → flake8 → ast syntax-only.

    Args:
        filepath: Path to the .py file.
        content:  Optional in-memory content (used for syntax-only fallback).

    Returns:
        (issues, linter_name) tuple.
        issues is empty list if file is clean or not a Python file.
    """
    p = Path(filepath)
    if p.suffix != ".py":
        return [], "none"

    # Respect user override
    preferred = os.environ.get("CODEY_LINTER", "").lower()

    def _try_ruff():
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=concise", str(filepath)],
                capture_output=True, text=True, timeout=20,
            )
            issues = _parse_colon_format(result.stdout + result.stderr, filepath)
            return issues, "ruff"
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None

    def _try_flake8():
        try:
            result = subprocess.run(
                ["flake8", "--max-line-length=120", str(filepath)],
                capture_output=True, text=True, timeout=20,
            )
            issues = _parse_colon_format(result.stdout, filepath)
            return issues, "flake8"
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None

    # Try in priority order
    for tool, runner in [("ruff", _try_ruff), ("flake8", _try_flake8)]:
        if preferred and preferred != tool:
            continue
        if not shutil.which(tool):
            continue
        res = runner()
        if res is not None:
            return res

    # Fallback: AST syntax check only
    src = content
    if src is None and p.exists():
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            src = None
    if src:
        err = check_syntax(src, filepath)
        if err:
            return [LintIssue(filepath, 0, 0, "SyntaxError", err, "error")], "ast"

    return [], "none"


# ── Multi-linter runner (for /review) ─────────────────────────────────────────

def run_all_linters(filepath: str) -> List[Tuple[str, List[LintIssue]]]:
    """
    Run ALL available linters and return a list of (tool_name, issues) pairs.
    Used by the /review command for a comprehensive report.
    """
    p = Path(filepath)
    if p.suffix != ".py":
        return []

    results = []

    if shutil.which("ruff"):
        try:
            out = subprocess.run(
                ["ruff", "check", "--output-format=concise", str(filepath)],
                capture_output=True, text=True, timeout=20,
            )
            results.append(("ruff", _parse_colon_format(out.stdout + out.stderr, filepath)))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    if shutil.which("flake8"):
        try:
            out = subprocess.run(
                ["flake8", "--max-line-length=120", str(filepath)],
                capture_output=True, text=True, timeout=20,
            )
            results.append(("flake8", _parse_colon_format(out.stdout, filepath)))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    if shutil.which("mypy"):
        try:
            out = subprocess.run(
                ["mypy", "--no-error-summary", str(filepath)],
                capture_output=True, text=True, timeout=30,
            )
            results.append(("mypy", _parse_mypy_output(out.stdout, filepath)))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # Always include syntax check as baseline
    if p.exists():
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            err = check_syntax(src, filepath)
            syntax_issues = (
                [LintIssue(filepath, 0, 0, "SyntaxError", err, "error")] if err else []
            )
            results.append(("syntax", syntax_issues))
        except Exception:
            pass

    return results


# ── Formatting helpers ─────────────────────────────────────────────────────────

def format_issues(issues: List[LintIssue], max_issues: int = 8) -> str:
    """
    Format linter issues as a compact string to append to agent tool results.
    Errors shown first, warnings after.
    """
    if not issues:
        return ""
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity != "error"]
    shown = (errors + warnings)[:max_issues]
    lines = [f"\n\n[LINTER] {len(issues)} issue(s) found:"]
    for issue in shown:
        prefix = "  ✗" if issue.severity == "error" else "  ⚠"
        lines.append(f"{prefix} Line {issue.line}: [{issue.code}] {issue.message}")
    if len(issues) > max_issues:
        lines.append(f"  ... and {len(issues) - max_issues} more (run /review for full report)")
    lines.append("Review and fix any errors before the file is considered done.")
    return "\n".join(lines)


def get_available_linters() -> List[str]:
    """Return names of all installed linter tools."""
    return [t for t in ("ruff", "flake8", "pylint", "mypy") if shutil.which(t)]
