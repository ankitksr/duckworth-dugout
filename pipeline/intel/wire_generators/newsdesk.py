"""News Desk — editorial reaction to breaking news and articles.

Trigger: new articles arriving in the article store.
Voice: news editor — "here's what this actually means."
Model: Pro @ 0.7 — connects breaking stories to standings / tactical
implications rather than restating the article in wire voice.

Reads from war_room_article_extractions (populated by article_extraction.py)
so the LLM gets pre-distilled summaries + key quotes instead of raw bodies —
sharper context, fewer tokens, no re-parsing.
"""

import hashlib
import json

import duckdb

from pipeline.intel.article_extraction import EXTRACTION_VERSION
from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
)


class NewsDeskGenerator(WireGenerator):
    SOURCE = "newsdesk"
    TOOLS = ["search_articles", "get_squad_detail"]
    MODEL = "pro"
    TEMPERATURE = 0.7

    def _count_recent_extractions(self, conn: duckdb.DuckDBPyConnection) -> int:
        try:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM war_room_articles a
                JOIN war_room_article_extractions e
                  ON e.article_guid = a.guid AND e.extraction_version = ?
                WHERE a.is_ipl = TRUE
                  AND e.is_relevant = TRUE
                  AND a.published >= (now() - INTERVAL '6 hours')
                """,
                [EXTRACTION_VERSION],
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def _recent_article_ids(self, conn: duckdb.DuckDBPyConnection) -> list[str]:
        try:
            rows = conn.execute(
                """
                SELECT coalesce(a.content_hash, a.guid)
                FROM war_room_articles a
                JOIN war_room_article_extractions e
                  ON e.article_guid = a.guid AND e.extraction_version = ?
                WHERE a.is_ipl = TRUE
                  AND e.is_relevant = TRUE
                  AND a.published >= (now() - INTERVAL '6 hours')
                ORDER BY a.published DESC
                LIMIT 10
                """,
                [EXTRACTION_VERSION],
            ).fetchall()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [HASH_VERSION, self.SOURCE]
        ids = self._recent_article_ids(ctx.conn)
        parts.append(f"articles:{','.join(ids)}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def should_run(self, ctx: GeneratorContext) -> bool:
        return self._count_recent_extractions(ctx.conn) > 0

    def build_context(self, ctx: GeneratorContext) -> str:
        # Sort by story_type priority first so availability / team news /
        # controversy don't get crowded out by match_report articles on
        # match days. `published DESC` is the secondary key.
        try:
            rows = ctx.conn.execute(
                """
                SELECT a.source, a.title, e.story_type, e.summary,
                       e.headline_takeaway, e.key_quotes, a.teams
                FROM war_room_articles a
                JOIN war_room_article_extractions e
                  ON e.article_guid = a.guid AND e.extraction_version = ?
                WHERE a.is_ipl = TRUE
                  AND e.is_relevant = TRUE
                  AND a.published >= (now() - INTERVAL '8 hours')
                ORDER BY
                    CASE e.story_type
                        WHEN 'injury_update'    THEN 0
                        WHEN 'team_news'        THEN 0
                        WHEN 'controversy'      THEN 0
                        WHEN 'transfer_auction' THEN 1
                        WHEN 'match_preview'    THEN 2
                        WHEN 'interview'        THEN 2
                        WHEN 'match_report'     THEN 3
                        ELSE 4
                    END,
                    a.published DESC
                LIMIT 12
                """,
                [EXTRACTION_VERSION],
            ).fetchall()
        except Exception:
            rows = []

        if not rows:
            return "(No recent articles)"

        parts = []
        for source, title, story_type, summary, takeaway, quotes_json, teams in rows:
            team_tags = f" [{', '.join(teams)}]" if teams else ""
            type_tag = f" ({story_type})" if story_type else ""
            block_lines = [f"[{source}]{team_tags}{type_tag} {title}"]
            if takeaway:
                block_lines.append(f"  → {takeaway}")
            if summary:
                block_lines.append(f"  {summary}")

            # Inline up to 2 substantive quotes
            try:
                quotes = json.loads(quotes_json) if quotes_json else []
            except (TypeError, ValueError):
                quotes = []
            for q in quotes[:2]:
                speaker = q.get("speaker", "").strip()
                text = q.get("text", "").strip()
                if speaker and text:
                    block_lines.append(f'  "{text}" — {speaker}')

            parts.append("\n".join(block_lines))

        # Minimal standings for framing
        standings_line = ""
        if ctx.standings:
            standings_line = "\n\nCURRENT TABLE (for framing):\n" + " | ".join(
                f"{s['position']}.{s['short_name']} {s['wins']}-{s['losses']}"
                for s in ctx.standings
            )

        return "RECENT ARTICLES:\n" + "\n---\n".join(parts) + standings_line

    def system_prompt(self) -> str:
        return load_prompt("wire_newsdesk_system.md")

    def user_prompt(self, ctx: GeneratorContext, focused_context: str, previous: str) -> str:
        template = load_prompt("wire_newsdesk_user.md")
        return template.format(
            base_context=ctx.base_context,
            focused_context=focused_context,
            previous_entries=previous,
            franchise_ids="rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt",
        )
