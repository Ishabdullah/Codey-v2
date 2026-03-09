#!/usr/bin/env python3
"""
LoRA adapter import and merge for Codey-v2.

Handles:
- Importing LoRA adapters trained with Unsloth
- Merging adapters with base model using llama.cpp tools
- Quantizing merged model to GGUF format
- Hot-swapping to the fine-tuned model

Note: Heavy merging/quantization happens off-device if possible.
On-device merge requires llama.cpp with full model loading.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

from utils.logger import info, warning, success, error
from utils.config import MODEL_PATH, SECONDARY_MODEL_PATH, MODEL_CONFIG


# =============================================================================
# LoRA Adapter Validation
# =============================================================================

def validate_lora_adapter(adapter_path: str) -> Tuple[bool, str]:
    """
    Validate a LoRA adapter directory.
    
    Checks for:
    - adapter_config.json (LoRA configuration)
    - adapter_model.safetensors or adapter_model.bin (weights)
    - tokenizer files (optional but recommended)
    
    Args:
        adapter_path: Path to adapter directory
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    adapter_dir = Path(adapter_path)
    
    if not adapter_dir.exists():
        return False, f"Adapter directory not found: {adapter_path}"
    
    if not adapter_dir.is_dir():
        return False, f"Not a directory: {adapter_path}"
    
    # Required files
    required_files = ["adapter_config.json"]
    optional_files = ["adapter_model.safetensors", "adapter_model.bin"]
    
    missing = []
    for f in required_files:
        if not (adapter_dir / f).exists():
            missing.append(f)
    
    if missing:
        return False, f"Missing required files: {', '.join(missing)}"
    
    # Check for model weights (at least one format)
    has_weights = any((adapter_dir / f).exists() for f in optional_files)
    if not has_weights:
        return False, "No adapter weights found (need .safetensors or .bin)"
    
    # Read and validate config
    try:
        with open(adapter_dir / "adapter_config.json") as f:
            config = json.load(f)
        
        # Check for LoRA-specific fields
        if "r" not in config:
            warning("adapter_config.json missing 'r' (LoRA rank)")
        if "target_modules" not in config:
            warning("adapter_config.json missing 'target_modules'")
            
    except json.JSONDecodeError as e:
        return False, f"Invalid adapter_config.json: {e}"
    
    return True, "Valid adapter"


def get_adapter_info(adapter_path: str) -> Dict:
    """
    Get information about a LoRA adapter.
    
    Args:
        adapter_path: Path to adapter directory
        
    Returns:
        Dict with adapter information
    """
    adapter_dir = Path(adapter_path)
    info_dict = {
        "path": str(adapter_dir),
        "size_mb": 0,
        "base_model": "unknown",
        "lora_r": "unknown",
        "lora_alpha": "unknown",
    }
    
    # Calculate size
    total_size = sum(f.stat().st_size for f in adapter_dir.rglob("*") if f.is_file())
    info_dict["size_mb"] = total_size / (1024 * 1024)
    
    # Read config
    config_path = adapter_dir / "adapter_config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            info_dict["base_model"] = config.get("base_model_name_or_path", "unknown")
            info_dict["lora_r"] = config.get("r", "unknown")
            info_dict["lora_alpha"] = config.get("lora_alpha", "unknown")
        except:
            pass
    
    return info_dict


# =============================================================================
# Model Merging (llama.cpp)
# =============================================================================

def merge_lora_with_llama_cpp(
    adapter_path: str,
    base_model_path: str,
    output_path: str,
    quantize: str = "q4_0"
) -> Tuple[bool, str]:
    """
    Merge LoRA adapter with base model using llama.cpp tools.
    
    This requires:
    - llama.cpp with Python bindings
    - Full base model loaded in memory
    - Sufficient storage for merged model
    
    Args:
        adapter_path: Path to LoRA adapter
        base_model_path: Path to base GGUF model
        output_path: Output path for merged model
        quantize: Quantization level (q4_0, q5_0, q8_0, f16)
        
    Returns:
        Tuple of (success, message)
    """
    adapter_dir = Path(adapter_path)
    base_model = Path(base_model_path)
    output = Path(output_path)
    
    # Validate inputs
    valid, msg = validate_lora_adapter(adapter_path)
    if not valid:
        return False, msg
    
    if not base_model.exists():
        return False, f"Base model not found: {base_model_path}"
    
    # Check for llama.cpp tools
    llama_dir = Path.home() / "llama.cpp"
    if not llama_dir.exists():
        return False, "llama.cpp not found. Install with: git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp"
    
    # Try Python-based merge first (preferred)
    try:
        return _merge_with_python(adapter_dir, base_model, output, quantize)
    except Exception as e:
        warning(f"Python merge failed: {e}, trying shell script...")
        return _merge_with_shell(adapter_dir, base_model, output, quantize)


