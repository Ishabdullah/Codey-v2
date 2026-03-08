#!/usr/bin/env python3
"""
Model loader for Codey v2.

Manages loading/unloading of models with hot-swap capability:
- Primary model (7B) for complex tasks
- Secondary model (1.5B) for simple tasks
- Hot-swap with 2-3 second delay
- Cooldown to prevent thrashing
"""

import time
from typing import Optional, Literal
from pathlib import Path

from utils.logger import info, warning, error, success
from utils.config import MODEL_PATH, SECONDARY_MODEL_PATH, MODEL_CONFIG, ROUTER_CONFIG

ModelType = Literal["primary", "secondary"]


class ModelLoader:
    """
    Manages model loading and hot-swapping.
    
    Supports:
    - Load primary (7B) or secondary (1.5B) model
    - Unload current model
    - Hot-swap with cooldown
    - Track loaded model state
    """
    
    def __init__(self):
        self._loaded_model: Optional[ModelType] = None
        self._model_instance: Optional[object] = None
        self._loaded_at: float = 0
        self._load_failures: int = 0
    
    def load_primary(self) -> bool:
        """
        Load the primary (7B) model.
        
        Returns:
            True if loaded successfully, False otherwise
        """
        return self._load_model("primary", MODEL_PATH)
    
    def load_secondary(self) -> bool:
        """
        Load the secondary (1.5B) model.
        
        Returns:
            True if loaded successfully, False otherwise
        """
        return self._load_model("secondary", SECONDARY_MODEL_PATH)
    
    def _load_model(self, model_type: ModelType, model_path: Path) -> bool:
        """
        Internal method to load a model.
        
        Args:
            model_type: "primary" or "secondary"
            model_path: Path to model file
            
        Returns:
            True if loaded successfully
        """
        try:
            info(f"Loading {model_type} model: {model_path.name}")
            
            # Check if model file exists
            if not model_path.exists():
                error(f"Model file not found: {model_path}")
                self._load_failures += 1
                return False
            
            # Import llama_cpp here to avoid dependency issues when not needed
            try:
                from llama_cpp import Llama
            except ImportError:
                error("llama-cpp-python not installed. Run: pip install llama-cpp-python")
                self._load_failures += 1
                return False
            
            # Unload current model if loaded
            if self._model_instance is not None:
                self.unload()
            
            # Load new model
            self._model_instance = Llama(
                model_path=str(model_path),
                n_ctx=MODEL_CONFIG["n_ctx"],
                n_threads=MODEL_CONFIG["n_threads"],
                n_gpu_layers=MODEL_CONFIG["n_gpu_layers"],
                verbose=MODEL_CONFIG["verbose"],
            )
            
            self._loaded_model = model_type
            self._loaded_at = time.time()
            
            success(f"Loaded {model_type} model ({model_path.name})")
            return True
            
        except Exception as e:
            error(f"Failed to load {model_type} model: {e}")
            self._load_failures += 1
            return False
    
    def unload(self):
        """Unload the current model."""
        if self._model_instance is not None:
            info(f"Unloading {self._loaded_model} model")
            del self._model_instance
            self._model_instance = None
            self._loaded_model = None
            success("Model unloaded")
    
    def ensure_model(self, model_type: ModelType) -> bool:
        """
        Ensure a specific model is loaded.
        
        If different model is loaded, unloads and loads the requested one.
        
        Args:
            model_type: "primary" or "secondary"
            
        Returns:
            True if model is loaded (or was already loaded)
        """
        if self._loaded_model == model_type:
            return True
        
        if model_type == "primary":
            return self.load_primary()
        else:
            return self.load_secondary()
    
    def get_loaded_model(self) -> Optional[ModelType]:
        """Get the currently loaded model type."""
        return self._loaded_model
    
    def is_loaded(self, model_type: ModelType = None) -> bool:
        """Check if a model is loaded (optionally check specific type)."""
        if model_type is None:
            return self._loaded_model is not None
        return self._loaded_model == model_type
    
    def get_model_instance(self) -> Optional[object]:
        """Get the llama_cpp model instance."""
        return self._model_instance
    
    def get_load_failures(self) -> int:
        """Get count of consecutive load failures."""
        return self._load_failures
    
    def reset_failures(self):
        """Reset failure count (call after successful load)."""
        self._load_failures = 0
    
    def get_status(self) -> dict:
        """Get loader status."""
        return {
            "loaded_model": self._loaded_model,
            "loaded_at": self._loaded_at,
            "uptime_seconds": time.time() - self._loaded_at if self._loaded_at else 0,
            "load_failures": self._load_failures,
        }


# Global loader instance
_loader: Optional[ModelLoader] = None


def get_loader() -> ModelLoader:
    """Get the global loader instance."""
    global _loader
    if _loader is None:
        _loader = ModelLoader()
    return _loader


def reset_loader():
    """Reset the global loader (for testing)."""
    global _loader
    if _loader:
        _loader = None
