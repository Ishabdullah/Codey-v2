# Fine-tuning

Codey-v2 supports personalizing the underlying model using your own interaction history. Heavy training runs off-device on Google Colab (free tier), while your phone handles only lightweight data export and model file management.

---

## Step 1 — Export Your Interaction Data

```bash
# Export last 30 days with default quality threshold
codey2 --finetune

# Customize the export
codey2 --finetune --ft-days 60 --ft-quality 0.6 --ft-model 7b
```

| Flag | Default | Description |
|------|---------|-------------|
| `--ft-days` | 30 | Days of history to include |
| `--ft-quality` | 0.7 | Minimum quality score (0.0–1.0) |
| `--ft-model` | both | Target variant: `0.5b`, `7b`, or `both` |
| `--ft-output` | `~/Downloads/codey-finetune` | Output directory |

**Output files:**

- `codey-finetune-0.5b.jsonl` — Dataset for the 0.5B model
- `codey-finetune-7b.jsonl` — Dataset for the 7B model
- `codey-finetune-qwen-coder-0.5b.ipynb` — Colab notebook
- `codey-finetune-qwen-coder-7b.ipynb` — Colab notebook

---

## Step 2 — Train on Google Colab

1. Go to [colab.research.google.com](https://colab.research.google.com).
2. Upload the generated notebook (`codey-finetune-*.ipynb`).
3. Run all cells. Free T4 GPU takes 1–4 hours depending on model size.
4. Download `codey-lora-adapter.zip` when training completes.

Training uses [Unsloth](https://github.com/unslothai/unsloth) for 2x speed and 70% less VRAM.

---

## Step 3 — Import the Adapter

```bash
# Extract the downloaded adapter
unzip codey-lora-adapter.zip

# Import to Codey-v2
codey2 --import-lora /path/to/codey-lora-adapter --lora-model primary
```

| Flag | Default | Description |
|------|---------|-------------|
| `--lora-model` | primary | `primary` (7B) or `secondary` (0.5B) |
| `--lora-quant` | q4_0 | Quantization: `q4_0`, `q5_0`, `q8_0`, `f16` |
| `--lora-merge` | false | Merge on-device (requires llama.cpp, ~8 GB RAM for 7B) |

---

## Merging On-Device (Advanced)

If you want a single merged GGUF file instead of a base model + adapter:

```bash
# Merge on import
codey2 --import-lora /path/to/adapter --lora-model primary --lora-merge

# Or manually with llama.cpp
python ~/llama.cpp/convert-lora.py \
  --base-model ~/models/qwen2.5-coder-7b/model.gguf \
  --lora-adapter /path/to/adapter \
  --output merged.gguf

./quantize merged.gguf merged-q4.gguf q4_0
```

Merging requires ~8 GB free RAM for the 7B model and takes 5–15 minutes.

---

## Rollback

A full backup is created automatically before any import. To restore:

```bash
codey2 --rollback --lora-model primary
```

---

## Quality Tips

| Goal | Setting |
|------|---------|
| High quality, smaller dataset | `--ft-quality 0.8` or higher |
| More examples, more diversity | `--ft-quality 0.5` with `--ft-days 90` |
| Fast training for style tuning | Target the 0.5B model |
| Best reasoning improvement | Target the 7B model |
