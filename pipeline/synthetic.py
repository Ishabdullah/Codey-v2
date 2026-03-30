"""
Synthetic corpus generator.

Produces Termux CLI examples and multi-step coding patterns that fill
the gaps in available open-source datasets.

Writes two JSONL files:
  synthetic_termux.jsonl     — ~5K Termux shell command examples
  synthetic_multistep.jsonl  — ~3K multi-step coding patterns
"""

import json
import itertools
from pathlib import Path
from typing import List, Dict

# ── Termux package corpus ─────────────────────────────────────────────────────

_PKG_INSTALL = [
    ("python",        ["python", "py", "python3", "cpython"]),
    ("nodejs",        ["node", "nodejs", "node.js", "javascript runtime"]),
    ("git",           ["git", "version control", "git vcs"]),
    ("vim",           ["vim", "vi editor"]),
    ("neovim",        ["neovim", "nvim"]),
    ("clang",         ["clang", "c compiler", "c++ compiler", "gcc"]),
    ("cmake",         ["cmake", "build system"]),
    ("make",          ["make", "makefile"]),
    ("wget",          ["wget", "web downloader"]),
    ("curl",          ["curl", "http client"]),
    ("zip",           ["zip", "archive tool"]),
    ("unzip",         ["unzip"]),
    ("tar",           ["tar"]),
    ("sqlite",        ["sqlite", "sqlite3", "database"]),
    ("htop",          ["htop", "process monitor", "task manager"]),
    ("tmux",          ["tmux", "terminal multiplexer"]),
    ("ffmpeg",        ["ffmpeg", "video tool", "audio tool"]),
    ("imagemagick",   ["imagemagick", "image processing"]),
    ("openssh",       ["ssh", "openssh", "secure shell"]),
    ("rsync",         ["rsync", "file sync"]),
    ("openjdk-17",    ["java", "jdk", "java development kit"]),
    ("rust",          ["rust", "rustlang", "cargo"]),
    ("golang",        ["go", "golang"]),
    ("ruby",          ["ruby"]),
    ("perl",          ["perl"]),
    ("php",           ["php"]),
    ("lua",           ["lua"]),
    ("nmap",          ["nmap", "network scanner"]),
    ("termux-api",    ["termux api", "termux-api"]),
    ("build-essential", ["build tools", "build essential", "dev tools"]),
]

_PIP_INSTALL = [
    ("numpy",         ["numpy", "numerical python", "array math"]),
    ("pandas",        ["pandas", "data analysis", "dataframe"]),
    ("requests",      ["requests", "http library"]),
    ("flask",         ["flask", "web framework"]),
    ("fastapi",       ["fastapi", "fast api"]),
    ("uvicorn",       ["uvicorn", "asgi server"]),
    ("scipy",         ["scipy", "scientific python"]),
    ("matplotlib",    ["matplotlib", "plotting", "charts"]),
    ("pillow",        ["pillow", "pil", "image library"]),
    ("tqdm",          ["tqdm", "progress bar"]),
    ("rich",          ["rich", "rich terminal", "colored output"]),
    ("click",         ["click", "cli framework"]),
    ("pydantic",      ["pydantic", "data validation"]),
    ("httpx",         ["httpx", "async http"]),
    ("aiohttp",       ["aiohttp", "async http client"]),
    ("sqlalchemy",    ["sqlalchemy", "orm", "database orm"]),
    ("transformers",  ["transformers", "huggingface"]),
    ("torch",         ["pytorch", "torch"]),
    ("sentence-transformers", ["sentence transformers", "sentence embeddings"]),
    ("datasets",      ["datasets library", "huggingface datasets"]),
]

_INSTRUCTION_TEMPLATES_PKG = [
    "install {pkg} in termux",
    "install {pkg} using termux",
    "how do i install {pkg} on termux",
    "set up {pkg} in termux",
    "get {pkg} running on termux",
    "add {pkg} to termux",
    "download and install {pkg} in termux",
    "i need {pkg} installed in termux",
    "install {alias} in termux",
    "how to install {alias} on my termux",
]

_INSTRUCTION_TEMPLATES_PIP = [
    "install {pkg} with pip",
    "pip install {pkg}",
    "install python package {pkg}",
    "i need the {pkg} python package",
    "how to install {pkg} using pip",
    "install {alias} python library",
    "get {pkg} installed in python",
    "add {pkg} to my python environment",
]

# ── Termux operational commands ───────────────────────────────────────────────

