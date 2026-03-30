"""
Normalization pipeline.

Converts raw heterogeneous dataset records into a uniform intermediate format
before the transformation engine maps them to Codey-v2 tool calls.

Intermediate format:
{
    "instruction":   str,   # cleaned user instruction
    "response_type": str,   # shell_command | file_write | ... (see classifier)
    "raw_response":  str,   # cleaned response content
    "language":      str|None,
    "source_dataset": str,
    "source_id":     str,
    "quality":       float,
    "is_synthetic":  bool,
    "execution_verified": bool,
    # dataset-specific extras kept for transformer
    "_extra":        dict,
}
"""

import re
import hashlib
from typing import Dict, Optional, Iterator

from .classifier import (
    classify_response, detect_language,
    SHELL_COMMAND, FILE_WRITE, CODE_GENERATION, UNKNOWN,
)
from .quality import score as quality_score, has_placeholder


# ── Text cleaning helpers ─────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Normalise whitespace, strip leading/trailing noise."""
    text = text.strip()
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip surrounding markdown bold/italic that sometimes wraps instructions
    text = re.sub(r"^\*+|\*+$", "", text).strip()
    return text


def _extract_code_block(text: str) -> Optional[str]:
    """Pull the first fenced code block out of a response."""
    m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def _strip_leading_verb(instruction: str) -> str:
    """Lower-case and remove common leading verbs ('Write a ...', 'Create ...')."""
    return instruction.lower().strip().rstrip(".")


# ── Per-schema extractors ─────────────────────────────────────────────────────

