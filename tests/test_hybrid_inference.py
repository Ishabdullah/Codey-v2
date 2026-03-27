#!/usr/bin/env python3
"""
Tests for Codey-v2 inference backend (v2.7.0).

Tests the current ChatCompletionBackend (single HTTP backend using
llama-server's /v1/chat/completions endpoint on port 8080).

The v2.4.0 three-backend architecture (DirectBindingBackend, TcpHttpBackend,
UnixSocketBackend, HybridInferenceBackend) was removed. This file was rewritten
to reflect the current single-backend architecture.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.inference_hybrid import (
    ChatCompletionBackend,
    get_hybrid_backend,
    reset_hybrid_backend,
)


class TestChatCompletionBackend:
    """Test the HTTP /v1/chat/completions backend."""

    def test_backend_name(self):
        """Backend should report the correct name."""
        backend = ChatCompletionBackend()
        assert backend.backend_name == "chat_completions"

    def test_default_host_port(self):
        """Should default to localhost:8080."""
        backend = ChatCompletionBackend()
        assert backend._host == "127.0.0.1"
        assert backend._port == 8080

    def test_custom_host_port(self):
        """Should accept custom host and port."""
        backend = ChatCompletionBackend(host="192.168.1.10", port=9000)
        assert backend._host == "192.168.1.10"
        assert backend._port == 9000

    def test_base_url_constructed(self):
        """Base URL should be derived from host and port."""
        backend = ChatCompletionBackend(host="127.0.0.1", port=8080)
        assert backend._base_url == "http://127.0.0.1:8080"

    def test_calls_initially_zero(self):
        """Call counter should start at zero."""
        backend = ChatCompletionBackend()
        assert backend._calls_made == 0

    def test_check_health_returns_bool(self):
        """check_health() should return a bool (False when server not running)."""
        backend = ChatCompletionBackend()
        result = backend.check_health()
        assert isinstance(result, bool)

    def test_is_server_running_returns_bool(self):
        """is_server_running() should return a bool."""
        backend = ChatCompletionBackend()
        result = backend.is_server_running()
        assert isinstance(result, bool)

    def test_get_stats_structure(self):
        """get_stats() should return a dict with expected keys."""
        backend = ChatCompletionBackend()
        stats = backend.get_stats()
        assert isinstance(stats, dict)
        assert "active_backend" in stats
        assert stats["active_backend"] == "chat_completions"
        assert "host" in stats
        assert "port" in stats
        assert "calls_made" in stats
        assert stats["calls_made"] == 0


class TestGlobalBackendSingleton:
    """Test the module-level singleton and reset functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_hybrid_backend()

    def test_get_hybrid_backend_returns_instance(self):
        """get_hybrid_backend() should return a ChatCompletionBackend."""
        backend = get_hybrid_backend()
        assert backend is not None
        assert isinstance(backend, ChatCompletionBackend)

    def test_singleton_same_instance(self):
        """Repeated calls should return the same instance."""
        backend1 = get_hybrid_backend()
        backend2 = get_hybrid_backend()
        assert backend1 is backend2

    def test_reset_creates_new_instance(self):
        """reset_hybrid_backend() should force creation of a new instance."""
        backend1 = get_hybrid_backend()
        reset_hybrid_backend()
        backend2 = get_hybrid_backend()
        assert backend1 is not backend2

    def test_prefer_unix_socket_ignored(self):
        """prefer_unix_socket kwarg is accepted for compat but has no effect."""
        backend = get_hybrid_backend(prefer_unix_socket=True)
        assert isinstance(backend, ChatCompletionBackend)

    def test_reset_then_check_backend_name(self):
        """After reset, new backend should still have correct name."""
        reset_hybrid_backend()
        backend = get_hybrid_backend()
        assert backend.backend_name == "chat_completions"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
