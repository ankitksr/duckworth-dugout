"""Wire generators — specialized LLM generators that feed the AI Wire panel.

Each generator focuses on a specific editorial angle, has its own trigger
conditions, sees only relevant context, and produces a small number of
high-quality dispatches. The wire orchestrator runs them (some in parallel)
and aggregates the results.

Generator contract:
    - Subclass WireGenerator
    - Define SOURCE, TOOLS, MODEL, TEMPERATURE
    - Implement should_run() — return True if context changed for this generator
    - Implement build_context() — return the focused context string
    - Implement system_prompt / user_prompt — return prompt strings
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import duckdb
from rich.console import Console

from pipeline.config import DATA_DIR
from pipeline.models import ScheduleMatch

console = Console()

_FRANCHISE_IDS = "rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt"
_VALID_FIDS = {fid.strip() for fid in _FRANCHISE_IDS.split(",")}
_VALID_SEVERITIES = {"signal", "alert", "alarm"}

# Bumped when context_hash semantics change. Prefixed onto every hash so
# legacy DB rows can never collide with hashes from a newer generator
# version — on deploy, generators run fresh exactly once.
HASH_VERSION = "v5"

# Hard ceiling on non-expired entries per source per day. Backstop against
# unbounded accumulation if hashes keep changing despite the previous-entries
# guard. Tuned generously — most days should land well under the cap.
DAILY_CAP: dict[str, int] = {
    "situation": 8,
    "scout": 8,
    "newsdesk": 8,
    "preview": 8,
    "take": 8,
    "archive": 3,
    "fan_desk": 2,
}

# Grounding-contract enforcement mode.
#
#   False → warn-only. Validators log which dispatches would have been
#     dropped, but return items untouched. Use during rollout to calibrate
#     blacklists and enum sets against real LLM output.
#   True  → strict. Validators drop failing items.
#
# Flip to True once the warn-only logs confirm we're only rejecting
# genuinely low-quality dispatches.
_STRICT_GROUNDING = False


def _jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity (case-insensitive, ignores <3-char tokens)."""
    ta = {t for t in re.findall(r"\w+", a.lower()) if len(t) >= 3}
    tb = {t for t in re.findall(r"\w+", b.lower()) if len(t) >= 3}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _validate_grounding(
    source: str,
    item: dict,
    *,
    type_enum: set[str],
    detail_min_chars: int = 15,
    detail_min_words: int = 0,
    cop_outs: tuple[str, ...] = (),
    extra_checks: list | None = None,
) -> str | None:
    """Shared grounding-contract validator.

    Returns None when the item passes; returns a short reason string when
    it fails. Callers decide (per module-level _STRICT_GROUNDING) whether a
    failure drops the item or just logs.

    Checks applied in order:
      1. grounding object present with both `type` and `detail` keys
      2. grounding.type in the desk's enum
      3. grounding.detail is a string of >= detail_min_chars and >= detail_min_words
      4. neither headline nor text contains any cop-out phrase (case-insensitive)
      5. any extra_checks — each a callable(item) -> str|None
    """
    g = item.get("grounding")
    if not isinstance(g, dict):
        return "missing grounding object"

    gtype = (g.get("type") or "").strip().lower()
    if gtype not in type_enum:
        return f"grounding.type={gtype!r} not in {sorted(type_enum)}"

    detail = (g.get("detail") or "").strip()
    if len(detail) < detail_min_chars:
        return f"grounding.detail too short ({len(detail)} < {detail_min_chars})"
    if detail_min_words and len(detail.split()) < detail_min_words:
        return f"grounding.detail too few words ({len(detail.split())} < {detail_min_words})"

    prose = f"{item.get('headline', '')} {item.get('text', '')}".lower()
    for phrase in cop_outs:
        if phrase.lower() in prose:
            return f"cop-out phrase: {phrase!r}"

    for check in extra_checks or []:
        reason = check(item)
        if reason:
            return reason

    return None


