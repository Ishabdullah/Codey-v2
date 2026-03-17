#!/usr/bin/env bash
# setup_skills.sh — Phase 1 (v2.6.1)
#
# Clone skill repositories into knowledge/skills/ and index them into
# the knowledge base for RAG retrieval.
#
# Usage:
#   bash tools/setup_skills.sh
#   bash tools/setup_skills.sh --no-semantic   # skip embedding index build
#
# Run from the codey-v2 root directory.

set -euo pipefail

CODEY_DIR="${CODEY_DIR:-$HOME/codey-v2}"
SKILL_DIR="$CODEY_DIR/knowledge/skills"
NO_SEMANTIC=0

# Parse flags
for arg in "$@"; do
    case "$arg" in
        --no-semantic) NO_SEMANTIC=1 ;;
        --help|-h)
            echo "Usage: bash tools/setup_skills.sh [--no-semantic]"
            exit 0
            ;;
    esac
done

# ── Create directory structure ────────────────────────────────────────────────
echo "=== Codey-v2 Knowledge Base Setup ==="
echo "KB root: $CODEY_DIR/knowledge"
echo ""

mkdir -p "$SKILL_DIR"
mkdir -p "$CODEY_DIR/knowledge/docs"
mkdir -p "$CODEY_DIR/knowledge/apis"
mkdir -p "$CODEY_DIR/knowledge/patterns"
mkdir -p "$CODEY_DIR/knowledge/embeddings"

echo "[1/4] Cloning skill repositories..."

# Clone each repo with --depth 1 (shallow) — fail gracefully
clone_repo() {
    local url="$1"
    local dest="$2"
    local name
    name="$(basename "$dest")"

    if [ -d "$dest/.git" ]; then
        echo "  $name: already cloned, pulling latest..."
        git -C "$dest" pull --quiet --ff-only 2>/dev/null || echo "  $name: pull failed (using existing)"
    else
        echo "  Cloning $name..."
        git clone --depth 1 --quiet "$url" "$dest" 2>/dev/null \
            && echo "  $name: done" \
            || echo "  $name: clone failed (skipping)"
    fi
}

# Original repos
clone_repo "https://github.com/ComposioHQ/awesome-claude-skills.git" \
    "$SKILL_DIR/awesome-claude-skills"

clone_repo "https://github.com/obra/superpowers.git" \
    "$SKILL_DIR/superpowers"

clone_repo "https://github.com/anthropics/skil.git" \
    "$SKILL_DIR/skil"

clone_repo "https://github.com/PleasePrompto/notebooklm-skill.git" \
    "$SKILL_DIR/notebooklm-skill"

# Extended skill repos — TDD, fullstack, DevOps, Agile, git workflows
clone_repo "https://github.com/alirezarezvani/claude-skills.git" \
    "$SKILL_DIR/claude-skills-alirezarezvani"

clone_repo "https://github.com/levnikolaevich/claude-code-skills.git" \
    "$SKILL_DIR/claude-code-skills"

clone_repo "https://github.com/BehiSecc/awesome-claude-skills.git" \
    "$SKILL_DIR/awesome-claude-skills-behisecc"

clone_repo "https://github.com/karanb192/awesome-claude-skills.git" \
    "$SKILL_DIR/awesome-claude-skills-karanb192"

clone_repo "https://github.com/hesreallyhim/awesome-claude-code.git" \
    "$SKILL_DIR/awesome-claude-code"

clone_repo "https://github.com/VoltAgent/awesome-agent-skills.git" \
    "$SKILL_DIR/awesome-agent-skills"

clone_repo "https://github.com/travisvn/awesome-claude-skills.git" \
    "$SKILL_DIR/awesome-claude-skills-travisvn"

echo ""
echo "[2/4] Indexing skill repositories into knowledge base..."

python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ.get("CODEY_DIR", os.path.expanduser("~/codey-v2")))

from tools.kb_scraper import index_directory

skill_dir = os.path.join(os.environ.get("CODEY_DIR", os.path.expanduser("~/codey-v2")), "knowledge", "skills")

repos = [
    ("awesome-claude-skills",          (".md", ".txt", ".yaml", ".yml", ".json")),
    ("superpowers",                    (".md", ".txt", ".py",   ".yaml", ".yml", ".json")),
    ("skil",                           (".md", ".txt", ".py",   ".yaml", ".yml", ".json", ".ts")),
    ("notebooklm-skill",               (".md", ".txt", ".py",   ".yaml", ".yml", ".json")),
    ("claude-skills-alirezarezvani",   (".md", ".txt", ".yaml", ".yml", ".json")),
    ("claude-code-skills",             (".md", ".txt", ".yaml", ".yml", ".json")),
    ("awesome-claude-skills-behisecc", (".md", ".txt", ".yaml", ".yml", ".json")),
    ("awesome-claude-skills-karanb192",(".md", ".txt", ".yaml", ".yml", ".json")),
    ("awesome-claude-code",            (".md", ".txt", ".yaml", ".yml", ".json")),
    ("awesome-agent-skills",           (".md", ".txt", ".yaml", ".yml", ".json")),
    ("awesome-claude-skills-travisvn", (".md", ".txt", ".yaml", ".yml", ".json")),
]

