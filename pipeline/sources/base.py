"""Resilient HTTP fetcher with retry, backoff, rate limiting, and cache integration.

This is the foundation for all data fetching. Every HTTP request goes through
ResilientFetcher, which handles:
  - Disk-based caching (skip if already fetched)
  - Rate limiting per domain (token bucket)
  - Exponential backoff with jitter on failure
  - Configurable retries (default 3)
  - Timeout handling
  - User-Agent rotation
  - Graceful SIGINT handling
"""

import asyncio
import random
import signal
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from rich.console import Console

from pipeline.cache.manager import CacheManager
from pipeline.config import (
    BACKOFF_BASE,
    BACKOFF_MAX,
    JITTER_MAX,
    MAX_RETRIES,
    RATE_LIMITS,
    REQUEST_TIMEOUT_CONNECT,
    REQUEST_TIMEOUT_READ,
    REQUEST_TIMEOUT_READ_LARGE,
    USER_AGENTS,
)

console = Console()


class RateLimiter:
    """Per-domain rate limiter using token bucket."""

    def __init__(self, rates: dict[str, float] | None = None):
        self._rates = rates or RATE_LIMITS
        self._last_request: dict[str, float] = {}

    async def acquire(self, domain: str) -> None:
        """Wait until we're allowed to make a request to this domain."""
        rate = self._rates.get(domain, 1.0)
        min_interval = 1.0 / rate

        now = time.monotonic()
        last = self._last_request.get(domain, 0.0)
        wait = max(0.0, min_interval - (now - last))

        if wait > 0:
            await asyncio.sleep(wait)

        self._last_request[domain] = time.monotonic()


