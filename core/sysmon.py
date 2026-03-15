#!/usr/bin/env python3
"""
System monitor for Codey-v2 TUI.

Reads CPU%, RAM, and CPU/SoC temperature in a background thread.
Provides a Rich renderable for live display and a terminal-title updater.

No psutil required — reads /proc/stat, /proc/meminfo, and
/sys/class/thermal directly (all available in Termux/Android).
psutil is used when installed for slightly more accurate CPU%.
"""

import sys
import time
import threading
from pathlib import Path
from typing import Optional, Tuple

from rich.text import Text


class SystemMonitor:
    """
    Background thread that samples CPU, RAM, and temperature every `interval`
    seconds.  Thread is daemon so it never blocks process exit.
    """

    def __init__(self, interval: float = 2.0):
        self._interval = interval
        self._lock = threading.Lock()
        self._cpu: float = 0.0
        self._ram_used: int = 0
        self._ram_total: int = 0
        self._temp: Optional[float] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # For /proc/stat delta CPU calculation
        self._prev_idle: int = 0
        self._prev_total: int = 0
        self._seed_cpu_proc()   # seed /proc/stat fallback

    # ── public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        # Do one immediate read so the first render() call has real data
        self._loop_once()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sysmon")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    @property
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu":       self._cpu,
                "ram_used":  self._ram_used,
                "ram_total": self._ram_total,
                "temp":      self._temp,
            }

    def render(self) -> Text:
        """Return a Rich Text line suitable for printing as a stats bar."""
        s = self.snapshot
        cpu  = s["cpu"]
        ru   = s["ram_used"]  / 1024 ** 3
        rt   = s["ram_total"] / 1024 ** 3
        temp = s["temp"]

        cpu_col  = _threshold_color(cpu, warn=60, crit=85)
        ram_pct  = (ru / rt * 100) if rt else 0
        ram_col  = _threshold_color(ram_pct, warn=65, crit=85)
        temp_col = _threshold_color(temp or 0, warn=65, crit=80) if temp else "dim"

        cpu_bar = _bar(cpu, width=8)
        ram_bar = _bar(ram_pct, width=8)

        line = Text()
        line.append(" CPU ", style="dim")
        line.append(f"[{cpu_bar}]", style=cpu_col)
        line.append(f" {cpu:4.1f}%", style=f"bold {cpu_col}")
        line.append("   RAM ", style="dim")
        line.append(f"[{ram_bar}]", style=ram_col)
        line.append(f" {ru:.1f}/{rt:.1f} GB", style=f"bold {ram_col}")
        if temp is not None:
            line.append("   Temp ", style="dim")
            line.append(f"{temp:.0f}°C", style=f"bold {temp_col}")
        return line

    def set_title(self) -> None:
        """Write a compact stats string to the terminal title bar."""
        if not sys.stdout.isatty():
            return
        s = self.snapshot
        cpu  = s["cpu"]
        ru   = s["ram_used"]  / 1024 ** 3
        rt   = s["ram_total"] / 1024 ** 3
        temp = s["temp"]
        parts = [f"CPU {cpu:.0f}%", f"RAM {ru:.1f}/{rt:.1f}G"]
        if temp is not None:
            parts.append(f"T {temp:.0f}°C")
        bar = "  ·  ".join(parts)
        try:
            sys.stdout.write(f"\033]0;Codey  {bar}\007")
            sys.stdout.flush()
        except Exception:
            pass

    # ── internals ─────────────────────────────────────────────────────────────

    def _loop_once(self) -> None:
        cpu    = self._read_cpu()
        ru, rt = self._read_ram()
        temp   = self._read_temp()
        with self._lock:
            self._cpu       = cpu
            self._ram_used  = ru
            self._ram_total = rt
            self._temp      = temp
        self.set_title()

    def _loop(self) -> None:
        while self._running:
            self._loop_once()
            time.sleep(self._interval)

    def _seed_cpu_proc(self) -> None:
        try:
            with open("/proc/stat") as f:
                fields = list(map(int, f.readline().split()[1:]))
            self._prev_idle  = fields[3] + (fields[4] if len(fields) > 4 else 0)
            self._prev_total = sum(fields)
        except Exception:
            pass

    def _read_cpu(self) -> float:
        try:
            import psutil
            # interval=0.5 blocks briefly but gives an accurate reading every time.
            # interval=None returns 0.0 on first call and requires a prior seed.
            return psutil.cpu_percent(interval=0.5)
        except ImportError:
            return self._read_cpu_proc()

    def _read_cpu_proc(self) -> float:
        try:
            with open("/proc/stat") as f:
                fields = list(map(int, f.readline().split()[1:]))
            idle  = fields[3] + (fields[4] if len(fields) > 4 else 0)
            total = sum(fields)
            d_idle  = idle  - self._prev_idle
            d_total = total - self._prev_total
            self._prev_idle  = idle
            self._prev_total = total
            if d_total == 0:
                return 0.0
            return 100.0 * (1.0 - d_idle / d_total)
        except Exception:
            return 0.0

    def _read_ram(self) -> Tuple[int, int]:
        try:
            import psutil
            m = psutil.virtual_memory()
            return m.used, m.total
        except ImportError:
            pass
        try:
            info: dict = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":")
                    info[k.strip()] = int(v.split()[0]) * 1024
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", 0)
            return total - avail, total
        except Exception:
            return 0, 0

    def _read_temp(self) -> Optional[float]:
        """
        Scan /sys/class/thermal for CPU/SoC zones (Android).
        Falls back to any zone if no CPU-named zone is found.
        """
        best: Optional[float] = None
        try:
            for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
                try:
                    ztype = (zone / "type").read_text().strip().lower()
                    raw   = int((zone / "temp").read_text().strip())
                    temp_c = raw / 1000.0
                    # Ignore absurd readings (sensor glitches)
                    if not (0 < temp_c < 120):
                        continue
                    if any(k in ztype for k in ("cpu", "soc", "package", "skin")):
                        return temp_c
                    if best is None:
                        best = temp_c
                except Exception:
                    continue
        except Exception:
            pass
        return best


# ── helpers ───────────────────────────────────────────────────────────────────

def _threshold_color(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return "bold red"
    if value >= warn:
        return "bold yellow"
    return "bold green"


def _bar(pct: float, width: int = 10) -> str:
    filled = int(round(pct / 100 * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


# ── singleton ─────────────────────────────────────────────────────────────────

_monitor: Optional[SystemMonitor] = None


def get_monitor() -> SystemMonitor:
    global _monitor
    if _monitor is None:
        _monitor = SystemMonitor()
    return _monitor
