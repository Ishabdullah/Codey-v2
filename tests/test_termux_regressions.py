"""Regression coverage for Termux installation and restricted Android monitoring."""
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from core.sysmon import SystemMonitor
from pipeline.storage.vector_store import VectorStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('error', [PermissionError, FileNotFoundError, OSError])
def test_monitor_survives_restricted_reads(error):
    psutil = SimpleNamespace(cpu_percent=Mock(side_effect=error('restricted')),
                             virtual_memory=Mock(side_effect=error('restricted')))
    with patch.dict(sys.modules, {'psutil': psutil}), \
         patch('builtins.open', side_effect=error('restricted')), \
         patch.object(Path, 'glob', side_effect=error('restricted')):
        monitor = SystemMonitor(interval=0.01)
        monitor.start()
        try:
            time.sleep(0.03)
            assert monitor._thread.is_alive()
            assert monitor.snapshot['cpu'] == 0.0
            assert monitor.snapshot['ram_total'] == 0
            assert monitor.snapshot['temp'] is None
            assert 'CPU' in monitor.render().plain
        finally:
            monitor.stop()
            monitor._thread.join(timeout=1)
        assert not monitor._thread.is_alive()


def test_monitor_uses_proc_fallback_when_psutil_denied():
    psutil = SimpleNamespace(cpu_percent=Mock(side_effect=PermissionError),
                             virtual_memory=Mock(side_effect=PermissionError))
    with patch.dict(sys.modules, {'psutil': psutil}):
        monitor = SystemMonitor()
        with patch.object(monitor, '_read_cpu_proc', return_value=42.0):
            assert monitor._read_cpu() == 42.0
        from io import StringIO
        with patch('builtins.open', return_value=StringIO(
                'MemTotal: 100 kB\nMemAvailable: 40 kB\n')):
            assert monitor._read_ram() == (60 * 1024, 100 * 1024)


def test_numpy_vector_search_without_hnswlib(tmp_path):
    with patch.dict(sys.modules, {'hnswlib': None}):
        path = str(tmp_path / 'vectors.bin')
        store = VectorStore(dim=3, index_path=path)
        assert not store._use_hnswlib
        assert store.add_batch([[1, 0, 0], [0, 1, 0]]) == [0, 1]
        assert store.search([1, 0, 0], top_k=1)[0][0] == 0
        store.save()
        restored = VectorStore(dim=3, index_path=path)
        assert restored.search([0, 1, 0], top_k=1)[0][0] == 1
        assert restored.add([0, 0, 1]) == 2


def run_installer(termux, fail_core=False):
    # Source functions only; fake pip so no packages/models are installed.
    script = '''
source ./install.sh
is_termux() { TERMUX_RESULT; }
python3() {
    if [[ "$1" == "-c" ]]; then return 0; fi
    printf '%s\\n' "$*"
    if [[ "$*" == *rich* ]]; then CORE_RESULT; fi
}
SKIP_CONFIRM=true
install_python_deps
'''.replace('TERMUX_RESULT', 'return 0' if termux else 'return 1').replace(
        'CORE_RESULT', 'return 1' if fail_core else 'return 0')
    return subprocess.run(['bash', '-c', script], cwd=ROOT,
                          text=True, capture_output=True)


def test_termux_installer_skips_native_builds():
    result = run_installer(True)
    assert result.returncode == 0
    pip_commands = [line for line in result.stdout.splitlines() if line.startswith('-m pip')]
    assert pip_commands
    assert not any('numpy' in line or 'ann' in line or 'hnswlib' in line for line in pip_commands)
    assert 'Core Python packages installed' in result.stdout


def test_desktop_installer_keeps_optional_acceleration():
    result = run_installer(False)
    assert result.returncode == 0
    assert '-m pip install numpy>=1.24.0' in result.stdout
    assert 'requirements-ann.txt' in result.stdout


def test_core_install_failure_is_not_reported_as_success():
    result = run_installer(True, fail_core=True)
    assert result.returncode != 0
    assert 'Core Python packages installed' not in result.stdout


def test_pipeline_requirements_do_not_require_hnswlib():
    requirements = (ROOT / 'requirements.txt').read_text().splitlines()
    assert not any(line.startswith('hnswlib') for line in requirements)
