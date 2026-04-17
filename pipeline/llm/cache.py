"""LLM response caching — prompt hash to response.

Extends the existing CacheManager pattern. Each LLM call is keyed by
a deterministic hash of (model + prompt), stored under cache/llm/{task}/{hash}.json.
Prompt changes naturally invalidate the cache.

Cache hits emit a zero-cost row to the `llm_usage` ledger so effective
hit-rate and savings are queryable. Construct with `panel="..."` to tag
those rows — unlabelled instances log under panel="unknown".
"""

import hashlib
import json
from typing import Any

from pipeline.cache.manager import CacheManager


class LLMCache:
    """Cache LLM responses keyed by (task, prompt_hash)."""

    _SOURCE = "llm"

    def __init__(
        self,
        cache: CacheManager | None = None,
        *,
        panel: str | None = None,
        model: str | None = None,
    ):
        self._cache = cache or CacheManager()
        self._panel = panel or "unknown"
        self._model = model or "unknown"

    @staticmethod
    def make_key(model: str, prompt: str) -> str:
        """Deterministic hash of model + prompt content."""
        content = json.dumps({"model": model, "prompt": prompt}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:24]

    def get(
        self,
        task: str,
        key: str,
        *,
        sub_key: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a cached LLM response. Returns None on miss.

        On hit, emits an `app_cache_hit=True` ledger row (cost 0) so
        cache utility is queryable alongside real calls.
        """
        value = self._cache.read_json(self._SOURCE, task, key)
        if value is not None:
            self._record_cache_hit(task=task, sub_key=sub_key)
        return value

    def put(self, task: str, key: str, response: dict[str, Any]) -> None:
        """Store an LLM response in the cache."""
        self._cache.write_json(self._SOURCE, task, key, response)

    def delete(self, task: str, key: str) -> bool:
        """Delete a cached LLM response. Returns True if it existed."""
        return self._cache.delete(self._SOURCE, task, key)

    def has(self, task: str, key: str) -> bool:
        """Check if a cache entry exists."""
        return self._cache.has(self._SOURCE, task, key)

    def _record_cache_hit(self, *, task: str, sub_key: str | None) -> None:
        """Emit a zero-cost ledger row for an app-layer cache hit."""
        from pipeline.llm.usage_ledger import UsageEvent, record

        record(UsageEvent(
            panel=self._panel,
            provider="gemini",
            model=self._model,
            app_cache_hit=True,
            sub_key=sub_key or task,
        ))
