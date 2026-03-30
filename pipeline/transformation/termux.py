"""
TermuxNormalizer — converts generic Linux/macOS shell commands to their
Termux equivalents.

Run on any shell command before it reaches the output JSONL.
"""

import re

# Direct command substitutions (first token of command)
_COMMAND_MAP = {
    "apt":          "pkg",
    "apt-get":      "pkg",
    "brew":         "pkg",
    "python3":      "python",
    "pip3":         "pip",
    "node":         "node",     # same in Termux
    "npm":          "npm",      # same
}

# Subcommand-aware substitutions: (pattern, replacement)
_PATTERN_SUBS = [
    # sudo → strip entirely (no sudo in Termux)
    (re.compile(r"^sudo\s+"),                          ""),
    # apt install / apt-get install → pkg install
    (re.compile(r"\bapt(?:-get)?\s+install\b"),        "pkg install"),
    (re.compile(r"\bapt(?:-get)?\s+update\b"),         "pkg update"),
    (re.compile(r"\bapt(?:-get)?\s+upgrade\b"),        "pkg upgrade"),
    (re.compile(r"\bapt(?:-get)?\s+remove\b"),         "pkg uninstall"),
    # python3 → python
    (re.compile(r"\bpython3\b"),                       "python"),
    # pip3 → pip
    (re.compile(r"\bpip3\b"),                          "pip"),
    # Absolute paths that differ in Termux
    (re.compile(r"/usr/bin/python3?"),                 "python"),
    (re.compile(r"/usr/local/bin/python3?"),           "python"),
    (re.compile(r"/usr/bin/pip3?"),                    "pip"),
    (re.compile(r"/usr/local/bin/pip3?"),              "pip"),
    # /usr/bin/env python3 → python
    (re.compile(r"/usr/bin/env\s+python3"),            "python"),
    (re.compile(r"/usr/bin/env\s+python"),             "python"),
    # homebrew paths
    (re.compile(r"/opt/homebrew/bin/(\w+)"),           r"\1"),
    (re.compile(r"/usr/local/Cellar/\S+/bin/(\w+)"),  r"\1"),
    # systemctl (not available in Termux — warn but keep)
    # service → nohup equivalent (no direct sub, just normalise)
]

# Package name translations (some packages differ in Termux)
_PKG_MAP = {
    "python3":        "python",
    "python3-pip":    "python",
    "python3-dev":    "python",
    "python3-venv":   "python",
    "libpython3-dev": "python",
    "build-essential":"build-essential",  # exists in Termux
    "nodejs":         "nodejs",
    "npm":            "nodejs",
    "default-jdk":    "openjdk-17",
    "default-jre":    "openjdk-17",
    "openjdk-11-jdk": "openjdk-17",
    "wget":           "wget",
    "curl":           "curl",
    "git":            "git",
    "vim":            "vim",
    "neovim":         "neovim",
    "htop":           "htop",
    "tmux":           "tmux",
    "rsync":          "rsync",
    "sqlite3":        "sqlite",
    "libsqlite3-dev": "sqlite",
    "ffmpeg":         "ffmpeg",
    "imagemagick":    "imagemagick",
    "gcc":            "clang",
    "g++":            "clang",
    "clang":          "clang",
    "cmake":          "cmake",
    "make":           "make",
    "unzip":          "unzip",
    "zip":            "zip",
}


def normalize_command(command: str) -> str:
    """
    Apply Termux normalizations to a shell command string.

    Args:
        command: raw shell command

    Returns:
        Termux-compatible command string
    """
    cmd = command.strip()

    # Apply pattern substitutions in order
    for pattern, replacement in _PATTERN_SUBS:
        cmd = pattern.sub(replacement, cmd)
        cmd = cmd.strip()

    # Normalize package names in pkg install commands
    cmd = _normalize_pkg_names(cmd)

    return cmd.strip()


def _normalize_pkg_names(cmd: str) -> str:
    """Translate generic package names to Termux equivalents."""
    # Match pkg install / pip install patterns
    pkg_install_re = re.compile(
        r"((?:pkg|pip|pip3|apt|apt-get)\s+install\s+)(.*)",
        re.IGNORECASE,
    )
    m = pkg_install_re.match(cmd)
    if not m:
        return cmd

    prefix = m.group(1)
    packages_str = m.group(2)

    # Split packages (handle -y, --quiet flags)
    parts = packages_str.split()
    translated = []
    for part in parts:
        if part.startswith("-"):
            translated.append(part)
        else:
            translated.append(_PKG_MAP.get(part.lower(), part))

    return prefix + " ".join(translated)


def is_termux_compatible(command: str) -> bool:
    """
    Rough check: does this command look Termux-compatible after normalization?

    Returns False for commands that require root or unavailable system services.
    """
    incompatible = [
        "systemctl", "service ", "initctl",
        "useradd", "groupadd", "usermod",
        "mount ", "umount ",
        "fdisk", "parted",
        "/etc/init.d/",
        "dpkg-reconfigure",
    ]
    cmd_lower = command.lower()
    return not any(p in cmd_lower for p in incompatible)