class NormalizationPipeline:
    """
    Routes raw records to the correct extractor based on _schema_type,
    scores them, and yields normalized intermediates.

    Args:
        min_quality: Drop records below this threshold (default 0.5)
        dedup:       Deduplicate by instruction hash (default True)
    """

    def __init__(self, min_quality: float = 0.5, dedup: bool = True):
        self.min_quality = min_quality
        self.dedup = dedup
        self._seen: set = set()

        self._extractors = {
            "glaive_fc":       self._extract_glaive_fc,
            "hermes_fc":       self._extract_hermes_fc,
            "xlam_fc":         self._extract_xlam_fc,
            "alpaca_code":     self._extract_alpaca,
            "alpaca_general":  self._extract_alpaca,
            "codesearchnet":   self._extract_codesearchnet,
            "mbpp":            self._extract_mbpp,
            "humaneval":       self._extract_humaneval,
            "bigcodebench":    self._extract_bigcodebench,
            "humanevalpack":   self._extract_humanevalpack,
            "code_feedback":   self._extract_code_feedback,
            "orca_agent":      self._extract_orca_agent,
            "bfcl":            self._extract_bfcl,
            "jsonl_generic":   self._extract_jsonl_generic,
        }

    # ── Public entry point ────────────────────────────────────────────────────

    def process(self, raw: Dict) -> Optional[Dict]:
        """
        Normalize one raw record.

        Returns None if the record should be dropped (low quality / duplicate).
        """
        schema = raw.get("_schema_type", "jsonl_generic")
        extractor = self._extractors.get(schema, self._extract_jsonl_generic)

        try:
            intermediate = extractor(raw)
        except Exception:
            return None

        if intermediate is None:
            return None

        # Deduplication by normalized instruction hash
        if self.dedup:
            key = hashlib.md5(intermediate["instruction"].encode()).hexdigest()
            if key in self._seen:
                return None
            self._seen.add(key)

        # Quality scoring
        intermediate["quality"] = quality_score(intermediate)
        if intermediate["quality"] < self.min_quality:
            return None

        # Drop placeholder content
        if has_placeholder(intermediate["raw_response"]):
            return None

        return intermediate

    # ── Schema extractors ─────────────────────────────────────────────────────

    def _make_base(
        self,
        instruction: str,
        raw_response: str,
        source: str,
        source_id: str = "",
        extra: Optional[Dict] = None,
        is_synthetic: bool = False,
        execution_verified: bool = False,
    ) -> Optional[Dict]:
        instruction  = _clean_text(instruction)
        raw_response = _clean_text(raw_response)

        if not instruction or not raw_response:
            return None

        code = _extract_code_block(raw_response) or raw_response
        lang = detect_language(code, instruction)
        resp_type = classify_response(raw_response, instruction)

        return {
            "instruction":        _strip_leading_verb(instruction),
            "response_type":      resp_type,
            "raw_response":       raw_response,
            "language":           lang,
            "source_dataset":     source,
            "source_id":          source_id or "",
            "quality":            0.0,  # filled in by process()
            "is_synthetic":       is_synthetic,
            "execution_verified": execution_verified,
            "_extra":             extra or {},
        }

    # ── Glaive function-calling v2 ────────────────────────────────────────────
    def _extract_glaive_fc(self, raw: Dict) -> Optional[Dict]:
        """
        Schema: {"system": "...FUNCTION: {...}...", "chat": "USER: ...\nASSISTANT: <functioncall> {...}"}
        """
        chat = raw.get("chat", "")
        system = raw.get("system", "")

        # Extract last USER turn
        user_match = re.findall(r"USER:\s*(.*?)(?=\nASSISTANT:|\Z)", chat, re.DOTALL)
        if not user_match:
            return None
        instruction = user_match[-1].strip()

        # Extract <functioncall> JSON
        fc_match = re.search(r"<functioncall>\s*(\{.*?\})", chat, re.DOTALL)
        if not fc_match:
            return None
        raw_response = fc_match.group(1).strip()

        return self._make_base(
            instruction, raw_response,
            source="glaive-function-calling-v2",
            extra={"system_prompt": system, "schema_type": "function_call_json"},
        )

    # ── Hermes function-calling v1 ────────────────────────────────────────────
    def _extract_hermes_fc(self, raw: Dict) -> Optional[Dict]:
        """
        Schema: {"conversations": [{"role": ..., "content": ...}, ...]}
        """
        convs = raw.get("conversations", [])
        user_content = ""
        assistant_content = ""

        for turn in convs:
            role = turn.get("role", turn.get("from", ""))
            content = turn.get("content", turn.get("value", ""))
            if role in ("user", "human"):
                user_content = content
            elif role in ("assistant", "gpt") and not assistant_content:
                assistant_content = content

        if not user_content or not assistant_content:
            return None

        # Strip <tool_call> wrapper if present
        tc_match = re.search(r"<tool_call>\s*(\{.*?})\s*</tool_call>", assistant_content, re.DOTALL)
        raw_response = tc_match.group(1) if tc_match else assistant_content

        return self._make_base(
            user_content, raw_response,
            source="hermes-function-calling-v1",
            extra={"schema_type": "function_call_json"},
        )

    # ── xLAM / APIGen ─────────────────────────────────────────────────────────
    def _extract_xlam_fc(self, raw: Dict) -> Optional[Dict]:
        """
        Schema: {"query": "...", "answers": "[{\"name\": ..., \"arguments\": {...}}]", "tools": "..."}
        """
        query = raw.get("query", "")
        answers = raw.get("answers", "[]")

        if not query:
            return None

        return self._make_base(
            query, answers,
            source=raw.get("_source", "xlam-function-calling"),
            execution_verified=True,
            extra={"schema_type": "xlam_answers", "tools_spec": raw.get("tools", "")},
        )

    # ── Alpaca-style (code and general) ───────────────────────────────────────
    def _extract_alpaca(self, raw: Dict) -> Optional[Dict]:
        instruction = raw.get("instruction", "")
        inp         = raw.get("input", "")
        output      = raw.get("output", raw.get("response", ""))

        if not instruction or not output:
            return None

        # Merge non-empty input into instruction
        if inp and inp.strip():
            instruction = f"{instruction}\nContext: {inp}"

        return self._make_base(
            instruction, output,
            source=raw.get("_source", "alpaca"),
        )

    # ── CodeSearchNet instructional ───────────────────────────────────────────
    def _extract_codesearchnet(self, raw: Dict) -> Optional[Dict]:
        instruction = raw.get("instruction", "")
        response    = raw.get("response", "")
        if not instruction or not response:
            return None
        return self._make_base(
            instruction, response,
            source="instructional-codesearchnet-python",
        )

    # ── MBPP ─────────────────────────────────────────────────────────────────
    def _extract_mbpp(self, raw: Dict) -> Optional[Dict]:
        text      = raw.get("text", "")
        code      = raw.get("code", "")
        tests     = raw.get("test_list", [])
        task_id   = str(raw.get("task_id", ""))

        if not text or not code:
            return None

        return self._make_base(
            text, code,
            source="mbpp",
            source_id=task_id,
            execution_verified=True,
            extra={"test_list": tests, "schema_type": "mbpp"},
        )

    # ── HumanEval+ ───────────────────────────────────────────────────────────
    def _extract_humaneval(self, raw: Dict) -> Optional[Dict]:
        prompt    = raw.get("prompt", "")
        solution  = raw.get("canonical_solution", "")
        test      = raw.get("test", "")
        task_id   = str(raw.get("task_id", ""))
        entry     = raw.get("entry_point", "")

        if not prompt or not solution:
            return None

        # Extract docstring from prompt as instruction
        doc_match = re.search(r'"""(.*?)"""', prompt, re.DOTALL)
        instruction = doc_match.group(1).strip() if doc_match else prompt.strip()

        full_code = prompt + solution
        return self._make_base(
            instruction, full_code,
            source="humanevalplus",
            source_id=task_id,
            execution_verified=True,
            extra={"test": test, "entry_point": entry, "schema_type": "humaneval"},
        )

    # ── BigCodeBench ─────────────────────────────────────────────────────────
    def _extract_bigcodebench(self, raw: Dict) -> Optional[Dict]:
        instruction = raw.get("instruct_prompt", "")
        solution    = raw.get("canonical_solution", "")
        test        = raw.get("test", "")
        task_id     = str(raw.get("task_id", ""))

        if not instruction or not solution:
            return None

        return self._make_base(
            instruction, solution,
            source="bigcodebench",
            source_id=task_id,
            execution_verified=True,
            extra={"test": test, "schema_type": "bigcodebench"},
        )

    # ── HumanEvalPack ────────────────────────────────────────────────────────
    def _extract_humanevalpack(self, raw: Dict) -> Optional[Dict]:
        prompt        = raw.get("prompt", "")
        solution      = raw.get("canonical_solution", "")
        buggy         = raw.get("buggy_solution", "")
        task_id       = str(raw.get("task_id", ""))
        task_type     = raw.get("task_type", "synthesis")  # synthesis|fix|explain
        language      = raw.get("language", "python")

        if not prompt:
            return None

        doc_match   = re.search(r'"""(.*?)"""', prompt, re.DOTALL)
        instruction = doc_match.group(1).strip() if doc_match else prompt.strip()

        if task_type == "fix":
            # fix task: buggy → canonical; map to patch_file
            if not buggy or not solution:
                return None
            raw_response = solution
            extra = {"buggy": buggy, "schema_type": "patch", "language": language}
        else:
            raw_response = (prompt + solution) if solution else prompt
            extra = {"schema_type": "humaneval", "language": language}

        return self._make_base(
            instruction, raw_response,
            source="humanevalpack",
            source_id=task_id,
            execution_verified=True,
            extra=extra,
        )

    # ── Code-Feedback (OpenCodeInterpreter) ──────────────────────────────────
    def _extract_code_feedback(self, raw: Dict) -> Optional[Dict]:
        query    = raw.get("query", "")
        answer   = raw.get("answer", "")
        feedback = raw.get("code_feedback", [])

        if not query or not answer:
            return None

        has_execution = bool(feedback)
        return self._make_base(
            query, answer,
            source="code-feedback",
            execution_verified=has_execution,
            extra={"code_feedback": feedback[:1], "schema_type": "code_with_execution"},
        )

    # ── OrcaAgentInstruct ────────────────────────────────────────────────────
    def _extract_orca_agent(self, raw: Dict) -> Optional[Dict]:
        messages = raw.get("messages", [])
        if not messages:
            return None

        user_content = ""
        assistant_content = ""
        for msg in messages:
            role    = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user" and not user_content:
                user_content = content
            elif role == "assistant" and not assistant_content:
                assistant_content = content

        if not user_content or not assistant_content:
            return None

        return self._make_base(
            user_content, assistant_content,
            source="orca-agentinstruct",
        )

    # ── BFCL (eval set only) ─────────────────────────────────────────────────
    def _extract_bfcl(self, raw: Dict) -> Optional[Dict]:
        instruction = raw.get("question", raw.get("prompt", ""))
        answer      = raw.get("ground_truth", raw.get("answer", ""))
        if not instruction or not answer:
            return None
        return self._make_base(
            instruction, str(answer),
            source="bfcl",
            execution_verified=True,
        )

    # ── Generic JSONL (synthetic + custom) ───────────────────────────────────
    def _extract_jsonl_generic(self, raw: Dict) -> Optional[Dict]:
        # Try common field names in order of preference
        instruction = (
            raw.get("instruction") or raw.get("user") or
            raw.get("query") or raw.get("prompt") or ""
        )
        response = (
            raw.get("response") or raw.get("output") or
            raw.get("assistant") or raw.get("answer") or ""
        )
        if not instruction or not response:
            return None

        return self._make_base(
            instruction, response,
            source=raw.get("_source", "custom"),
            is_synthetic=raw.get("is_synthetic", False),
            extra=raw.get("_extra", {}),
        )
