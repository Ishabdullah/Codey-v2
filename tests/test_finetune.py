#!/usr/bin/env python3
"""
Tests for Codey-v2 fine-tuning workflow.

Tests:
- Dataset curation
- ShareGPT export
- Notebook generation
- LoRA adapter validation
- Import workflow
"""

import sys
import json
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.finetune_prep import DatasetCurator, export_dataset, generate_notebook
from core.lora_import import validate_lora_adapter, get_adapter_info


class TestDatasetCurator:
    """Test dataset curation from episodic memory."""

    def test_quality_calculation(self):
        """Test quality score calculation."""
        curator = DatasetCurator()
        
        # High quality: successful, multi-step, recent
        high_quality = {
            "success": True,
            "steps": 3,
            "timestamp": 1000000000,  # Recent
            "error": None
        }
        score = curator._calculate_quality(high_quality)
        assert score >= 0.7
        
        # Low quality: error occurred
        low_quality = {
            "success": False,
            "steps": 1,
            "timestamp": 1000000000,
            "error": "Something failed"
        }
        score = curator._calculate_quality(low_quality)
        assert score < 0.5

    def test_action_to_sharegpt(self):
        """Test conversion to ShareGPT format."""
        curator = DatasetCurator()
        
        action = {
            "user_message": "Create a Flask app",
            "response": "I'll create a Flask app for you...",
            "success": True,
            "tools_used": ["write_file"]
        }
        
        result = curator._action_to_sharegpt(action)
        assert result is not None
        assert "conversations" in result
        assert len(result["conversations"]) >= 2
        
        # Check roles
        roles = [c["role"] for c in result["conversations"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_curate_examples(self):
        """Test example curation."""
        curator = DatasetCurator()
        
        # This will return empty if no episodic data
        # but should not crash
        examples = curator.curate_examples(days=30, min_quality=0.7)
        assert isinstance(examples, list)


class TestDatasetExport:
    """Test dataset export to JSONL."""

    def test_export_jsonl(self):
        """Test JSONL export."""
        examples = [
            {
                "conversations": [
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"}
                ]
            }
        ]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path, count = export_dataset(examples, tmpdir, "both")
            
            assert count == 1
            assert Path(path).exists()
            
            # Verify JSONL format
            with open(path) as f:
                lines = f.readlines()
                assert len(lines) == 1
                
                data = json.loads(lines[0])
                assert "conversations" in data


class TestNotebookGeneration:
    """Test Colab notebook generation."""

    def test_generate_1_5b_notebook(self):
        """Test 1.5B notebook generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_notebook("1.5b", tmpdir)
            
            assert Path(path).exists()
            assert "1.5b" in path
            
            # Verify notebook structure
            with open(path) as f:
                nb = json.load(f)
                assert "cells" in nb
                assert nb["nbformat"] == 4

    def test_generate_7b_notebook(self):
        """Test 7B notebook generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_notebook("7b", tmpdir)
            
            assert Path(path).exists()
            assert "7b" in path
            
            # Verify notebook structure
            with open(path) as f:
                nb = json.load(f)
                assert "cells" in nb

    def test_notebook_contains_unsloth(self):
        """Test notebook includes Unsloth setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_notebook("1.5b", tmpdir)
            
            with open(path) as f:
                content = f.read()
                
                # Check for key Unsloth elements
                assert "unsloth" in content.lower() or "Unsloth" in content
                assert "LoRA" in content or "lora" in content
                assert "from_pretrained" in content


class TestLoraValidation:
    """Test LoRA adapter validation."""

    def test_invalid_path(self):
        """Test invalid adapter path."""
        valid, msg = validate_lora_adapter("/nonexistent/path")
        assert valid == False
        assert "not found" in msg.lower()

    def test_not_a_directory(self):
        """Test when path is not a directory."""
        with tempfile.NamedTemporaryFile() as f:
            valid, msg = validate_lora_adapter(f.name)
            assert valid == False
            assert "directory" in msg.lower()

    def test_missing_required_files(self):
        """Test adapter missing required files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create empty directory
            valid, msg = validate_lora_adapter(tmpdir)
            assert valid == False
            assert "Missing" in msg or "required" in msg.lower()

    def test_valid_adapter_structure(self):
        """Test valid adapter structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter_dir = Path(tmpdir)
            
            # Create required files
            config = {
                "r": 16,
                "lora_alpha": 16,
                "target_modules": ["q_proj", "v_proj"],
                "base_model_name_or_path": "Qwen/Qwen2.5-Coder-7B-Instruct"
            }
            with open(adapter_dir / "adapter_config.json", "w") as f:
                json.dump(config, f)
            
            # Create dummy weights file
            (adapter_dir / "adapter_model.safetensors").touch()
            
            valid, msg = validate_lora_adapter(str(adapter_dir))
            assert valid == True
            assert "Valid" in msg


class TestAdapterInfo:
    """Test adapter info extraction."""

    def test_get_info(self):
        """Test getting adapter information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter_dir = Path(tmpdir)
            
            # Create config
            config = {
                "r": 32,
                "lora_alpha": 32,
                "base_model_name_or_path": "Qwen/Qwen2.5-1.5B-Instruct"
            }
            with open(adapter_dir / "adapter_config.json", "w") as f:
                json.dump(config, f)
            
            # Create dummy file for size
            (adapter_dir / "dummy.bin").write_bytes(b"x" * 1024)
            
            info = get_adapter_info(str(adapter_dir))
            
            assert "path" in info
            assert info["lora_r"] == 32
            assert info["lora_alpha"] == 32
            assert "1.5B" in info["base_model"]
            assert info["size_mb"] > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
