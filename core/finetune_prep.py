#!/usr/bin/env python3
"""
Fine-tuning data preparation for Codey-v2.

Exports interaction data for off-device fine-tuning using Unsloth + Colab.
Generates ShareGPT-style JSONL datasets and ready-to-run Colab notebooks.

This module handles:
- Dataset curation from episodic/long-term memory
- Quality filtering (successful interactions, user corrections)
- ShareGPT format export (messages with system/user/assistant roles)
- Unsloth Colab notebook generation
- User instructions for training workflow

Note: All heavy training happens off-device (Colab free tier T4 GPU).
Phone only does lightweight data export + file writing.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from utils.logger import info, warning, success, error
from core.state import get_state_store
from core.memory import memory as _mem


# =============================================================================
# Dataset Curation
# =============================================================================

class DatasetCurator:
    """
    Curates high-quality fine-tuning examples from Codey-v2 interaction history.
    
    Filters by:
    - Successful interactions (no errors, task completed)
    - User corrections accepted
    - Multi-turn conversations (richer context)
    - Recent interactions (more relevant to current style)
    """
    
    def __init__(self):
        self.state = get_state_store()
    
    def get_episodic_actions(
        self,
        days: int = 30,
        min_quality: float = 0.7
    ) -> List[Dict]:
        """
        Retrieve episodic actions from the last N days.
        
        Args:
            days: Number of days to look back
            min_quality: Minimum quality score (0.0-1.0)
            
        Returns:
            List of action dictionaries
        """
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp())
        
        try:
            # Get episodic log from state
            actions_json = self.state.get("episodic_log")
            if not actions_json:
                return []
            
            actions = json.loads(actions_json)
            
            # Filter by date and quality
            filtered = []
            for action in actions:
                ts = action.get("timestamp", 0)
                if ts < cutoff_ts:
                    continue
                
                # Quality heuristics
                quality = self._calculate_quality(action)
                if quality >= min_quality:
                    action["_quality"] = quality
                    filtered.append(action)
            
            # Sort by quality descending
            filtered.sort(key=lambda x: x.get("_quality", 0), reverse=True)
            return filtered
            
        except Exception as e:
            warning(f"Failed to load episodic actions: {e}")
            return []
    
    def _calculate_quality(self, action: Dict) -> float:
        """
        Calculate quality score for an action.
        
        Heuristics:
        - Task completed successfully: +0.5
        - User accepted/corrected: +0.3
        - Multi-step task: +0.2
        - Recent (last 7 days): +0.1
        - Error occurred: -0.5
        """
        score = 0.5  # Base score
        
        # Success bonus
        if action.get("success", False):
            score += 0.3
        
        # Multi-step bonus
        if action.get("steps", 1) > 1:
            score += 0.2
        
        # Recency bonus
        ts = action.get("timestamp", 0)
        days_ago = (datetime.now().timestamp() - ts) / 86400
        if days_ago <= 7:
            score += 0.1
        
        # Error penalty
        if action.get("error"):
            score -= 0.5
        
        return max(0.0, min(1.0, score))
    
    def curate_examples(
        self,
        days: int = 30,
        min_quality: float = 0.7,
        max_examples: int = 500
    ) -> List[Dict]:
        """
        Curate fine-tuning examples from history.
        
        Args:
            days: Days to look back
            min_quality: Minimum quality threshold
            max_examples: Maximum examples to return
            
        Returns:
            List of curated examples in ShareGPT format
        """
        actions = self.get_episodic_actions(days, min_quality)
        examples = []
        
        for action in actions[:max_examples]:
            example = self._action_to_sharegpt(action)
            if example:
                examples.append(example)
        
        return examples
    
    def _action_to_sharegpt(self, action: Dict) -> Optional[Dict]:
        """
        Convert an episodic action to ShareGPT format.
        
        ShareGPT format:
        {
            "conversations": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
        """
        user_msg = action.get("user_message", "")
        assistant_msg = action.get("response", "")
        
        if not user_msg or not assistant_msg:
            return None
        
        # Build system prompt from preferences
        system_prompt = self._build_system_prompt(action)
        
        return {
            "conversations": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg}
            ],
            "metadata": {
                "source": "codey-v2",
                "quality": action.get("_quality", 0.5),
                "timestamp": action.get("timestamp", 0),
                "tools_used": action.get("tools_used", []),
            }
        }
    
    def _build_system_prompt(self, action: Dict) -> str:
        """Build system prompt from learned preferences."""
        from core.learning import get_learning_manager
        
        learning = get_learning_manager()
        prefs = learning.get_all_preferences()
        
        parts = ["You are Codey-v2, a helpful AI coding assistant."]
        
        # Add learned preferences
        if prefs.get("test_framework"):
            parts.append(f"User prefers {prefs['test_framework']} for testing.")
        if prefs.get("code_style"):
            parts.append(f"User prefers {prefs['code_style']} code style.")
        if prefs.get("naming_convention"):
            parts.append(f"User prefers {prefs['naming_convention']} naming.")
        
        return " ".join(parts)


# =============================================================================
# Dataset Export
# =============================================================================

def export_dataset(
    examples: List[Dict],
    output_path: str,
    model_variant: str = "both"
) -> Tuple[str, int]:
    """
    Export examples to ShareGPT-style JSONL.
    
    Args:
        examples: List of ShareGPT examples
        output_path: Output directory
        model_variant: "1.5b", "7b", or "both"
        
    Returns:
        Tuple of (output_file, example_count)
    """
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if model_variant == "both":
        # Export single combined file
        output_file = output_dir / "codey-finetune-combined.jsonl"
        count = _write_jsonl(examples, output_file)
        return str(output_file), count
    
    elif model_variant == "1.5b":
        # Filter for simpler examples (single-turn, style-focused)
        simple = [e for e in examples if len(e["conversations"]) <= 3]
        output_file = output_dir / "codey-finetune-1.5b.jsonl"
        count = _write_jsonl(simple, output_file)
        return str(output_file), count
    
    elif model_variant == "7b":
        # Include complex multi-turn examples
        output_file = output_dir / "codey-finetune-7b.jsonl"
        count = _write_jsonl(examples, output_file)
        return str(output_file), count
    
    else:
        raise ValueError(f"Unknown model variant: {model_variant}")


def _write_jsonl(examples: List[Dict], output_file: Path) -> int:
    """Write examples to JSONL file."""
    count = 0
    with open(output_file, "w", encoding="utf-8") as f:
        for example in examples:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
            count += 1
    return count


# =============================================================================
# Colab Notebook Generation
# =============================================================================

UNSLOTH_NOTEBOOK_TEMPLATE = '''# Codey-v2 Fine-tuning with Unsloth
# Model: {model_name}
# Generated: {generated_date}

"""
This notebook fine-tunes {model_name} on your Codey-v2 interaction data.

Requirements:
- Google Colab free tier (T4 GPU, 16GB VRAM)
- Unsloth library (pre-installed in this notebook)
- Your exported JSONL dataset

Steps:
1. Upload your codey-finetune-*.jsonl file
2. Run all cells
3. Download the LoRA adapter
4. Import back to Codey-v2 with: codey2 --import-lora /path/to/adapter

Estimated time: 1-4 hours on free T4 GPU
"""

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Install Unsloth (if not pre-installed)
# ─────────────────────────────────────────────────────────────────────────────
!pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
!pip install --no-deps "xformers<0.0.27" trl peft accelerate bitsandbytes

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Load Your Dataset
# ─────────────────────────────────────────────────────────────────────────────
from google.colab import files
import json

print("Upload your codey-finetune-*.jsonl file:")
uploaded = files.upload()

# Read the uploaded file
jsonl_file = list(uploaded.keys())[0]
with open(jsonl_file, "r") as f:
    dataset = [json.loads(line) for line in f]

print(f"Loaded {{len(dataset)}} examples")

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Load Base Model with Unsloth
# ─────────────────────────────────────────────────────────────────────────────
from unsloth import FastLanguageModel

# Model selection
{model_loading_code}

# Load model with 4-bit quantization (saves VRAM)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=model_id,
    max_seq_length=2048,
    load_in_4bit=True,  # 4-bit quantization
    fast_inference=True,  # Enable fast inference
)

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Configure LoRA Adapters
# ─────────────────────────────────────────────────────────────────────────────
model = FastLanguageModel.get_peft_model(
    model,
    r={lora_r},  # LoRA rank (16-32 recommended)
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj"
    ],
    lora_alpha={lora_alpha},
    lora_dropout=0,  # Optimized for performance
    bias="none",
)

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Prepare Training Data
# ─────────────────────────────────────────────────────────────────────────────
from trl import SFTTrainer
from transformers import TrainingArguments

# Format conversations for training
def format_conversation(example):
    conversations = example["conversations"]
    text = ""
    for msg in conversations:
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            text += f"User: {{content}}\\n\\n"
        elif role == "assistant":
            text += f"Assistant: {{content}}"
    return {{"text": text}}

formatted_dataset = [format_conversation(ex) for ex in dataset]

# Training arguments
training_args = TrainingArguments(
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    warmup_steps=5,
    max_steps={max_steps},  # Adjust based on dataset size
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    output_dir="outputs",
    optim="adamw_8bit",
    seed=42,
)

# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Train!
# ─────────────────────────────────────────────────────────────────────────────
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=formatted_dataset,
    dataset_text_field="text",
    max_seq_length=2048,
    args=training_args,
)

print("Starting training...")
trainer.train()

# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Save and Download Adapter
# ─────────────────────────────────────────────────────────────────────────────
# Save the LoRA adapter
adapter_path = "codey-lora-adapter"
model.save_pretrained(adapter_path)
tokenizer.save_pretrained(adapter_path)

# Create a zip file for download
import shutil
shutil.make_archive("codey-lora-adapter", "zip", adapter_path)

# Download
files.download("codey-lora-adapter.zip")

print("""
─────────────────────────────────────────────────────────────────
✓ Training complete!

Next steps:
1. Download the codey-lora-adapter.zip file
2. Extract it on your device
3. Import to Codey-v2: codey2 --import-lora /path/to/codey-lora-adapter

To merge with base model (optional):
  python merge_adapter.py --base {model_id} --adapter codey-lora-adapter --output merged-model
─────────────────────────────────────────────────────────────────
""")
'''


def generate_notebook(
    model_variant: str,
    output_path: str,
    lora_r: int = 16,
    lora_alpha: int = 16,
    max_steps: int = 200
) -> str:
    """
    Generate Unsloth Colab notebook for fine-tuning.
    
    Args:
        model_variant: "1.5b" or "7b"
        output_path: Output directory
        lora_r: LoRA rank
        lora_alpha: LoRA alpha
        max_steps: Maximum training steps
        
    Returns:
        Path to generated notebook
    """
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Model configuration
    if model_variant == "1.5b":
        model_name = "Qwen2.5-1.5B-Instruct"
        model_id = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
        notebook_name = "codey-finetune-qwen-coder-1.5b.ipynb"
    elif model_variant == "7b":
        model_name = "Qwen2.5-Coder-7B-Instruct"
        model_id = "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"
        notebook_name = "codey-finetune-qwen-coder-7b.ipynb"
    else:
        raise ValueError(f"Unknown model variant: {model_variant}")
    
    # Generate notebook content
    notebook_content = UNSLOTH_NOTEBOOK_TEMPLATE.format(
        model_name=model_name,
        model_id=model_id,
        model_loading_code=f'model_id = "{model_id}"',
        lora_r=lora_r,
        lora_alpha=lora_alpha,
        max_steps=max_steps,
        generated_date=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    
    # Convert to Jupyter notebook format
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [f"# {model_name} Fine-tuning with Unsloth\n\n"]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": notebook_content.split("\n")
            }
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python",
                "version": "3.10.0"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 4
    }
    
    output_file = output_dir / notebook_name
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(notebook, f, indent=2)
    
    info(f"Generated notebook: {output_file}")
    return str(output_file)


# =============================================================================
# User Instructions
# =============================================================================

def print_instructions(
    dataset_path: str,
    notebook_path: str,
    model_variant: str
):
    """Print step-by-step instructions for the user."""
    
    instructions = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    Codey-v2 Fine-tuning Workflow                             ║
╠══════════════════════════════════════════════════════════════════════════════╣

✓ Dataset exported: {dataset_path}
✓ Notebook generated: {notebook_path}

────────────────────────────────────────────────────────────────────────────────
STEP 1: Open Google Colab
────────────────────────────────────────────────────────────────────────────────
  1. Go to https://colab.research.google.com
  2. Click "Upload notebook"
  3. Upload: {notebook_path}

────────────────────────────────────────────────────────────────────────────────
STEP 2: Upload Dataset
────────────────────────────────────────────────────────────────────────────────
  1. Run the first cell in the notebook
  2. When prompted, upload: {dataset_path}
  3. Wait for dataset to load

────────────────────────────────────────────────────────────────────────────────
STEP 3: Train
────────────────────────────────────────────────────────────────────────────────
  1. Click "Runtime" → "Run all"
  2. Training will take 1-4 hours (free T4 GPU)
  3. Do NOT close the browser tab

────────────────────────────────────────────────────────────────────────────────
STEP 4: Download Adapter
────────────────────────────────────────────────────────────────────────────────
  1. After training completes, the adapter will auto-download
  2. File: codey-lora-adapter.zip
  3. Transfer to your Android device

────────────────────────────────────────────────────────────────────────────────
STEP 5: Import to Codey-v2
────────────────────────────────────────────────────────────────────────────────
  On your device:
  
  1. Extract the zip file:
     unzip codey-lora-adapter.zip
  
  2. Import the adapter:
     codey2 --import-lora /path/to/codey-lora-adapter --model {model_variant}
  
  3. Test the fine-tuned model:
     codey2 "test the new model"

────────────────────────────────────────────────────────────────────────────────
TROUBLESHOOTING
────────────────────────────────────────────────────────────────────────────────
• Out of memory: Reduce batch_size to 1 in notebook
• Training too slow: Use 1.5B model instead of 7B
• Poor results: Increase max_steps or lower min_quality threshold
• Import fails: Ensure adapter folder contains adapter_config.json

────────────────────────────────────────────────────────────────────────────────
NOTES
────────────────────────────────────────────────────────────────────────────────
• Free Colab T4 GPU: 16GB VRAM, ~12 hour session limit
• 7B model: ~4 hours training, better quality
• 1.5B model: ~1 hour training, faster iteration
• LoRA adapter size: ~100-500MB (much smaller than full model)

╚══════════════════════════════════════════════════════════════════════════════╝
"""
    print(instructions)


# =============================================================================
# Main Entry Point
# =============================================================================

def prepare_finetune_data(
    days: int = 30,
    min_quality: float = 0.7,
    model_variant: str = "both",
    output_dir: str = None
) -> Dict[str, str]:
    """
    Main entry point for fine-tuning data preparation.
    
    Args:
        days: Days of history to include
        min_quality: Minimum quality threshold
        model_variant: "1.5b", "7b", or "both"
        output_dir: Output directory (default: ~/Downloads)
        
    Returns:
        Dict with paths to generated files
    """
    if output_dir is None:
        output_dir = str(Path.home() / "Downloads" / "codey-finetune")
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    info(f"Curating examples from last {days} days (min_quality={min_quality})...")
    
    # Curate examples
    curator = DatasetCurator()
    examples = curator.curate_examples(days, min_quality)
    
    if not examples:
        warning("No high-quality examples found. Try lowering min_quality or increasing days.")
        return {"error": "No examples found"}
    
    info(f"Curated {len(examples)} examples")
    
    # Export dataset(s)
    results = {}
    
    if model_variant == "both":
        # Export combined + both variants
        for variant in ["1.5b", "7b"]:
            path, count = export_dataset(examples, str(output_path), variant)
            results[f"dataset_{variant}"] = path
            info(f"Exported {count} examples to {path}")
            
            # Generate notebook
            nb_path = generate_notebook(variant, str(output_path))
            results[f"notebook_{variant}"] = nb_path
    else:
        path, count = export_dataset(examples, str(output_path), model_variant)
        results["dataset"] = path
        info(f"Exported {count} examples to {path}")
        
        nb_path = generate_notebook(model_variant, str(output_path))
        results["notebook"] = nb_path
    
    # Print instructions
    variant_key = f"dataset_{model_variant}" if model_variant == "both" else "dataset"
    nb_key = f"notebook_{model_variant}" if model_variant == "both" else "notebook"
    
    if model_variant == "both":
        print_instructions(
            results["dataset_1.5b"],
            results["notebook_1.5b"],
            "1.5b"
        )
        print_instructions(
            results["dataset_7b"],
            results["notebook_7b"],
            "7b"
        )
    else:
        print_instructions(
            results[variant_key],
            results[nb_key],
            model_variant
        )
    
    return results