def _merge_with_python(
    adapter_dir: Path,
    base_model: Path,
    output: Path,
    quantize: str
) -> Tuple[bool, str]:
    """Merge using llama.cpp Python bindings."""
    
    # Check if we can import llama_cpp
    try:
        from llama_cpp import Llama
    except ImportError:
        raise ImportError("llama-cpp-python not installed")
    
    info("Loading base model...")
    try:
        # Load base model
        llm = Llama(
            model_path=str(base_model),
            n_ctx=MODEL_CONFIG["n_ctx"],
            n_threads=MODEL_CONFIG["n_threads"],
            verbose=False
        )
    except Exception as e:
        return False, f"Failed to load base model: {e}"
    
    info("Applying LoRA adapter...")
    try:
        # Apply LoRA
        llm.apply_lora_from_disk(
            str(adapter_dir),
            base_model=str(base_model)
        )
    except Exception as e:
        return False, f"Failed to apply LoRA: {e}"
    
    info("Saving merged model...")
    try:
        # Save merged model
        llm.save_model(str(output))
        success(f"Merged model saved to {output}")
        return True, f"Merged model saved to {output}"
    except Exception as e:
        return False, f"Failed to save merged model: {e}"


def _merge_with_shell(
    adapter_dir: Path,
    base_model: Path,
    output: Path,
    quantize: str
) -> Tuple[bool, str]:
    """Merge using llama.cpp shell scripts."""
    
    llama_dir = Path.home() / "llama.cpp"
    convert_script = llama_dir / "convert-lora.py"
    quantize_script = llama_dir / "quantize"
    
    # Check for convert script
    if not convert_script.exists():
        return False, "convert-lora.py not found in llama.cpp"
    
    # Run conversion
    info("Running convert-lora.py...")
    temp_merged = output.parent / "temp-merged-f16.gguf"
    
    cmd = [
        "python", str(convert_script),
        "--base-model", str(base_model),
        "--lora-adapter", str(adapter_dir),
        "--outfile", str(temp_merged)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            return False, f"Conversion failed: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "Conversion timed out (took >1 hour)"
    except Exception as e:
        return False, f"Conversion error: {e}"
    
    # Quantize if requested
    if quantize != "f16":
        info(f"Quantizing to {quantize}...")
        if not quantize_script.exists():
            warning("quantize not found, keeping F16")
            temp_merged.rename(output)
            return True, f"Merged model saved to {output} (F16)"
        
        cmd = [str(quantize_script), str(temp_merged), str(output), quantize]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                return False, f"Quantization failed: {result.stderr}"
            
            # Clean up temp file
            temp_merged.unlink()
            success(f"Merged and quantized model saved to {output}")
            return True, f"Merged model saved to {output} ({quantize})"
            
        except subprocess.TimeoutExpired:
            return False, "Quantization timed out"
        except Exception as e:
            return False, f"Quantization error: {e}"
    else:
        temp_merged.rename(output)
        return True, f"Merged model saved to {output} (F16)"


# =============================================================================
# Model Hot-Swap
# =============================================================================

def swap_to_finetuned_model(
    model_path: str,
    model_variant: str = "primary"
) -> Tuple[bool, str]:
    """
    Swap to the fine-tuned model.
    
    Args:
        model_path: Path to fine-tuned model
        model_variant: "primary" or "secondary"
        
    Returns:
        Tuple of (success, message)
    """
    from core.loader_v2 import get_loader
    
    model_file = Path(model_path)
    if not model_file.exists():
        return False, f"Model not found: {model_path}"
    
    info(f"Swapping to fine-tuned {model_variant} model...")
    
    loader = get_loader()
    
    # For now, we need to update the config to point to new model
    # In a full implementation, this would use the loader's hot-swap
    if model_variant == "primary":
        # Backup original path
        original = MODEL_PATH
        # Update config (this is temporary, would need persistence)
        import utils.config as cfg
        cfg.MODEL_PATH = model_file
        
        # Reload
        loader.unload()
        if loader.load_primary():
            success(f"Swapped to fine-tuned primary model: {model_path}")
            return True, f"Swapped to fine-tuned model"
        else:
            # Rollback
            cfg.MODEL_PATH = original
            return False, "Failed to load fine-tuned model, rolled back"
    
    else:
        # Secondary model
        original = SECONDARY_MODEL_PATH
        import utils.config as cfg
        cfg.SECONDARY_MODEL_PATH = model_file
        
        loader.unload()
        if loader.load_secondary():
            success(f"Swapped to fine-tuned secondary model: {model_path}")
            return True, f"Swapped to fine-tuned model"
        else:
            cfg.SECONDARY_MODEL_PATH = original
            return False, "Failed to load fine-tuned model, rolled back"


# =============================================================================
# Rollback Support
# =============================================================================

def create_backup_before_import(model_variant: str) -> Optional[str]:
    """
    Create backup of current model before importing LoRA.
    
    Args:
        model_variant: "primary" or "secondary"
        
    Returns:
        Path to backup, or None if failed
    """
    import utils.config as cfg
    
    if model_variant == "primary":
        original = cfg.MODEL_PATH
    else:
        original = cfg.SECONDARY_MODEL_PATH
    
    original_path = Path(original)
    if not original_path.exists():
        warning(f"Original model not found: {original}")
        return None
    
    # Create backup in same directory
    backup_name = original_path.stem + ".backup" + original_path.suffix
    backup_path = original_path.parent / backup_name
    
    info(f"Creating backup: {backup_path}")
    try:
        shutil.copy2(original_path, backup_path)
        success(f"Backup created: {backup_path}")
        return str(backup_path)
    except Exception as e:
        warning(f"Failed to create backup: {e}")
        return None


def rollback_to_backup(
    backup_path: str,
    model_variant: str
) -> Tuple[bool, str]:
    """
    Rollback to backup model.
    
    Args:
        backup_path: Path to backup model
        model_variant: "primary" or "secondary"
        
    Returns:
        Tuple of (success, message)
    """
    backup = Path(backup_path)
    if not backup.exists():
        return False, f"Backup not found: {backup_path}"
    
    import utils.config as cfg
    
    if model_variant == "primary":
        original = cfg.MODEL_PATH
    else:
        original = cfg.SECONDARY_MODEL_PATH
    
    original_path = Path(original)
    
    info(f"Rolling back to backup...")
    try:
        shutil.copy2(backup, original_path)
        # Remove backup marker
        backup.unlink()
        
        # Reload model
        from core.loader_v2 import get_loader
        loader = get_loader()
        loader.unload()
        
        if model_variant == "primary":
            loader.load_primary()
        else:
            loader.load_secondary()
        
        success("Rolled back to original model")
        return True, "Rolled back successfully"
        
    except Exception as e:
        return False, f"Rollback failed: {e}"


# =============================================================================
# Main Entry Point
# =============================================================================

def import_lora_adapter(
    adapter_path: str,
    model_variant: str = "primary",
    quantize: str = "q4_0",
    merge_on_device: bool = False
) -> Dict:
    """
    Main entry point for importing LoRA adapter.
    
    Args:
        adapter_path: Path to LoRA adapter directory
        model_variant: "primary" (7B) or "secondary" (1.5B)
        quantize: Quantization level
        merge_on_device: Whether to merge on-device (default: expect pre-merged GGUF)
        
    Returns:
        Dict with results
    """
    results = {
        "success": False,
        "adapter_path": adapter_path,
        "model_variant": model_variant,
    }
    
    # Validate adapter
    valid, msg = validate_lora_adapter(adapter_path)
    if not valid:
        results["error"] = msg
        return results
    
    # Get adapter info
    info_dict = get_adapter_info(adapter_path)
    results["adapter_info"] = info_dict
    
    # Create backup
    backup_path = create_backup_before_import(model_variant)
    results["backup_path"] = backup_path
    
    if merge_on_device:
        # Full merge on-device (requires llama.cpp, lots of RAM)
        if model_variant == "primary":
            base_model = str(MODEL_PATH)
            output_name = "codey-v2-finetuned-7b.gguf"
        else:
            base_model = str(SECONDARY_MODEL_PATH)
            output_name = "codey-v2-finetuned-1.5b.gguf"
        
        output_path = Path.home() / "models" / "codey-finetuned" / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        success, msg = merge_lora_with_llama_cpp(
            adapter_path,
            base_model,
            str(output_path),
            quantize
        )
        
        if not success:
            results["error"] = msg
            return results
        
        # Swap to new model
        swap_success, swap_msg = swap_to_finetuned_model(str(output_path), model_variant)
        results["success"] = swap_success
        results["model_path"] = str(output_path)
        results["message"] = swap_msg
        
    else:
        # Expect pre-merged GGUF (user merged on Colab/PC)
        # Look for .gguf file in adapter directory
        adapter_dir = Path(adapter_path)
        gguf_files = list(adapter_dir.glob("*.gguf"))
        
        if not gguf_files:
            # Try to find in parent directory
            gguf_files = list(adapter_dir.parent.glob("*.gguf"))
        
        if not gguf_files:
            results["error"] = "No GGUF file found. Please merge adapter first or use --merge-on-device"
            results["instructions"] = """
To merge the adapter:
1. On PC with llama.cpp:
   python convert-lora.py --base-model model.gguf --lora-adapter adapter/ --output merged.gguf
   ./quantize merged.gguf merged-q4.gguf q4_0

2. Or use the provided merge script:
   python core/finetune_merge.py --adapter {adapter_path} --model {model_variant}

3. Then run:
   codey2 --import-lora /path/to/merged-q4.gguf --model {model_variant}
""".format(adapter_path=adapter_path, model_variant=model_variant)
            return results
        
        # Use first GGUF file
        merged_model = gguf_files[0]
        info(f"Found merged model: {merged_model}")
        
        # Swap to new model
        swap_success, swap_msg = swap_to_finetuned_model(str(merged_model), model_variant)
        results["success"] = swap_success
        results["model_path"] = str(merged_model)
        results["message"] = swap_msg
    
    return results
