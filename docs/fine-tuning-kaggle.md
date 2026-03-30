# Fine-Tuning Codey-v2 on Kaggle

This guide covers the full end-to-end workflow for fine-tuning both Codey-v2 models using your own training data and a free Kaggle GPU.

---

## What gets trained

| Model | Port | What improves |
|-------|------|---------------|
| Qwen2.5-0.5B-Instruct | 8081 | Breaking tasks into numbered planning steps |
| Qwen2.5-Coder-7B-Instruct | 8080 | Tool use, code generation, Termux commands |

Both models are trained with QLoRA (4-bit quantized base + LoRA adapters) so they fit in Kaggle's free 16 GB GPU. Output is Q4_K_M GGUF files — the exact format your phone's llama-server uses.

---

## Step 1 — Generate training data (on your phone)

Run the pipeline in Termux from the codey-v2 directory:

```bash
cd ~/codey-v2

# Quick option — no internet needed, ~5,800 synthetic records:
python pipeline/run.py --synthetic-only

# Better option — streams real datasets from HuggingFace:
python pipeline/run.py --datasets phase1 --max-records 3000

# Best option — more data, longer runtime:
python pipeline/run.py --datasets phase1
```

Output file: `~/codey-v2/pipeline_output/training_data.jsonl`

See `docs/pipeline.md` for full pipeline documentation.

---

## Step 2 — Copy files to your Downloads folder

You need two files in your Downloads folder — the notebook to upload to Kaggle, and the training data to upload as a Kaggle dataset.

If you haven't set up Termux storage access yet, run this first (only needed once):

```bash
termux-setup-storage
```

Then copy both files:

```bash
# The Kaggle notebook
cp ~/codey-v2/notebooks/codey_finetune_kaggle.ipynb ~/storage/downloads/

# The training data
cp ~/codey-v2/pipeline_output/training_data.jsonl ~/storage/downloads/
```

Both files will now appear in your phone's Downloads folder and can be uploaded from there.

---

## Step 3 — Upload training data to Kaggle

1. Go to **kaggle.com → Datasets → New Dataset**
2. Upload `training_data.jsonl` from your Downloads folder
3. Name the dataset exactly: `codey-training-data`
4. Make it private or public (either works)
5. Click **Create**

---

## Step 4 — Set up the Kaggle notebook

1. Go to **kaggle.com → Code → New Notebook**
2. Click **File → Import Notebook** and upload `codey_finetune_kaggle.ipynb` from your Downloads folder
3. In the right panel, set **Accelerator → GPU T4 x1** (free, required)
4. Click **Add Data** → search for your `codey-training-data` dataset → add it

---

## Step 5 — Get a HuggingFace token

1. Go to **huggingface.co/settings/tokens**
2. Click **New token**
3. Set type to **Write**
4. Copy the token (starts with `hf_`)

The notebook pushes your trained GGUF models to HuggingFace so you can download them on your phone.

---

## Step 6 — Configure the notebook

Open the notebook in Kaggle. Find the **CONFIGURATION** cell (second cell) and fill in:

```python
HF_TOKEN    = "hf_YOUR_TOKEN_HERE"   # paste your token here
HF_USERNAME = "your_username"         # your HuggingFace username
```

Everything else has sensible defaults. Optional settings you can adjust:

```python
MAX_RECORDS_PLANNER = 3000   # records for 0.5B training (more = better, slower)
MAX_RECORDS_CODER   = 8000   # records for 7B training
PLANNER_EPOCHS      = 3      # training passes for 0.5B
CODER_EPOCHS        = 1      # training passes for 7B (1 is enough on Kaggle)
TRAIN_PLANNER       = True   # set False to skip 0.5B
TRAIN_CODER         = True   # set False to skip 7B
QUANT               = "q4_k_m"  # quantization: q4_k_m / q5_k_m / q8_0
```

---

## Step 7 — Run the notebook

Click **Run All**. The notebook:

1. Checks the GPU is available
2. Installs Unsloth (fast fine-tuning library)
3. Loads your training data
4. Trains the 0.5B planner on multi-step task decomposition examples
5. Converts the 0.5B model to GGUF and pushes to HuggingFace
6. Frees GPU memory
7. Trains the 7B coder on the full tool-call training data
8. Converts the 7B model to GGUF and pushes to HuggingFace
9. Prints download links for both models

**Expected total time:** 3–5 hours on a free T4 GPU.

The notebook shows training loss in the output — it should decrease steadily. If it stays flat or increases, you may have too few training records.

---

## Step 8 — Download models to your phone

After the notebook finishes, your models are at:
- `https://huggingface.co/YOUR_USERNAME/qwen2.5-0.5b-codey-planner-gguf`
- `https://huggingface.co/YOUR_USERNAME/qwen2.5-coder-7b-codey-gguf`

### Option A — Download directly in Termux (recommended)

```bash
# Download the fine-tuned planner model
wget -O ~/models/qwen2.5-0.5b/planner-codey.gguf \
  https://huggingface.co/YOUR_USERNAME/qwen2.5-0.5b-codey-planner-gguf/resolve/main/unsloth.Q4_K_M.gguf

# Download the fine-tuned coder model
wget -O ~/models/qwen2.5-coder-7b/coder-codey.gguf \
  https://huggingface.co/YOUR_USERNAME/qwen2.5-coder-7b-codey-gguf/resolve/main/unsloth.Q4_K_M.gguf
```

Replace `YOUR_USERNAME` with your actual HuggingFace username.

### Option B — Download from Kaggle output to Downloads folder

The GGUF files are also saved in Kaggle's output:

1. In the Kaggle notebook, click **Output** in the right panel
2. Find `planner_gguf/` and `coder_gguf/` folders
3. Download the `.gguf` files to your phone's Downloads folder
4. In Termux, copy them to the models directory:

```bash
# Set up Termux storage access (only needed once):
termux-setup-storage

# Copy from Downloads to models:
cp ~/storage/downloads/unsloth.Q4_K_M.gguf ~/models/qwen2.5-0.5b/planner-codey.gguf
```

---

## Step 9 — Load the new models

Restart Codey-v2 to load the new weights:

```bash
codeyd2 stop
codeyd2 start
codeyd2 status
```

If your `config.json` points to the old filenames, either rename the new files to match the old names (replacing them), or update the model paths in `config.json`.

---

## Troubleshooting

**"No GPU detected"**
Go to the Kaggle notebook settings (right panel) → Accelerator → GPU T4 x1. You must enable this before running.

**"hf_YOUR_TOKEN_HERE" error**
You forgot to fill in your HuggingFace token in the Configuration cell.

**Out of memory during 7B training**
Reduce `MAX_RECORDS_CODER` to 2000–3000, or set `CODER_EPOCHS = 1`.

**Training loss not decreasing**
You have too few training records. Run the pipeline with `--datasets phase1` (without `--max-records`) to get more data.

**Download URL 404**
Check the actual filename on your HuggingFace repo page — it may differ slightly. The file will be listed under the Files tab of your HuggingFace repository.

**Kaggle session times out (9-hour limit)**
Set `TRAIN_PLANNER = False` on the first run (just train the 7B), then set `TRAIN_CODER = False` on the second run (just train the 0.5B).
