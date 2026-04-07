"""LLM response caching — prompt hash to response.

Extends the existing CacheManager pattern. Each LLM call is keyed by
a deterministic hash of (model + prompt), stored under cache/llm/{task}/{hash}.json.
Prompt changes naturally invalidate the cache.
"""

import hashlib
import json
from typing import Any

from pipeline.cache.manager import CacheManager


class LLMCache:
    """Cache LLM responses keyed by (task, prompt_hash)."""

    _SOURCE = "llm"

    def __init__(self, cache: CacheManager | None = None):
        self._cache = cache or CacheManager()

    @staticmethod
    def make_key(model: str, prompt: str) -> str:
        """Deterministic hash of model + prompt content."""
        content = json.dumps({"model": model, "prompt": prompt}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:24]

    def get(self, task: str, key: str) -> dict[str, Any] | None:
        """Retrieve a cached LLM response. Returns None on miss."""
        return self._cache.read_json(self._SOURCE, task, key)

    def put(self, task: str, key: str, response: dict[str, Any]) -> None:
        """Store an LLM response in the cache."""
        self._cache.write_json(self._SOURCE, task, key, response)

    def delete(self, task: str, key: str) -> bool:
        """Delete a cached LLM response. Returns True if it existed."""
        return self._cache.delete(self._SOURCE, task, key)

    def has(self, task: str, key: str) -> bool:
        """Check if a cache entry exists."""
        return self._cache.has(self._SOURCE, task, key)