_OPERATIONAL = [
    ("upgrade all termux packages",       "pkg upgrade"),
    ("update termux packages",            "pkg update"),
    ("update and upgrade termux",         "pkg update && pkg upgrade"),
    ("list installed termux packages",    "pkg list-installed"),
    ("search for a package in termux",    "pkg search python"),
    ("show info about a termux package",  "pkg show python"),
    ("uninstall python from termux",      "pkg uninstall python"),
    ("setup termux storage access",       "termux-setup-storage"),
    ("grant storage permissions",         "termux-setup-storage"),
    ("show battery status",               "termux-battery-status"),
    ("send a termux notification",        "termux-notification --content 'Hello from Termux'"),
    ("get clipboard content",             "termux-clipboard-get"),
    ("set clipboard text",                "termux-clipboard-set 'hello'"),
    ("open termux url",                   "termux-open-url https://example.com"),
    ("share a file from termux",          "termux-share file.txt"),
    ("take a photo with termux",          "termux-camera-photo photo.jpg"),
    ("list termux jobs",                  "jobs"),
    ("check termux python version",       "python --version"),
    ("check pip version in termux",       "pip --version"),
    ("show termux environment",           "env"),
    ("list home directory",               "ls ~"),
    ("list current directory",            "ls"),
    ("show current directory",            "pwd"),
    ("go to home directory",              "cd ~"),
    ("make a new directory",              "mkdir myproject"),
    ("create directory myproject",        "mkdir myproject"),
    ("remove a file",                     "rm file.txt"),
    ("show disk usage",                   "df -h"),
    ("show memory usage",                 "free -h"),
    ("show running processes",            "ps aux"),
    ("kill a process by pid",             "kill 1234"),
    ("run a python script",               "python script.py"),
    ("run script.py",                     "python script.py"),
    ("execute app.py",                    "python app.py"),
    ("run main.py in background",         "nohup python main.py &"),
    ("clone a git repo",                  "git clone https://github.com/example/repo"),
    ("initialize a git repo",             "git init"),
    ("check git status",                  "git status"),
    ("add all files to git",              "git add ."),
    ("commit with message",               "git commit -m 'initial commit'"),
    ("push to git remote",                "git push origin main"),
    ("create python virtual environment", "python -m venv venv"),
    ("activate virtualenv",               "source venv/bin/activate"),
    ("freeze pip requirements",           "pip freeze > requirements.txt"),
    ("install from requirements.txt",     "pip install -r requirements.txt"),
    ("show installed pip packages",       "pip list"),
    ("check if port 8080 is in use",      "netstat -tlnp"),
]

# ── Multi-step patterns ───────────────────────────────────────────────────────

