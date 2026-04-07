"""Generic RSS/Atom feed fetcher with poll-based new-item detection.

Fetches any RSS 2.0 or Atom feed, parses it into structured FeedItem objects,
and tracks seen items by GUID/link across polls for incremental processing.

State is persisted to a JSON file in cache/rss/ for restartability. Seen GUIDs
are capped at 500 entries (FIFO eviction) to prevent unbounded growth.

Usage:
    fetcher = RSSFetcher("https://example.com/feed.xml")
    new_items = fetcher.poll()   # returns only items not seen before
    all_items = fetcher.fetch()  # returns every item in the feed
"""

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from rich.console import Console

from pipeline.config import CACHE_DIR

console = Console()

# Atom namespace
_ATOM_NS = "http://www.w3.org/2005/Atom"

# Max seen GUIDs to persist (FIFO eviction beyond this)
_MAX_SEEN_GUIDS = 500

# Simple HTML tag stripper
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str | None:
    """Remove HTML tags and collapse whitespace."""
    if text is None:
        return None
    cleaned = _HTML_TAG_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _parse_datetime(text: str | None) -> datetime | None:
    """Parse RSS (RFC 2822) or Atom (ISO 8601) date strings."""
    if not text:
        return None
    text = text.strip()
    # Try RFC 2822 first (RSS 2.0 pubDate)
    try:
        return parsedate_to_datetime(text)
    except (ValueError, TypeError):
        pass
    # Try ISO 8601 (Atom updated/published)
    try:
        # Handle Z suffix
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        pass
    return None


def _element_text(element: ET.Element | None) -> str | None:
    """Safely extract text content from an XML element."""
    if element is None:
        return None
    return element.text.strip() if element.text else None


@dataclass
class FeedItem:
    """A single item from an RSS/Atom feed."""

    guid: str
    """Unique identifier (from <guid>, <id>, or <link>)."""

    title: str
    """Item title."""

    link: str | None = None
    """URL to the full content."""

    description: str | None = None
    """Summary text (HTML stripped)."""

    published: datetime | None = None
    """Publication timestamp."""

    categories: list[str] = field(default_factory=list)
    """Category/tag labels from <category> elements."""

    raw: dict = field(default_factory=dict)
    """All parsed fields for source-specific extraction."""


