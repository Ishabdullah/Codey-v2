#!/usr/bin/env python3
"""
Codey-v2 Tools Embedding Pipeline — CLI entry point.

Usage:
  python pipeline/run.py --help
  python pipeline/run.py --datasets glaive mbpp python18k --phase 1
  python pipeline/run.py --datasets all --phase 1 --max-records 5000
  python pipeline/run.py --synthetic-only
  python pipeline/run.py --datasets mbpp --embed --output-dir ./my_output
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure repo root is on path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from pipeline.ingestion         import HFIngestor, JSONLIngestor
from pipeline.normalization     import NormalizationPipeline
from pipeline.transformation    import TransformationEngine
from pipeline.embedding         import EmbeddingPipeline
from pipeline.storage           import SQLiteMetadataStore, VectorStore
from pipeline.export            import Exporter
from pipeline.synthetic         import write_synthetic_corpora
from pipeline.embedding.embedder import build_embed_text


# ── Dataset registry ──────────────────────────────────────────────────────────

PHASE1_DATASETS = {
    "glaive":   "glaiveai/glaive-function-calling-v2",
    "hermes":   "NousResearch/hermes-function-calling-v1",
    "mbpp":     "google-research-datasets/mbpp",
    "humaneval":"evalplus/humanevalplus",
    "python18k":"iamtarun/python_code_instructions_18k_alpaca",
}

PHASE2_DATASETS = {
    "xlam":     "lockon/xlam-function-calling-60k",
    "code122k": "TokenBender/code_instructions_122k_alpaca_style",
    "codefeedback": "m-a-p/Code-Feedback",
    "apigen":   "argilla/apigen-function-calling",
}

PHASE3_DATASETS = {
    "bigcodebench":  "bigcode/bigcodebench",
    "humanevalpack": "bigcode/humanevalpack",
    "alpaca":        "yahma/alpaca-cleaned",
    "codesearchnet": "Nan-Do/instructional_code-search-net-python",
    "orca":          "microsoft/orca-agentinstruct-1M-v1",
}

ALL_DATASETS = {**PHASE1_DATASETS, **PHASE2_DATASETS, **PHASE3_DATASETS}

DATASET_SPLITS = {
    "google-research-datasets/mbpp": "train",
    "evalplus/humanevalplus":         "test",
    "bigcode/bigcodebench":           "v0.1.2",
    "bigcode/humanevalpack":          "test",
    "openai/openai_humaneval":        "test",
}


def _resolve_datasets(names: list) -> dict:
    """Turn CLI dataset shortnames into {shortname: hf_path} dict."""
    if "all" in names:
        return dict(PHASE1_DATASETS)  # default to phase 1 for 'all'
    if "phase1" in names:
        return dict(PHASE1_DATASETS)
    if "phase2" in names:
        return dict(PHASE2_DATASETS)
    if "phase3" in names:
        return dict(PHASE3_DATASETS)

    result = {}
    for name in names:
        if name in ALL_DATASETS:
            result[name] = ALL_DATASETS[name]
        else:
            print(f"  [warn] Unknown dataset shortname: '{name}' — skipping")
    return result


def run_pipeline(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieval_dir = output_dir / "retrieval"
    retrieval_dir.mkdir(exist_ok=True)

    print(f"\nCodey-v2 Tools Embedding Pipeline")
    print(f"{'='*50}")
    print(f"  Output dir:  {output_dir}")
    print(f"  Min quality: {args.min_quality}")
    print(f"  Max records: {args.max_records or 'unlimited'} per dataset")
    print(f"  Embed:       {args.embed}")
    print()

    normalizer  = NormalizationPipeline(min_quality=args.min_quality)
    transformer = TransformationEngine(skip_invalid=True)

    embed_pipeline = None
    vector_store   = None
    sqlite_store   = None

    if args.embed:
        embed_pipeline = EmbeddingPipeline(nomic_port=8082)
        print(f"  Embedding backend: {embed_pipeline.backend_name} ({embed_pipeline.dim}d)")
        vector_store = VectorStore(
            dim=embed_pipeline.dim,
            index_path=str(retrieval_dir / "index"),
        )
        sqlite_store = SQLiteMetadataStore(str(retrieval_dir / "metadata.db"))

    # ── Synthetic corpora ──────────────────────────────────────────────────────
    synthetic_dir = output_dir / "synthetic"
    if not args.skip_synthetic:
        print("  Generating synthetic corpora...")
        synth_paths = write_synthetic_corpora(str(synthetic_dir))
        print()
    else:
        synth_paths = {}

    # ── Build ingestor list ────────────────────────────────────────────────────
    ingestors = []

    # HF datasets
    if not args.synthetic_only:
        dataset_map = _resolve_datasets(args.datasets or ["phase1"])
        for short, hf_path in dataset_map.items():
            split = DATASET_SPLITS.get(hf_path, "train")
            ingestors.append(HFIngestor(
                dataset_path=hf_path,
                split=split,
                max_records=args.max_records,
            ))

    # Synthetic JSONL datasets
    if not args.skip_synthetic:
        for name, path in synth_paths.items():
            schema = "jsonl_generic"
            ingestors.append(JSONLIngestor(path, schema_type=schema, max_records=args.max_records))

    # Any extra JSONL files
    for extra_path in (args.extra_jsonl or []):
        ingestors.append(JSONLIngestor(extra_path))

    if not ingestors:
        print("  No datasets selected. Use --datasets or --synthetic-only.")
        return

    # ── Main pipeline loop ────────────────────────────────────────────────────
    embed_buffer: list = []  # (record, embed_text) pairs for batch embedding

    with Exporter(str(output_dir)) as exporter:
        for ingestor in ingestors:
            print(f"  Processing: {ingestor.name()} ...")
            t0 = time.time()
            source_count = 0
            source_out   = 0

            for raw in ingestor.ingest():
                exporter.increment_input()
                source_count += 1

                # Normalize
                intermediate = normalizer.process(raw)
                if intermediate is None:
                    continue

                # Handle pre-built synthetic tool_calls
                if intermediate.get("_extra", {}).get("tool_calls_prebuilt"):
                    tc = intermediate["_extra"]["tool_calls_prebuilt"]
                    record = {
                        "user": intermediate["instruction"],
                        "tool_calls": tc,
                        "metadata": transformer._build_metadata(intermediate, tc),
                    }
                else:
                    record = transformer.transform(intermediate)
                    if record is None:
                        exporter.write_error(transformer.errors[-1] if transformer.errors else {})
                        continue

                exporter.write_record(record)
                source_out += 1

                if args.embed:
                    embed_text = build_embed_text(record)
                    embed_buffer.append((record, embed_text))

                    # Flush buffer in batches
                    if len(embed_buffer) >= 256:
                        _flush_embeddings(embed_buffer, embed_pipeline, vector_store, sqlite_store)
                        embed_buffer.clear()

            elapsed = time.time() - t0
            print(f"    → {source_out:,} / {source_count:,} records in {elapsed:.1f}s")

        # Flush remaining embeddings
        if args.embed and embed_buffer:
            _flush_embeddings(embed_buffer, embed_pipeline, vector_store, sqlite_store)
            embed_buffer.clear()

        # Write transformer errors
        for err in transformer.errors:
            exporter.write_error(err)

    # ── Save vector store ─────────────────────────────────────────────────────
    if args.embed and vector_store:
        vector_store.save()
        sqlite_store.close()
        print(f"\n  Retrieval index: {retrieval_dir}")
        print(f"  Vectors stored:  {vector_store.count():,}")

    exporter.print_summary()


def _flush_embeddings(
    buffer: list,
    embed_pipeline,
    vector_store: VectorStore,
    sqlite_store: SQLiteMetadataStore,
) -> None:
    """Embed a batch and persist to vector store + SQLite."""
    records    = [r for r, _ in buffer]
    embed_texts = [t for _, t in buffer]

    vectors = embed_pipeline._get_backend().embed_batch(embed_texts)

    insert_batch = []
    for record, vec in zip(records, vectors):
        if vec is None:
            continue
        vid = vector_store.add(vec)
        et  = build_embed_text(record)
        insert_batch.append((vid, record, et))

    if insert_batch:
        sqlite_store.insert_batch(insert_batch)


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Codey-v2 Tools Embedding Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Dataset shortnames:
  phase1        glaive, hermes, mbpp, humaneval, python18k  (default)
  phase2        xlam, code122k, codefeedback, apigen
  phase3        bigcodebench, humanevalpack, alpaca, codesearchnet, orca
  all           phase1 (use --phase for others)

  Individual:   glaive hermes mbpp humaneval python18k xlam code122k ...

Examples:
  python pipeline/run.py
  python pipeline/run.py --datasets phase1 --max-records 1000
  python pipeline/run.py --datasets glaive mbpp --embed
  python pipeline/run.py --synthetic-only
        """,
    )

    p.add_argument(
        "--datasets", nargs="*", default=["phase1"],
        help="Dataset shortnames or phase (default: phase1)",
    )
    p.add_argument(
        "--output-dir", default="./pipeline_output",
        help="Output directory (default: ./pipeline_output)",
    )
    p.add_argument(
        "--min-quality", type=float, default=0.5,
        help="Minimum quality score 0.0–1.0 (default: 0.5)",
    )
    p.add_argument(
        "--max-records", type=int, default=None,
        help="Max records per dataset (default: unlimited)",
    )
    p.add_argument(
        "--embed", action="store_true",
        help="Generate embeddings and build retrieval index",
    )
    p.add_argument(
        "--skip-synthetic", action="store_true",
        help="Skip synthetic corpus generation",
    )
    p.add_argument(
        "--synthetic-only", action="store_true",
        help="Generate synthetic corpora only (no HF datasets)",
    )
    p.add_argument(
        "--extra-jsonl", nargs="*", default=[],
        help="Additional local JSONL files to include",
    )
    p.add_argument(
        "--force-local-embed", action="store_true",
        help="Use sentence-transformers instead of nomic server",
    )

    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
