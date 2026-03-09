#!/usr/bin/env python3
"""
Tests for Codey-v2 hybrid inference backend (v2.4.0).

Tests:
- Backend initialization and fallback
- Direct binding availability detection
- Unix socket backend
- TCP HTTP backend
- Hybrid backend manager
- Latency tracking
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.inference_hybrid import (
    DirectBindingBackend,
    UnixSocketBackend,
    TcpHttpBackend,
    HybridInferenceBackend,
    BackendStats,
    get_hybrid_backend,
    reset_hybrid_backend,
)


class TestDirectBindingBackend:
    """Test direct llama-cpp-python binding backend."""

    def test_initialize_unavailable(self):
        """Direct binding should be unavailable on Termux/Android."""
        backend = DirectBindingBackend()
        result = backend.initialize()
        
        # On Termux/Android, this should return False
        # On desktop with llama-cpp-python installed, might return True
        assert isinstance(result, bool)
        assert backend._available == result
        
        if not result:
            # Should have an error message
            assert backend._init_error is not None

    def test_backend_name(self):
        """Backend should have correct name."""
        backend = DirectBindingBackend()
        assert backend.backend_name == "direct"

    def test_is_loaded_initially_false(self):
        """Should not have model loaded initially."""
        backend = DirectBindingBackend()
        backend.initialize()
        assert backend.is_loaded == False


class TestTcpHttpBackend:
    """Test TCP HTTP backend (original fallback)."""

    def test_backend_name(self):
        """Backend should have correct name."""
        backend = TcpHttpBackend()
        assert backend.backend_name == "tcp_http"

    def test_default_host_port(self):
        """Should use default host and port."""
        backend = TcpHttpBackend()
        assert backend._host == "127.0.0.1"
        assert backend._port == 8080

    def test_custom_host_port(self):
        """Should accept custom host and port."""
        backend = TcpHttpBackend(host="192.168.1.100", port=9000)
        assert backend._host == "192.168.1.100"
        assert backend._port == 9000


class TestUnixSocketBackend:
    """Test Unix domain socket backend."""

    def test_backend_name(self):
        """Backend should have correct name."""
        backend = UnixSocketBackend()
        assert backend.backend_name == "unix_socket"

    def test_default_socket_path(self):
        """Should use default socket path."""
        backend = UnixSocketBackend()
        assert "llama.sock" in backend._socket_path

    def test_custom_socket_path(self):
        """Should accept custom socket path."""
        backend = UnixSocketBackend(socket_path="/tmp/custom.sock")
        assert backend._socket_path == "/tmp/custom.sock"


class TestHybridInferenceBackend:
    """Test hybrid backend manager."""

    def setup_method(self):
        """Reset before each test."""
        reset_hybrid_backend()

    def test_initialize_selects_backend(self):
        """Should initialize and select best available backend."""
        hybrid = HybridInferenceBackend()
        backend_name = hybrid.initialize()
        
        # Should return one of the available backends
        assert backend_name in ["direct", "unix_socket", "tcp_http"]
        assert hybrid._active_backend is not None

    def test_stats_tracking(self):
        """Should track backend statistics."""
        hybrid = HybridInferenceBackend()
        hybrid.initialize()
        
        stats = hybrid.get_stats()
        
        assert "active_backend" in stats
        assert "backends" in stats
        assert isinstance(stats["backends"], dict)

    def test_fallback_chain(self):
        """Should have proper fallback chain."""
        hybrid = HybridInferenceBackend(prefer_unix_socket=True)
        hybrid.initialize()
        
        # Check that stats are tracked for initialized backends
        stats = hybrid.get_stats()
        
        # At minimum, one backend should be available
        assert len(stats["backends"]) >= 1
        
        # Direct binding should be unavailable on Termux
        if "direct" in stats["backends"]:
            assert stats["backends"]["direct"]["available"] == False
        
        # Unix socket or tcp_http should be available as fallback
        available_backends = [
            name for name, s in stats["backends"].items() 
            if s["available"]
        ]
        assert len(available_backends) >= 1

    def test_unload_model(self):
        """Should unload model cleanly."""
        hybrid = HybridInferenceBackend()
        hybrid.initialize()
        
        # Unload should not raise even if no model loaded
        hybrid.unload_model()


class TestBackendStats:
    """Test backend statistics dataclass."""

    def test_create_stats(self):
        """Should create stats object."""
        stats = BackendStats(
            backend_name="test",
            init_success=True
        )
        
        assert stats.backend_name == "test"
        assert stats.init_success == True
        assert stats.init_error is None
        assert stats.avg_latency_ms == 0.0
        assert stats.calls_made == 0

    def test_stats_with_error(self):
        """Should track init error."""
        stats = BackendStats(
            backend_name="test",
            init_success=False,
            init_error="Test error message"
        )
        
        assert stats.init_success == False
        assert stats.init_error == "Test error message"


class TestGlobalBackend:
    """Test global backend singleton."""

    def setup_method(self):
        """Reset before each test."""
        reset_hybrid_backend()

    def test_get_hybrid_backend_creates_instance(self):
        """Should create instance on first call."""
        backend = get_hybrid_backend()
        assert backend is not None
        assert isinstance(backend, HybridInferenceBackend)

    def test_get_hybrid_backend_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        backend1 = get_hybrid_backend()
        backend2 = get_hybrid_backend()
        
        assert backend1 is backend2

    def test_reset_hybrid_backend(self):
        """Should reset global instance."""
        backend1 = get_hybrid_backend()
        reset_hybrid_backend()
        backend2 = get_hybrid_backend()
        
        # Should be different instances after reset
        assert backend1 is not backend2


class TestBackendLatencyTracking:
    """Test backend latency tracking."""

    def test_latency_initialized_zero(self):
        """Latency should start at zero."""
        stats = BackendStats(backend_name="test", init_success=True)
        assert stats.avg_latency_ms == 0.0

    def test_calls_initialized_zero(self):
        """Call count should start at zero."""
        stats = BackendStats(backend_name="test", init_success=True)
        assert stats.calls_made == 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