class ResilientFetcher:
    """Async HTTP client with retry, caching, and rate limiting."""

    def __init__(self, cache: CacheManager | None = None):
        self.cache = cache or CacheManager()
        self.rate_limiter = RateLimiter()
        self._shutdown = False
        self._client: httpx.AsyncClient | None = None

        # Register SIGINT handler for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum: int, frame: object) -> None:
        console.print("\n[yellow]Graceful shutdown requested. Finishing current request...[/]")
        self._shutdown = True

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=REQUEST_TIMEOUT_CONNECT,
                    read=REQUEST_TIMEOUT_READ,
                    write=30.0,
                    pool=30.0,
                ),
                http2=True,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self, url: str = "") -> dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html, application/json, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }

    async def fetch_json(
        self,
        url: str,
        *,
        cache_source: str,
        cache_category: str,
        cache_key: str,
        params: dict | None = None,
        force: bool = False,
    ) -> dict | list | None:
        """Fetch JSON from a URL, using cache if available.

        Returns the parsed JSON, or None if the request failed after retries.
        """
        # Check cache first
        if not force and self.cache.has(cache_source, cache_category, cache_key):
            return self.cache.read_json(cache_source, cache_category, cache_key)

        # Fetch
        data = await self._request(url, params=params, expect="json")
        if data is not None:
            self.cache.write_json(cache_source, cache_category, cache_key, data)
        return data

    async def fetch_text(
        self,
        url: str,
        *,
        cache_source: str,
        cache_category: str,
        cache_key: str,
        ext: str = ".html",
        params: dict | None = None,
        force: bool = False,
    ) -> str | None:
        """Fetch text/HTML from a URL, using cache if available."""
        if not force and self.cache.has(cache_source, cache_category, cache_key, ext=ext):
            return self.cache.read_text(cache_source, cache_category, cache_key, ext=ext)

        text = await self._request(url, params=params, expect="text")
        if text is not None:
            self.cache.write_text(cache_source, cache_category, cache_key, text, ext=ext)
        return text

    async def fetch_bytes(
        self,
        url: str,
        *,
        cache_source: str,
        cache_category: str,
        cache_key: str,
        ext: str = ".zip",
        force: bool = False,
    ) -> bytes | None:
        """Fetch binary data from a URL, using cache if available."""
        if not force and self.cache.has(cache_source, cache_category, cache_key, ext=ext):
            return self.cache.read_bytes(cache_source, cache_category, cache_key, ext=ext)

        data = await self._request(url, expect="bytes")
        if data is not None:
            self.cache.write_bytes(cache_source, cache_category, cache_key, data, ext=ext)
        return data

    async def fetch_stream(
        self,
        url: str,
        *,
        dest_path: Path,
        force: bool = False,
    ) -> Path | None:
        """Stream a large file directly to disk with retry and rate limiting.

        Returns the destination path on success, or None on failure.
        Skips download if file already exists (unless force=True).
        """
        if not force and dest_path.exists():
            return dest_path

        domain = urlparse(url).hostname or ""

        for attempt in range(MAX_RETRIES + 1):
            if self._shutdown:
                console.print("[yellow]Shutdown: skipping remaining requests[/]")
                return None

            try:
                await self.rate_limiter.acquire(domain)
                timeout = httpx.Timeout(
                    connect=REQUEST_TIMEOUT_CONNECT,
                    read=REQUEST_TIMEOUT_READ_LARGE,
                    write=30.0,
                    pool=30.0,
                )
                async with httpx.AsyncClient(
                    timeout=timeout, follow_redirects=True
                ) as stream_client:
                    async with stream_client.stream(
                        "GET", url, headers=self._get_headers(url)
                    ) as response:
                        if response.status_code >= 400:
                            if response.status_code == 429:
                                wait = self._backoff_time(attempt) * 3
                                console.print(
                                    f"[yellow]Rate limited on {domain}, waiting {wait:.1f}s[/]"
                                )
                                await asyncio.sleep(wait)
                                continue
                            if response.status_code >= 500 and attempt < MAX_RETRIES:
                                wait = self._backoff_time(attempt)
                                console.print(
                                    f"[yellow]{response.status_code} from {domain}, "
                                    f"retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s[/]"
                                )
                                await asyncio.sleep(wait)
                                continue
                            console.print(
                                f"[red]HTTP {response.status_code} downloading {url}[/]"
                            )
                            return None

                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
                        try:
                            with open(tmp_path, "wb") as f:
                                async for chunk in response.aiter_bytes(
                                    chunk_size=64 * 1024
                                ):
                                    f.write(chunk)
                            tmp_path.rename(dest_path)
                            return dest_path
                        except BaseException:
                            tmp_path.unlink(missing_ok=True)
                            raise

            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    wait = self._backoff_time(attempt)
                    console.print(
                        f"[yellow]Timeout streaming {domain}, "
                        f"retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s[/]"
                    )
                    await asyncio.sleep(wait)
                else:
                    console.print(f"[red]Timeout after {MAX_RETRIES} retries: {url}[/]")
                    return None

            except httpx.HTTPError as e:
                if attempt < MAX_RETRIES:
                    wait = self._backoff_time(attempt)
                    console.print(
                        f"[yellow]HTTP error ({e}) streaming {domain}, "
                        f"retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s[/]"
                    )
                    await asyncio.sleep(wait)
                else:
                    console.print(
                        f"[red]HTTP error after {MAX_RETRIES} retries: {url} — {e}[/]"
                    )
                    return None

        return None

    async def _request(
        self,
        url: str,
        *,
        params: dict | None = None,
        expect: str = "json",
    ) -> dict | list | str | bytes | None:
        """Make an HTTP request with retry and backoff."""
        domain = urlparse(url).hostname or ""
        client = await self._get_client()

        for attempt in range(MAX_RETRIES + 1):
            if self._shutdown:
                console.print("[yellow]Shutdown: skipping remaining requests[/]")
                return None

            try:
                await self.rate_limiter.acquire(domain)
                response = await client.get(url, params=params, headers=self._get_headers(url))

                if response.status_code == 429:
                    wait = self._backoff_time(attempt) * 3  # Extra penalty for rate limit
                    console.print(f"[yellow]Rate limited on {domain}, waiting {wait:.1f}s[/]")
                    await asyncio.sleep(wait)
                    continue

                if response.status_code == 403:
                    console.print(f"[red]403 Forbidden: {url}[/]")
                    return None

                if response.status_code >= 500:
                    if attempt < MAX_RETRIES:
                        wait = self._backoff_time(attempt)
                        console.print(
                            f"[yellow]{response.status_code} from {domain}, "
                            f"retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s[/]"
                        )
                        await asyncio.sleep(wait)
                        continue
                    console.print(
                        f"[red]{response.status_code} after {MAX_RETRIES} retries: {url}[/]"
                    )
                    return None

                response.raise_for_status()

                if expect == "json":
                    return response.json()
                elif expect == "bytes":
                    return response.content
                else:
                    return response.text

            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    wait = self._backoff_time(attempt)
                    console.print(
                        f"[yellow]Timeout on {domain}, "
                        f"retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s[/]"
                    )
                    await asyncio.sleep(wait)
                else:
                    console.print(f"[red]Timeout after {MAX_RETRIES} retries: {url}[/]")
                    return None

            except httpx.HTTPError as e:
                if attempt < MAX_RETRIES:
                    wait = self._backoff_time(attempt)
                    console.print(
                        f"[yellow]HTTP error ({e}) on {domain}, "
                        f"retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s[/]"
                    )
                    await asyncio.sleep(wait)
                else:
                    console.print(f"[red]HTTP error after {MAX_RETRIES} retries: {url} — {e}[/]")
                    return None

        return None

    @staticmethod
    def _backoff_time(attempt: int) -> float:
        """Calculate exponential backoff with jitter."""
        base = min(BACKOFF_BASE * (2**attempt), BACKOFF_MAX)
        jitter = random.uniform(0, JITTER_MAX)
        return base + jitter
