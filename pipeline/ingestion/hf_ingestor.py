"""
HuggingFace dataset ingestor.

Streams records from any HF dataset without downloading the full corpus.
Each dataset has a schema_type that tells the normalizer how to read its fields.
"""

from typing import Iterator, Dict, Optional
from .base import BaseIngestor


# Registered datasets: maps HF path → schema_type
# schema_type tells the normalizer which field extractor to use.
REGISTERED_DATASETS = {
    "glaiveai/glaive-function-calling-v2":          "glaive_fc",
    "NousResearch/hermes-function-calling-v1":       "hermes_fc",
    "lockon/xlam-function-calling-60k":              "xlam_fc",
    "argilla/apigen-function-calling":               "xlam_fc",
    "iamtarun/python_code_instructions_18k_alpaca":  "alpaca_code",
    "TokenBender/code_instructions_122k_alpaca_style": "alpaca_code",
    "Nan-Do/instructional_code-search-net-python":   "codesearchnet",
    "google-research-datasets/mbpp":                 "mbpp",
    "evalplus/humanevalplus":                        "humaneval",
    "bigcode/bigcodebench":                          "bigcodebench",
    "bigcode/humanevalpack":                         "humanevalpack",
    "yahma/alpaca-cleaned":                          "alpaca_general",
    "microsoft/orca-agentinstruct-1M-v1":            "orca_agent",
    "m-a-p/Code-Feedback":                           "code_feedback",
    "gorilla-llm/Berkeley-Function-Calling-Leaderboard": "bfcl",
}


class HFIngestor(BaseIngestor):
    """
    Stream records from a HuggingFace dataset.

    Args:
        dataset_path:  HF dataset identifier (e.g. "glaiveai/glaive-function-calling-v2")
        split:         Dataset split to load (default "train")
        max_records:   Stop after this many records (None = all)
        subset:        Dataset config/subset name if required
        schema_type:   Override auto-detected schema type
    """

    def __init__(
        self,
        dataset_path: str,
        split: str = "train",
        max_records: Optional[int] = None,
        subset: Optional[str] = None,
        schema_type: Optional[str] = None,
    ):
        self.dataset_path = dataset_path
        self.split = split
        self.max_records = max_records
        self.subset = subset
        self._schema_type = schema_type or REGISTERED_DATASETS.get(dataset_path, "alpaca_code")

    def name(self) -> str:
        return self.dataset_path.split("/")[-1]

    @property
    def schema_type(self) -> str:
        return self._schema_type

    def ingest(self) -> Iterator[Dict]:
        try:
            from datasets import load_dataset
        except ImportError:
            raise RuntimeError("datasets library not installed. Run: pip install datasets")

        load_kwargs = {
            "streaming": True,
            "split": self.split,
            "trust_remote_code": False,
        }
        if self.subset:
            load_kwargs["name"] = self.subset

        try:
            ds = load_dataset(self.dataset_path, **load_kwargs)
        except Exception as e:
            raise RuntimeError(f"Failed to load {self.dataset_path}: {e}")

        count = 0
        for record in ds:
            if self.max_records is not None and count >= self.max_records:
                break
            # Tag every record with its source info for the normalizer
            record["_source"] = self.dataset_path
            record["_schema_type"] = self._schema_type
            yield dict(record)
            count += 1
