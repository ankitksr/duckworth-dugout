"""News Desk — editorial reaction to breaking news and articles.

Trigger: new articles arriving in the article store.
Voice: news editor — "here's what this actually means."
Model: Flash @ 0.6 — quick, reactive, grounded in articles.
"""

import hashlib

import duckdb

from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import GeneratorContext, WireGenerator


class NewsDeskGenerator(WireGenerator):
    SOURCE = "newsdesk"
    TOOLS = ["search_articles", "get_squad_detail"]
    MODEL = "flash"
    TEMPERATURE = 0.6

    def _count_recent_articles(self, conn: duckdb.DuckDBPyConnection) -> int:
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM war_room_articles
                WHERE is_ipl = TRUE
                  AND published >= (now() - INTERVAL '6 hours')
                """,
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def _recent_article_ids(self, conn: duckdb.DuckDBPyConnection) -> list[str]:
        try:
            rows = conn.execute(
                """
                SELECT coalesce(content_hash, url)
                FROM war_room_articles
                WHERE is_ipl = TRUE
                  AND published >= (now() - INTERVAL '6 hours')
                ORDER BY published DESC
                LIMIT 10
                """,
            ).fetchall()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [self.SOURCE]
        ids = self._recent_article_ids(ctx.conn)
        parts.append(f"articles:{','.join(ids)}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def should_run(self, ctx: GeneratorContext) -> bool:
        return self._count_recent_articles(ctx.conn) > 0

    def build_context(self, ctx: GeneratorContext) -> str:
        try:
            rows = ctx.conn.execute(
                """
                SELECT source, title, coalesce(snippet, left(body, 300)) as excerpt,
                       teams
                FROM war_room_articles
                WHERE is_ipl = TRUE
                  AND published >= (now() - INTERVAL '8 hours')
                ORDER BY published DESC
                LIMIT 6
                """,
            ).fetchall()
        except Exception:
            rows = []

        if not rows:
            return "(No recent articles)"

        parts = []
        for source, title, excerpt, teams in rows:
            team_tags = f" [{', '.join(teams)}]" if teams else ""
            text = (excerpt or title)[:400]
            parts.append(f"[{source}]{team_tags} {title}\n{text}")

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
