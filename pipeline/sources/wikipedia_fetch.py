"""Fetch IPL Wikipedia season pages via the MediaWiki API."""

from pathlib import Path

import httpx

from pipeline.cache.manager import CacheManager
from pipeline.config import (
    REQUEST_TIMEOUT_CONNECT,
    REQUEST_TIMEOUT_READ,
    WIKIPEDIA_API_BASE,
    WIKIPEDIA_IPL_PERSONNEL_TEMPLATE,
    WIKIPEDIA_IPL_TITLE_TEMPLATE,
)
from pipeline.sources.base import ResilientFetcher


def _cache_path(cache: CacheManager, key: str) -> Path:
    safe_key = cache._safe_filename(key)
    return cache.base_dir / "wikipedia" / "ipl" / f"{safe_key}.json"


def _extract_wikitext(payload: dict | list | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    return payload.get("parse", {}).get("wikitext", {}).get("*")


class IPLWikipediaFetcher:
    """Thin IPL-specific wrapper around the existing MediaWiki fetch flow."""

    def __init__(self, fetcher: ResilientFetcher, cache: CacheManager):
        self.fetcher = fetcher
        self.cache = cache

    async def fetch_season_page(self, season: int, *, force: bool = False) -> str | None:
        title = WIKIPEDIA_IPL_TITLE_TEMPLATE.format(year=season)
        payload = await self.fetcher.fetch_json(
            WIKIPEDIA_API_BASE,
            params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "format": "json",
            },
            cache_source="wikipedia",
            cache_category="ipl",
            cache_key=f"season_{season}",
            force=force,
        )
        return _extract_wikitext(payload)

    async def fetch_personnel_page(self, season: int, *, force: bool = False) -> str | None:
        title = WIKIPEDIA_IPL_PERSONNEL_TEMPLATE.format(year=season)
        payload = await self.fetcher.fetch_json(
            WIKIPEDIA_API_BASE,
            params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "format": "json",
            },
            cache_source="wikipedia",
            cache_category="ipl",
            cache_key=f"personnel_{season}",
            force=force,
        )
        return _extract_wikitext(payload)


def fetch_season_wikitext(
    season: int,
    *,
    force: bool = False,
    cache: CacheManager | None = None,
) -> str | None:
    """Sync helper for war-room code paths."""
    cache = cache or CacheManager()
    cache_key = f"live_season_{season}"
    path = _cache_path(cache, cache_key)

    if not force and path.exists():
        return _extract_wikitext(cache.read_json("wikipedia", "ipl", cache_key))

    title = WIKIPEDIA_IPL_TITLE_TEMPLATE.format(year=season)
    with httpx.Client(
        timeout=httpx.Timeout(
            connect=REQUEST_TIMEOUT_CONNECT,
            read=REQUEST_TIMEOUT_READ,
            write=30.0,
            pool=30.0,
        ),
        follow_redirects=True,
        http2=True,
        headers={
            "User-Agent": "cricket-timeline/1.0 (+https://en.wikipedia.org/wiki/Main_Page)",
            "Accept": "application/json",
        },
    ) as client:
        response = client.get(
            WIKIPEDIA_API_BASE,
            params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "format": "json",
            },
        )
        response.raise_for_status()
        payload = response.json()

    if isinstance(payload, dict) and "error" in payload:
        return None

    cache.write_json("wikipedia", "ipl", cache_key, payload)
    return _extract_wikitext(payload)


def fetch_personnel_wikitext(
    season: int,
    *,
    force: bool = False,
    cache: CacheManager | None = None,
) -> str | None:
    """Sync helper — fetch the IPL personnel changes Wikipedia page."""
    cache = cache or CacheManager()
    cache_key = f"personnel_{season}"
    path = _cache_path(cache, cache_key)

    if not force and path.exists():
        return _extract_wikitext(cache.read_json("wikipedia", "ipl", cache_key))

    title = WIKIPEDIA_IPL_PERSONNEL_TEMPLATE.format(year=season)
    with httpx.Client(
        timeout=httpx.Timeout(
            connect=REQUEST_TIMEOUT_CONNECT,
            read=REQUEST_TIMEOUT_READ,
            write=30.0,
            pool=30.0,
        ),
        follow_redirects=True,
        http2=True,
        headers={
            "User-Agent": "cricket-timeline/1.0 (+https://en.wikipedia.org/wiki/Main_Page)",
            "Accept": "application/json",
        },
    ) as client:
        response = client.get(
            WIKIPEDIA_API_BASE,
            params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "format": "json",
            },
        )
        response.raise_for_status()
        payload = response.json()

    if isinstance(payload, dict) and "error" in payload:
        return None

    cache.write_json("wikipedia", "ipl", cache_key, payload)
    return _extract_wikitext(payload)