total = 0
for name, exts in repos:
    repo_path = os.path.join(skill_dir, name)
    if os.path.isdir(repo_path):
        print(f"\n--- Indexing {name} ---")
        n = index_directory(repo_path, category=f"skill:{name}", extensions=exts)
        total += n
    else:
        print(f"Skipping {name}: not found at {repo_path}")

print(f"\nTotal: {total} chunks indexed from skill repositories")
PYEOF

echo ""
echo "[3/4] Indexing project knowledge docs (knowledge/docs/)..."

DOCS_DIR="$CODEY_DIR/knowledge/docs"
if [ -d "$DOCS_DIR" ] && [ "$(ls -A "$DOCS_DIR" 2>/dev/null)" ]; then
    python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ.get("CODEY_DIR", os.path.expanduser("~/codey-v2")))
from tools.kb_scraper import index_directory
docs_dir = os.path.join(os.environ.get("CODEY_DIR", os.path.expanduser("~/codey-v2")), "knowledge", "docs")
index_directory(docs_dir, category="docs")
PYEOF
else
    echo "  knowledge/docs/ is empty — add .md/.txt files there to index them"
fi

echo ""

if [ "$NO_SEMANTIC" -eq 0 ]; then
    echo "[4/4] Building semantic index..."
    python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ.get("CODEY_DIR", os.path.expanduser("~/codey-v2")))
try:
    from tools.kb_semantic import (
        build_semantic_index, check_llama_embeddings,
        HAS_FASTEMBED, HAS_SENTENCE_TRANSFORMERS,
    )
    has_llama = check_llama_embeddings()
    if has_llama:
        print("  Embedding backend: llama-server (hybrid BM25 + vector, RRF)")
    elif HAS_FASTEMBED:
        print("  Embedding backend: fastembed (hybrid BM25 + vector, RRF)")
    elif HAS_SENTENCE_TRANSFORMERS:
        print("  Embedding backend: sentence-transformers (hybrid BM25 + vector, RRF)")
    else:
        print("  No vector embedding backend found.")
        print("  BM25 keyword search is active — good enough for most queries.")
        print("")
        print("  To enable hybrid semantic search on Termux/Android:")
        print("    1. Start llama-server (or run: python main.py)")
        print("    2. Re-run: bash tools/setup_skills.sh")
        print("")
        print("  On desktop/server:")
        print("    pip install fastembed   (no torch needed)")
        sys.exit(0)

    n = build_semantic_index()
    if n > 0:
        print(f"  Semantic index ready: {n} embeddings")
    else:
        print("  No chunks to embed — index is empty.")
except Exception as e:
    print(f"  Semantic index failed: {e}")
    print("  BM25 keyword search fallback is still available.")
PYEOF
else
    echo "[4/4] Skipping semantic index (--no-semantic)"
fi

echo ""
echo "=== Setup complete ==="
echo ""

# Print final stats
python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ.get("CODEY_DIR", os.path.expanduser("~/codey-v2")))
try:
    from tools.kb_semantic import index_stats, HAS_SENTENCE_TRANSFORMERS
    s = index_stats()
    print(f"Knowledge base stats:")
    print(f"  Chunk files:     {s['chunk_files']}")
    print(f"  Total chunks:    {s['total_chunks']}")
    print(f"  Semantic index:  {'yes' if s['has_semantic'] else 'no (keyword fallback active)'}")
    print(f"  Sentence-transf: {'installed' if HAS_SENTENCE_TRANSFORMERS else 'not installed'}")
    print(f"  KB root:         {s['kb_root']}")
except Exception as e:
    print(f"Could not read stats: {e}")
PYEOF

echo ""
echo "The knowledge base is ready. Codey will now retrieve relevant"
echo "context from it during inference."
echo ""
echo "To add your own docs:"
echo "  cp my_docs/*.md ~/codey-v2/knowledge/docs/"
echo "  python3 -c \"from tools.kb_scraper import index_directory; index_directory('knowledge/docs', 'docs')\""
echo "  python3 -c \"from tools.kb_semantic import build_semantic_index; build_semantic_index()\""