class RSSFetcher:
    """Fetches and parses RSS 2.0 / Atom feeds with incremental polling.

    Parameters
    ----------
    feed_url : str
        The RSS/Atom feed URL to fetch.
    state_path : Path | None
        Where to persist seen GUIDs. Defaults to ``cache/rss/{feed_name}.json``
        where feed_name is derived from the URL hostname + path.
    timeout : float
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        feed_url: str,
        *,
        state_path: Path | None = None,
        timeout: float = 30.0,
    ):
        self.feed_url = feed_url
        self.timeout = timeout

        if state_path is not None:
            self._state_path = state_path
        else:
            # Derive a sensible filename from the URL
            parsed = urlparse(feed_url)
            slug = (parsed.hostname or "feed") + parsed.path.replace("/", "_")
            slug = re.sub(r"[^a-zA-Z0-9_.-]", "", slug)
            self._state_path = CACHE_DIR / "rss" / f"{slug}.json"

        # In-memory set of seen GUIDs, loaded from disk on first access
        self._seen_guids: list[str] | None = None

    # ── Public API ────────────────────────────────────────────────────────

    def fetch(self) -> list[FeedItem]:
        """Fetch the feed and parse all items. Does not update seen state."""
        xml_text = self._http_get()
        if xml_text is None:
            return []
        return self._parse_feed(xml_text)

    def poll(self) -> list[FeedItem]:
        """Fetch the feed, return only NEW items since last poll. Updates state."""
        all_items = self.fetch()
        seen = self._load_seen()
        seen_set = set(seen)

        new_items = [item for item in all_items if item.guid not in seen_set]

        if new_items:
            # Add new GUIDs, maintaining FIFO order
            for item in new_items:
                seen.append(item.guid)
            # Evict oldest if over cap
            if len(seen) > _MAX_SEEN_GUIDS:
                seen = seen[-_MAX_SEEN_GUIDS:]
            self._save_seen(seen)

        return new_items

    def reset(self) -> None:
        """Clear seen-item state, so next poll returns all items as new."""
        self._seen_guids = []
        if self._state_path.exists():
            self._state_path.unlink()
            console.print(f"[dim]RSS state cleared: {self._state_path}[/dim]")

    # ── HTTP ──────────────────────────────────────────────────────────────

    def _http_get(self) -> str | None:
        """Fetch the feed URL synchronously via httpx."""
        try:
            response = httpx.get(
                self.feed_url,
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": (
                        "application/rss+xml, application/atom+xml, "
                        "application/xml, text/xml, */*"
                    ),
                },
            )
            response.raise_for_status()
            return response.text
        except httpx.TimeoutException:
            console.print(f"[red]RSS fetch timeout: {self.feed_url}[/red]")
            return None
        except httpx.HTTPStatusError as exc:
            console.print(f"[red]RSS fetch HTTP {exc.response.status_code}: {self.feed_url}[/red]")
            return None
        except httpx.HTTPError as exc:
            console.print(f"[red]RSS fetch error: {exc}[/red]")
            return None

    # ── Parsing ───────────────────────────────────────────────────────────

    def _parse_feed(self, xml_text: str) -> list[FeedItem]:
        """Parse an RSS 2.0 or Atom feed from raw XML text."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            console.print(f"[red]RSS XML parse error: {exc}[/red]")
            return []

        # Detect feed format
        tag = root.tag.lower()
        if tag == "rss" or tag.endswith("}rss"):
            return self._parse_rss(root)
        elif tag == "feed" or tag.endswith("}feed") or f"{{{_ATOM_NS}}}" in root.tag:
            return self._parse_atom(root)
        else:
            # Try RSS — some feeds have <rdf:RDF> or other wrappers
            items = root.findall(".//item")
            if items:
                return self._parse_rss(root)
            entries = root.findall(f".//{{{_ATOM_NS}}}entry")
            if entries:
                return self._parse_atom(root)
            console.print(f"[yellow]RSS: unrecognized feed format (root tag: {root.tag})[/yellow]")
            return []

    def _parse_rss(self, root: ET.Element) -> list[FeedItem]:
        """Parse RSS 2.0 items from the XML tree."""
        items: list[FeedItem] = []
        for item_el in root.findall(".//item"):
            raw: dict = {}

            title = _element_text(item_el.find("title")) or ""
            raw["title"] = title

            link = _element_text(item_el.find("link"))
            raw["link"] = link

            description_raw = _element_text(item_el.find("description"))
            raw["description_raw"] = description_raw
            description = _strip_html(description_raw)

            guid_el = item_el.find("guid")
            guid = _element_text(guid_el) or link or title
            raw["guid"] = guid

            pub_date_str = _element_text(item_el.find("pubDate"))
            raw["pubDate"] = pub_date_str
            published = _parse_datetime(pub_date_str)

            categories = [
                cat.text.strip()
                for cat in item_el.findall("category")
                if cat.text
            ]
            raw["categories"] = categories

            # Explicitly extract content:encoded (WordPress feeds)
            content_ns = "{http://purl.org/rss/1.0/modules/content/}encoded"
            content_el = item_el.find(content_ns)
            if content_el is not None and content_el.text:
                raw["encoded"] = content_el.text

            # Capture any extra elements
            for child in item_el:
                tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag_name not in raw:
                    text = "".join(child.itertext()).strip()
                    if text:
                        raw[tag_name] = text

            if guid:
                items.append(FeedItem(
                    guid=guid,
                    title=title,
                    link=link,
                    description=description,
                    published=published,
                    categories=categories,
                    raw=raw,
                ))

        return items

    def _parse_atom(self, root: ET.Element) -> list[FeedItem]:
        """Parse Atom entries from the XML tree."""
        items: list[FeedItem] = []

        def _find(parent: ET.Element, local_name: str) -> ET.Element | None:
            """Find a child element in the Atom namespace or bare."""
            el = parent.find(f"{{{_ATOM_NS}}}{local_name}")
            if el is None:
                el = parent.find(local_name)
            return el

        for entry in root.findall(f"{{{_ATOM_NS}}}entry") or root.findall("entry"):
            raw: dict = {}

            title_el = _find(entry, "title")
            title = _element_text(title_el) or ""
            raw["title"] = title

            # Atom links are attributes: <link href="..." rel="alternate"/>
            link = None
            for link_el in entry.findall(f"{{{_ATOM_NS}}}link") or entry.findall("link"):
                rel = link_el.get("rel", "alternate")
                if rel == "alternate":
                    link = link_el.get("href")
                    break
            if link is None:
                # Fallback: first link element
                first_link = _find(entry, "link")
                if first_link is not None:
                    link = first_link.get("href") or _element_text(first_link)
            raw["link"] = link

            id_el = _find(entry, "id")
            guid = _element_text(id_el) or link or title
            raw["id"] = guid

            summary_el = _find(entry, "summary") or _find(entry, "content")
            summary_raw = _element_text(summary_el)
            raw["summary_raw"] = summary_raw
            description = _strip_html(summary_raw)

            updated_str = _element_text(_find(entry, "updated"))
            published_str = _element_text(_find(entry, "published")) or updated_str
            raw["published"] = published_str
            raw["updated"] = updated_str
            published = _parse_datetime(published_str)

            categories = [
                cat.get("term", "").strip()
                for cat in entry.findall(f"{{{_ATOM_NS}}}category") or entry.findall("category")
                if cat.get("term")
            ]
            raw["categories"] = categories

            if guid:
                items.append(FeedItem(
                    guid=guid,
                    title=title,
                    link=link,
                    description=description,
                    published=published,
                    categories=categories,
                    raw=raw,
                ))

        return items

    # ── State persistence ─────────────────────────────────────────────────

    def _load_seen(self) -> list[str]:
        """Load seen GUIDs from disk (or return cached in-memory list)."""
        if self._seen_guids is not None:
            return self._seen_guids

        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._seen_guids = data.get("seen_guids", [])
            except (json.JSONDecodeError, KeyError):
                console.print(
                    f"[yellow]RSS: corrupt state file, resetting: "
                    f"{self._state_path}[/yellow]"
                )
                self._seen_guids = []
        else:
            self._seen_guids = []

        return self._seen_guids

    def _save_seen(self, seen: list[str]) -> None:
        """Persist seen GUIDs to disk."""
        self._seen_guids = seen
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "feed_url": self.feed_url,
            "last_poll": datetime.now(timezone.utc).isoformat(),
            "seen_guids": seen,
        }
        self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
