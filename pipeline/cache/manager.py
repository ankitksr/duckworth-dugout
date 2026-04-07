"""Disk-based cache for raw HTTP responses.

Every fetch goes through this cache. Files are keyed by source/category/id.
The cache is append-only — once written, a file is never modified or deleted.
This makes the pipeline restartable: if it crashes, restarting will skip
everything already cached.
"""

import hashlib
import json
from pathlib import Path

from pipeline.config import CACHE_DIR, MANIFESTS_DIR


class CacheManager:
    """Manages the raw response cache on disk."""

    def __init__(self, base_dir: Path = CACHE_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, source: str, category: str, key: str, ext: str = ".json") -> Path:
        """Build cache file path: cache/{source}/{category}/{key}.{ext}"""
        safe_key = self._safe_filename(key)
        return self.base_dir / source / category / f"{safe_key}{ext}"

    @staticmethod
    def _safe_filename(key: str) -> str:
        """Convert a key to a safe filename. Use hash for long/complex keys."""
        safe = key.replace("/", "_").replace("\\", "_").replace(" ", "_")
        if len(safe) > 200:
            return hashlib.sha256(key.encode()).hexdigest()[:16] + "_" + safe[:50]
        return safe

    def has(self, source: str, category: str, key: str, ext: str = ".json") -> bool:
        """Check if a cache entry exists."""
        return self._path(source, category, key, ext).exists()

    def read_json(self, source: str, category: str, key: str) -> dict | list | None:
        """Read a cached JSON response. Returns None if not cached."""
        path = self._path(source, category, key, ".json")
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, source: str, category: str, key: str, data: dict | list) -> Path:
        """Write a JSON response to cache. Returns the file path."""
        path = self._path(source, category, key, ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_text(self, source: str, category: str, key: str, ext: str = ".html") -> str | None:
        """Read a cached text response."""
        path = self._path(source, category, key, ext)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write_text(
        self, source: str, category: str, key: str, text: str, ext: str = ".html"
    ) -> Path:
        """Write a text response to cache."""
        path = self._path(source, category, key, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def read_bytes(self, source: str, category: str, key: str, ext: str = ".zip") -> bytes | None:
        """Read a cached binary response."""
        path = self._path(source, category, key, ext)
        if not path.exists():
            return None
        return path.read_bytes()

    def write_bytes(
        self, source: str, category: str, key: str, data: bytes, ext: str = ".zip"
    ) -> Path:
        """Write a binary response to cache."""
        path = self._path(source, category, key, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def delete(self, source: str, category: str, key: str, ext: str = ".json") -> bool:
        """Delete a cache entry. Returns True if it existed."""
        path = self._path(source, category, key, ext)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_keys(self, source: str, category: str, ext: str = ".json") -> list[str]:
        """List all cached keys for a source/category."""
        dir_path = self.base_dir / source / category
        if not dir_path.exists():
            return []
        return [p.stem for p in dir_path.glob(f"*{ext}")]

    # ── Phase Manifests ────────────────────────────────────────────────────

    def mark_phase_done(self, phase_name: str) -> None:
        """Mark a pipeline phase as completed."""
        MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
        (MANIFESTS_DIR / f"{phase_name}.done").touch()

    def is_phase_done(self, phase_name: str) -> bool:
        """Check if a pipeline phase was previously completed."""
        return (MANIFESTS_DIR / f"{phase_name}.done").exists()

    def clear_phase(self, phase_name: str) -> None:
        """Clear a phase completion marker (for re-running)."""
        marker = MANIFESTS_DIR / f"{phase_name}.done"
        if marker.exists():
            marker.unlink()
