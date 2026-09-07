"""
shared/utils.py
Helper utilities shared across all five RAG projects.
"""

import os
import sys
import time
import logging
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional
from functools import wraps

logger = logging.getLogger(__name__)


def add_project_root(file: str) -> None:
    """
    Add the repo root to sys.path so that `from shared.x import y` works
    when running a script from within a project sub-directory.

    Usage (at top of any project file):
        from shared.utils import add_project_root
        add_project_root(__file__)
    """
    root = str(Path(file).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)


def timeit(fn):
    """Decorator that logs execution time of any function."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - start
        logger.info("%s completed in %.2fs", fn.__name__, elapsed)
        return result
    return wrapper


def hash_file(path: str) -> str:
    """Return a short SHA-256 hex digest for a file — used for cache keys."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def ensure_dir(path: str) -> str:
    """Create directory if it doesn't exist; return the path."""
    os.makedirs(path, exist_ok=True)
    return path


def truncate(text: str, max_chars: int = 300) -> str:
    """Truncate text to max_chars with an ellipsis."""
    return text[:max_chars] + "…" if len(text) > max_chars else text


def format_sources(source_nodes: List[Any]) -> List[Dict]:
    """
    Normalise LlamaIndex source nodes into a clean dict list
    suitable for displaying in any UI.
    """
    out = []
    for node in source_nodes:
        meta = getattr(node, "metadata", {}) or {}
        out.append({
            "file": meta.get("file_name", meta.get("source", "unknown")),
            "page": meta.get("page_label", meta.get("page", "—")),
            "score": round(getattr(node, "score", 0) or 0, 4),
            "excerpt": truncate(node.text or "", 250),
        })
    return out


def pretty_sources(sources: List[Dict]) -> str:
    """Return a markdown-formatted source attribution block."""
    if not sources:
        return ""
    lines = ["\n\n---\n**Sources used:**"]
    for i, s in enumerate(sources, 1):
        lines.append(
            f"{i}. **{s['file']}** (page {s['page']}) — "
            f"relevance {s['score']}\n   > {s['excerpt']}"
        )
    return "\n".join(lines)


def check_ollama_running(base_url: str = "http://localhost:11434") -> bool:
    """Return True if Ollama is reachable."""
    try:
        import requests
        r = requests.get(f"{base_url}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def ollama_warning() -> Optional[str]:
    """Return a warning string if Ollama is not running, else None."""
    from shared.config import config
    if config.embed_provider == "ollama" and not check_ollama_running(config.ollama_base_url):
        return (
            "⚠️ Ollama is not running. Start it with: `ollama serve`\n"
            f"Then ensure the model is pulled: `ollama pull {config.ollama_embed_model}`"
        )
    return None