def _apply_grounding_filter(
    source: str,
    items: list[dict],
    *,
    type_enum: set[str],
    detail_min_chars: int = 15,
    detail_min_words: int = 0,
    cop_outs: tuple[str, ...] = (),
    extra_checks: list | None = None,
) -> list[dict]:
    """Run _validate_grounding across items; respect _STRICT_GROUNDING.

    Warn-only mode logs the first rejection reason per item and keeps the
    item. Strict mode drops rejected items. Either way, accepted items are
    returned unchanged so downstream stages see the same shape.
    """
    kept: list[dict] = []
    rejected = 0
    for item in items:
        reason = _validate_grounding(
            source, item,
            type_enum=type_enum,
            detail_min_chars=detail_min_chars,
            detail_min_words=detail_min_words,
            cop_outs=cop_outs,
            extra_checks=extra_checks,
        )
        if reason is None:
            kept.append(item)
            continue
        rejected += 1
        mode = "dropped" if _STRICT_GROUNDING else "warn"
        console.print(
            f"  [dim yellow]Wire/{source}: grounding {mode} — "
            f"{reason} | {item.get('headline', '')[:70]!r}[/dim yellow]"
        )
        if not _STRICT_GROUNDING:
            kept.append(item)
    if rejected and _STRICT_GROUNDING:
        console.print(
            f"  [yellow]Wire/{source}: dropped {rejected} dispatch(es) "
            f"failing grounding contract[/yellow]"
        )
    return kept


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@dataclass
class GeneratorContext:
    """Shared data passed to all generators."""

    conn: duckdb.DuckDBPyConnection
    season: str
    today_matches: list[ScheduleMatch]
    standings: list[dict]
    caps: dict | None
    schedule: list[dict] | None
    base_context: str  # shared grounding: roster summary + table snapshot


