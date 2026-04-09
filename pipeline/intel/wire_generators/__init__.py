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

        Override in subclasses for generator-specific sensitivity.
        Default: hash of source name + standings + schedule status.
        """
        parts = [self.SOURCE]
        if ctx.standings:
            parts.append(json.dumps(
                [(s["short_name"], s["played"], s["wins"]) for s in ctx.standings],
                sort_keys=True,
            ))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def already_ran(self, ctx: GeneratorContext, ctx_hash: str) -> bool:
        """Check if we already generated for this context hash + source."""
        row = ctx.conn.execute(
            """
            SELECT 1 FROM war_room_wire
            WHERE context_hash = ? AND season = ? AND source = ?
            LIMIT 1
            """,
            [ctx_hash, ctx.season, self.SOURCE],
        ).fetchone()
        return row is not None

    def get_previous_entries(self, ctx: GeneratorContext, limit: int = 20) -> str:
        """Get recent non-expired entries for repetition avoidance."""
        rows = ctx.conn.execute(
            """
            SELECT source, category, headline, text FROM war_room_wire
            WHERE season = ? AND expired = FALSE
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            [ctx.season, limit],
        ).fetchall()
        if not rows:
            return "(none yet — this is the first wire generation)"
        return "\n".join(
            f"- [{r[0]}:{r[1]}] {r[2]}: {r[3]}" for r in rows
        )

    async def generate(
        self,
        ctx: GeneratorContext,
        *,
        force: bool = False,
    ) -> list[dict]:
        """Run this generator: check should_run + hash, build context, call LLM, parse, return items."""
        if not force and not self.should_run(ctx):
            console.print(f"  [dim]Wire/{self.SOURCE}: skipped (should_run=False)[/dim]")
            return []

        ctx_hash = self.context_hash(ctx)

        if not force and self.already_ran(ctx, ctx_hash):
            console.print(f"  [dim]Wire/{self.SOURCE}: unchanged ({ctx_hash[:8]})[/dim]")
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

        provider = GeminiProvider(model=model)
        tools = get_tool_declarations(self.TOOLS) if self.TOOLS else None

        result = await provider.generate_with_tools(
            usr_prompt,
            system=sys_prompt,
            tools=tools,
            tool_executor=execute_tool if tools else None,
            temperature=self.TEMPERATURE,
        )

        items = self._parse_response(result)
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
                items.append({
                    "headline": headline, "text": txt, "emoji": emoji,
                    "category": category, "severity": severity, "teams": teams,
                })
        return items