_MULTISTEP_PATTERNS = [
    {
        "instruction": "create a python hello world script and run it",
        "tool_calls": [
            {"name": "write_file", "args": {"path": "hello.py", "content": "print('Hello, World!')\n"}},
            {"name": "shell",      "args": {"command": "python hello.py"}},
        ],
    },
    {
        "instruction": "create a flask app on port 9000 and start it",
        "tool_calls": [
            {"name": "write_file", "args": {"path": "app.py", "content": (
                "from flask import Flask\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/')\n"
                "def index():\n"
                "    return 'Hello from Codey!'\n\n"
                "if __name__ == '__main__':\n"
                "    app.run(port=9000)\n"
            )}},
            {"name": "shell", "args": {"command": "python app.py"}},
        ],
    },
    {
        "instruction": "write a fibonacci function and test it",
        "tool_calls": [
            {"name": "write_file", "args": {"path": "fib.py", "content": (
                "def fibonacci(n):\n"
                "    if n <= 1:\n"
                "        return n\n"
                "    return fibonacci(n-1) + fibonacci(n-2)\n"
            )}},
            {"name": "write_file", "args": {"path": "test_fib.py", "content": (
                "from fib import fibonacci\n"
                "assert fibonacci(0) == 0\n"
                "assert fibonacci(1) == 1\n"
                "assert fibonacci(10) == 55\n"
                "print('All tests passed')\n"
            )}},
            {"name": "shell", "args": {"command": "python test_fib.py"}},
        ],
    },
    {
        "instruction": "install numpy and write a script that creates a random array",
        "tool_calls": [
            {"name": "shell",      "args": {"command": "pip install numpy"}},
            {"name": "write_file", "args": {"path": "array_demo.py", "content": (
                "import numpy as np\n"
                "arr = np.random.rand(3, 3)\n"
                "print('Random array:')\n"
                "print(arr)\n"
            )}},
            {"name": "shell", "args": {"command": "python array_demo.py"}},
        ],
    },
    {
        "instruction": "create a simple sqlite database and add a record",
        "tool_calls": [
            {"name": "write_file", "args": {"path": "db_demo.py", "content": (
                "import sqlite3\n"
                "conn = sqlite3.connect('demo.db')\n"
                "conn.execute('CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)')\n"
                "conn.execute(\"INSERT INTO items (name) VALUES ('hello')\")\n"
                "conn.commit()\n"
                "rows = conn.execute('SELECT * FROM items').fetchall()\n"
                "print(rows)\n"
                "conn.close()\n"
            )}},
            {"name": "shell", "args": {"command": "python db_demo.py"}},
        ],
    },
    {
        "instruction": "create a new python project directory with a main file",
        "tool_calls": [
            {"name": "shell",      "args": {"command": "mkdir myproject"}},
            {"name": "write_file", "args": {"path": "myproject/main.py", "content": (
                "def main():\n"
                "    print('Project started')\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            )}},
            {"name": "shell", "args": {"command": "python myproject/main.py"}},
        ],
    },
    {
        "instruction": "read the contents of requirements.txt and install them",
        "tool_calls": [
            {"name": "read_file", "args": {"path": "requirements.txt"}},
            {"name": "shell",     "args": {"command": "pip install -r requirements.txt"}},
        ],
    },
    {
        "instruction": "list files in the current directory and read main.py",
        "tool_calls": [
            {"name": "list_dir",  "args": {"path": "."}},
            {"name": "read_file", "args": {"path": "main.py"}},
        ],
    },
    {
        "instruction": "set up a python virtual environment and install flask",
        "tool_calls": [
            {"name": "shell", "args": {"command": "python -m venv venv"}},
            {"name": "shell", "args": {"command": "pip install flask"}},
        ],
    },
    {
        "instruction": "initialize a git repo and make the first commit",
        "tool_calls": [
            {"name": "shell", "args": {"command": "git init"}},
            {"name": "shell", "args": {"command": "git add ."}},
            {"name": "shell", "args": {"command": "git commit -m 'initial commit'"}},
        ],
    },
]

_MULTISTEP_VARIANTS = [
    "{base}",
    "please {base}",
    "can you {base}",
    "i want to {base}",
    "help me {base}",
]


# ── Generator functions ───────────────────────────────────────────────────────

def _make_record(instruction: str, tool_calls: List[Dict], is_synthetic: bool = True) -> Dict:
    return {
        "instruction": instruction.lower().strip(),
        "output":      json.dumps(tool_calls),
        "is_synthetic": is_synthetic,
        "_extra":      {"tool_calls_prebuilt": tool_calls},
        "_schema_type": "jsonl_generic",
        "_source":     "synthetic",
    }


def generate_termux_corpus() -> List[Dict]:
    """Generate ~5K Termux CLI training examples."""
    records = []

    # pkg install examples
    for pkg, aliases in _PKG_INSTALL:
        for template in _INSTRUCTION_TEMPLATES_PKG:
            for alias in aliases[:2]:  # limit variants per alias
                instr = template.format(pkg=pkg, alias=alias)
                tc    = [{"name": "shell", "args": {"command": f"pkg install {pkg}"}}]
                records.append(_make_record(instr, tc))

    # pip install examples
    for pkg, aliases in _PIP_INSTALL:
        for template in _INSTRUCTION_TEMPLATES_PIP:
            for alias in aliases[:2]:
                instr = template.format(pkg=pkg, alias=alias)
                tc    = [{"name": "shell", "args": {"command": f"pip install {pkg}"}}]
                records.append(_make_record(instr, tc))

    # Operational commands
    for instruction, command in _OPERATIONAL:
        tc = [{"name": "shell", "args": {"command": command}}]
        records.append(_make_record(instruction, tc))

    return records


def generate_multistep_corpus() -> List[Dict]:
    """Generate ~3K multi-step coding training examples."""
    records = []
    for pattern in _MULTISTEP_PATTERNS:
        base = pattern["instruction"]
        tc   = pattern["tool_calls"]
        for variant_tmpl in _MULTISTEP_VARIANTS:
            instr = variant_tmpl.format(base=base)
            records.append(_make_record(instr, tc))
    return records


def write_synthetic_corpora(output_dir: str) -> Dict[str, str]:
    """
    Generate and write both synthetic corpora to JSONL files.

    Args:
        output_dir: Directory to write the files

    Returns:
        Dict mapping corpus name → file path
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    termux_path    = out / "synthetic_termux.jsonl"
    multistep_path = out / "synthetic_multistep.jsonl"

    termux_records    = generate_termux_corpus()
    multistep_records = generate_multistep_corpus()

    with open(termux_path, "w", encoding="utf-8") as f:
        for rec in termux_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with open(multistep_path, "w", encoding="utf-8") as f:
        for rec in multistep_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"  Synthetic Termux corpus:    {len(termux_records):,} records → {termux_path}")
    print(f"  Synthetic multi-step corpus: {len(multistep_records):,} records → {multistep_path}")

    return {
        "termux":    str(termux_path),
        "multistep": str(multistep_path),
    }