class WireGenerator(ABC):
    """Base class for all wire generators."""

    # Subclasses must set these
    SOURCE: str = ""           # e.g. "situation", "scout", etc.
    TOOLS: list[str] = []      # tool names this generator can use
    MODEL: str = ""            # "flash" or "pro"
    TEMPERATURE: float = 0.7

    @abstractmethod
    def should_run(self, ctx: GeneratorContext) -> bool:
        """Return True if this generator's context has changed."""
        ...

    @abstractmethod
    def build_context(self, ctx: GeneratorContext) -> str:
        """Build the focused context string for this generator."""
        ...

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this generator."""
        ...

    @abstractmethod
    def user_prompt(self, ctx: GeneratorContext, focused_context: str, previous: str) -> str:
        """Return the user prompt with context injected."""
        ...

    def context_hash(self, ctx: GeneratorContext) -> str:
        """Compute a hash of inputs relevant to this generator.

        Override in subclasses for generator-specific sensitivity. Subclasses
        should anchor the hash to *content* signals (standings, completions,
        article IDs, etc.) so a generator only re-runs when its underlying
        data has actually changed.
        """
        parts = [HASH_VERSION, self.SOURCE]
        if ctx.standings:
            parts.append(json.dumps(
                [(s["short_name"], s["played"], s["wins"]) for s in ctx.standings],
                sort_keys=True,
            ))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def already_ran(self, ctx: GeneratorContext, ctx_hash: str) -> bool:
        """Check if we already generated for this context hash + source.

        Scoped to non-expired rows so yesterday's expired entries don't
        block today's regeneration. Without this, a generator whose hash
        is stable day-over-day (e.g. situation/scout when no match has
        completed) would be silently skipped forever.
        """
        row = ctx.conn.execute(
            """
            SELECT 1 FROM war_room_wire
            WHERE context_hash = ? AND season = ? AND source = ?
              AND expired = FALSE
            LIMIT 1
            """,
            [ctx_hash, ctx.season, self.SOURCE],
        ).fetchone()
        return row is not None

    def get_previous_entries(self, ctx: GeneratorContext, limit: int = 30) -> str:
        """Get recent non-expired entries from THIS generator for repetition avoidance.

        Source-scoped: a generator only sees its own prior dispatches, so the
        anti-repetition signal isn't diluted by unrelated entries from other
        desks. Subclasses may override (e.g. The Take pulls cross-desk history).
        """
        rows = ctx.conn.execute(
            """
            SELECT category, headline, text FROM war_room_wire
            WHERE season = ? AND expired = FALSE AND source = ?
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            [ctx.season, self.SOURCE, limit],
        ).fetchall()
        if not rows:
            return "(none yet — this is the first wire generation)"
        return "\n".join(f"- [{r[0]}] {r[1]}: {r[2]}" for r in rows)

    async def generate(
        self,
        ctx: GeneratorContext,
        *,
        force: bool = False,
    ) -> list[dict]:
        """Run: check should_run + hash, build context, call LLM, parse, return items."""
        if not force and not self.should_run(ctx):
            console.print(f"  [dim]Wire/{self.SOURCE}: skipped (should_run=False)[/dim]")
            return []

        ctx_hash = self.context_hash(ctx)

        if not force and self.already_ran(ctx, ctx_hash):
            console.print(f"  [dim]Wire/{self.SOURCE}: unchanged ({ctx_hash[:8]})[/dim]")
            return []

        # Daily cap backstop — prevents unbounded accumulation if hashes keep
        # changing through the day. Force mode bypasses (it has already
        # expired today's rows in the orchestrator).
        if not force:
            from pipeline.clock import today_ist_iso
            cap = DAILY_CAP.get(self.SOURCE, 8)
            existing = ctx.conn.execute(
                """
                SELECT COUNT(*) FROM war_room_wire
                WHERE season = ? AND source = ?
                  AND match_day = ? AND expired = FALSE
                """,
                [ctx.season, self.SOURCE, today_ist_iso()],
            ).fetchone()[0]
            if existing >= cap:
                console.print(
                    f"  [dim]Wire/{self.SOURCE}: at daily cap "
                    f"({existing}/{cap}) — skipping[/dim]"
                )
                return []

        focused = self.build_context(ctx)
        previous = self.get_previous_entries(ctx)
        sys_prompt = self.system_prompt()
        usr_prompt = self.user_prompt(ctx, focused, previous)

        # Resolve model
        from pipeline.config import GEMINI_MODEL, GEMINI_MODEL_PRO
        model = GEMINI_MODEL_PRO if self.MODEL == "pro" else GEMINI_MODEL

        from pipeline.intel.tools import execute_tool, get_tool_declarations
        from pipeline.llm.gemini import GeminiProvider

        provider = GeminiProvider(model=model, panel=f"wire/{self.SOURCE}")
        tools = get_tool_declarations(self.TOOLS) if self.TOOLS else None

        result = await provider.generate_with_tools(
            usr_prompt,
            system=sys_prompt,
            tools=tools,
            tool_executor=execute_tool if tools else None,
            temperature=self.TEMPERATURE,
        )

        items = self._parse_response(result)
        items = self.filter_items(ctx, items)
        if items:
            console.print(
                f"  [green]Wire/{self.SOURCE}: {len(items)} dispatches[/green]"
            )
        else:
            console.print(
                f"  [yellow]Wire/{self.SOURCE}: no valid items returned[/yellow]"
            )

        # Tag items with source and context hash
        for item in items:
            item["source"] = self.SOURCE
            item["_context_hash"] = ctx_hash

        return items

    def filter_items(
        self, ctx: GeneratorContext, items: list[dict]
    ) -> list[dict]:
        """Hook for subclasses to drop hallucinated/invalid items post-parse.

        Default: identity. Override to enforce per-generator constraints
        (e.g. preview previews must reference today's fixtures).
        """
        return items

    def _parse_response(self, result: dict) -> list[dict]:
        """Parse LLM JSON response into validated dispatch dicts."""
        parsed = result.get("parsed")
        if not parsed:
            text = result.get("text", "").strip()
            if text.startswith("```"):
                text = re.sub(r"```(?:json)?\n?", "", text).strip()
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                m = re.search(r"\[.*\]", text, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group())
                    except (json.JSONDecodeError, ValueError):
                        pass

        items: list[dict] = []
        if parsed and isinstance(parsed, list):
            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                headline = entry.get("headline", "").strip()
                txt = entry.get("text", "").strip()
                if not headline or not txt:
                    continue
                emoji = entry.get("emoji", "").strip()
                if emoji:
                    emoji = emoji[0] if len(emoji) == 1 else emoji[:2]
                category = entry.get("category", "insight").strip()
                severity = entry.get("severity", "signal").strip().lower()
                if severity not in _VALID_SEVERITIES:
                    severity = "signal"
                teams = entry.get("teams", [])
                if isinstance(teams, list):
                    teams = [
                        t.strip().lower() for t in teams
                        if isinstance(t, str) and t.strip().lower() in _VALID_FIDS
                    ]
                else:
                    teams = []
                grounding = entry.get("grounding")
                if not isinstance(grounding, dict):
                    grounding = None
                items.append({
                    "headline": headline, "text": txt, "emoji": emoji,
                    "category": category, "severity": severity, "teams": teams,
                    "grounding": grounding,
                })
        return items
