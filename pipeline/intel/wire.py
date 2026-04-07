"""AI Wire — incremental editorial insights for the War Room.

Unlike the ticker (factual headlines via Flash), the wire produces
connected observations and analysis via Pro. It builds incrementally
throughout the day as new data arrives, never repeating itself.

Context hash changes trigger generation: standings + match count +
cap leaders + article freshness. Previous entries are fed back to the
LLM to prevent repetition and encourage building on earlier insights.

Daily reset: previous day's entries are marked expired but preserved
for historical queries.

Usage:
    entries = await generate_wire(conn, season, today_matches)
    wire_data = export_wire_json(conn, season)
"""

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any

import duckdb
from rich.console import Console

from pipeline.config import DATA_DIR, GEMINI_MODEL_PRO
from pipeline.intel.prompts import load_prompt
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import ScheduleMatch

console = Console()


def _short(fid: str) -> str:
    return IPL_FRANCHISES.get(fid, {}).get("short_name", fid.upper())


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Context hashing ──────────────────────────────────────────────────

def _time_window() -> str:
    """Current time window for editorial angle guidance."""
    hour = datetime.now(timezone.utc).hour + 5  # IST roughly
    if hour >= 24:
        hour -= 24
    if hour < 12:
        return "morning"
    if hour < 15:
        return "afternoon"
    if hour < 20:
        return "evening"
    return "night"


def _build_context_hash(
    standings: list[dict],
    caps: dict | None,
    schedule: list[dict] | None,
    article_count: int,
) -> str:
    """Hash of wire input context — changes trigger regeneration.

    Sensitive to: standings changes, match status transitions, cap leader
    changes, article arrivals, and time-of-day windows.
    """
    parts: list[str] = []

    if standings:
        parts.append(json.dumps(
            [(s["short_name"], s["played"], s["wins"]) for s in standings],
            sort_keys=True,
        ))

    if schedule:
        completed = sum(1 for m in schedule if m.get("status") == "completed")
        live = sum(1 for m in schedule if m.get("status") == "live")
        parts.append(f"completed:{completed}")
        parts.append(f"live:{live}")

    if caps:
        oc = caps.get("orange_cap", [])
        pc = caps.get("purple_cap", [])
        if oc:
            parts.append(f"oc1:{oc[0].get('player', '')}")
        if pc:
            parts.append(f"pc1:{pc[0].get('player', '')}")

    # Raw article count — every new article can trigger fresh dispatches
    parts.append(f"articles:{article_count}")

    # Time window — ensures wire fires at least once per window per day
    parts.append(f"window:{_time_window()}")

    content = "|".join(parts)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── Database helpers ─────────────────────────────────────────────────

def _expire_previous_day(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    today: str,
) -> int:
    """Mark entries from previous days as expired."""
    result = conn.execute(
        """
        UPDATE war_room_wire
        SET expired = TRUE
        WHERE season = ? AND expired = FALSE
          AND (match_day IS NULL OR match_day < ?)
        RETURNING id
        """,
        [season, today],
    ).fetchall()
    return len(result)


def _get_previous_entries(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    limit: int = 20,
) -> list[dict]:
    """Get recent non-expired wire entries for repetition avoidance."""
    rows = conn.execute(
        """
        SELECT headline, text, category FROM war_room_wire
        WHERE season = ? AND expired = FALSE
        ORDER BY generated_at DESC
        LIMIT ?
        """,
        [season, limit],
    ).fetchall()
    return [{"headline": r[0], "text": r[1], "category": r[2]} for r in rows]


def _context_already_processed(
    conn: duckdb.DuckDBPyConnection,
    context_hash: str,
    season: str,
) -> bool:
    """Check if we already generated wire entries for this context."""
    row = conn.execute(
        """
        SELECT 1 FROM war_room_wire
        WHERE context_hash = ? AND season = ?
        LIMIT 1
        """,
        [context_hash, season],
    ).fetchone()
    return row is not None


def _count_recent_articles(
    conn: duckdb.DuckDBPyConnection,
    hours: int = 6,
) -> int:
    """Count IPL articles published in the last N hours."""
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM war_room_articles
        WHERE is_ipl = TRUE
          AND published >= (now() - INTERVAL '{int(hours)} hours')
        """,
    ).fetchone()
    return row[0] if row else 0


# ── Context builders ─────────────────────────────────────────────────

def _build_article_context(
    conn: duckdb.DuckDBPyConnection,
    max_articles: int = 8,
    max_chars: int = 600,
) -> str:
    """Recent IPL article summaries for wire context."""
    rows = conn.execute(
        """
        SELECT source, title, coalesce(snippet, left(body, 300)) as excerpt
        FROM war_room_articles
        WHERE is_ipl = TRUE
          AND published >= (now() - INTERVAL '8 hours')
        ORDER BY published DESC
        LIMIT ?
        """,
        [max_articles],
    ).fetchall()
    if not rows:
        return "(No recent articles)"
    parts = []
    for source, title, excerpt in rows:
        text = (excerpt or title)[:max_chars]
        parts.append(f"[{source}] {title}\n{text}")
    return "RECENT NEWS:\n" + "\n---\n".join(parts)


def _build_season_context(
    standings: list[dict],
    caps: dict | None,
    schedule: list[dict] | None,
) -> str:
    """Current-season context from synced JSONs."""
    parts: list[str] = []

    if standings:
        lines = [
            f"  {s['position']}. {s['short_name']}"
            f" P={s['played']} W={s['wins']} L={s['losses']}"
            f" NRR={s['nrr']}"
            for s in standings
        ]
        parts.append("STANDINGS:\n" + "\n".join(lines))

    if caps:
        for key, label in [
            ("orange_cap", "ORANGE CAP"),
            ("purple_cap", "PURPLE CAP"),
            ("best_sr", "BEST STRIKE RATE"),
            ("best_econ", "BEST ECONOMY"),
        ]:
            entries = caps.get(key, [])[:5]
            if entries:
                lines = [
                    f"  {e['rank']}. {e['player']} ({e['team_short']}) {e['stat']}"
                    for e in entries
                ]
                parts.append(f"{label}:\n" + "\n".join(lines))

    if schedule:
        completed = [m for m in schedule if m.get("status") == "completed"]
        if completed:
            result_lines: list[str] = []
            for m in completed[-7:]:
                main = (
                    f"  M{m['match_number']}: {_short(m['team1'])} vs {_short(m['team2'])}"
                    f" — {m.get('result', '?')}"
                    f" ({m.get('score1', '?')} vs {m.get('score2', '?')})"
                )
                result_lines.append(main)
                # Build performer highlight line
                highlights: list[str] = []
                tb1 = m.get("top_batter1")
                tb2 = m.get("top_batter2")
                tbw1 = m.get("top_bowler1")
                tbw2 = m.get("top_bowler2")
                hs = m.get("hero_stat")
                hn = m.get("hero_name")
                batters: list[str] = []
                if tb1:
                    nb = "()" if not tb1.get("not_out") else "*"
                    batters.append(f"{tb1['name']} {tb1['runs']}({tb1['balls']}){nb}")
                if tb2:
                    nb = "()" if not tb2.get("not_out") else "*"
                    batters.append(f"{tb2['name']} {tb2['runs']}({tb2['balls']}){nb}")
                if batters:
                    highlights.append("Top bat: " + ", ".join(batters))
                bowlers: list[str] = []
                if tbw1:
                    bowlers.append(f"{tbw1['name']} {tbw1['wickets']}/{tbw1['runs']}")
                if tbw2:
                    bowlers.append(f"{tbw2['name']} {tbw2['wickets']}/{tbw2['runs']}")
                if bowlers:
                    highlights.append("POTM: " + " | ".join(bowlers))
                elif hn and hs:
                    highlights.append(f"POTM: {hn} {hs}")
                if highlights:
                    result_lines.append("    " + " | ".join(highlights))
            parts.append("RECENT RESULTS:\n" + "\n".join(result_lines))

        today_str = date.today().isoformat()
        upcoming = [
            m for m in schedule
            if m.get("date") == today_str and m.get("status") in ("scheduled", "live")
        ]
        if upcoming:
            lines = [
                f"  M{m['match_number']}: {_short(m['team1'])} vs {_short(m['team2'])}"
                f" at {m.get('venue', '?')}, {m.get('time', '?')}"
                for m in upcoming
            ]
            parts.append("TODAY'S MATCHES:\n" + "\n".join(lines))

        # Toss analysis summary
        toss_matches = [m for m in completed if m.get("toss")]
        if toss_matches:
            bat_first = 0
            field_first = 0
            toss_win_match_win = 0
            for m in toss_matches:
                toss_str = (m.get("toss") or "").lower()
                if "bat" in toss_str:
                    bat_first += 1
                elif "field" in toss_str or "bowl" in toss_str:
                    field_first += 1
                # Toss winner → match winner correlation
                toss_winner_fid: str | None = None
                for fid in (m.get("team1"), m.get("team2")):
                    short = _short(fid) if fid else ""
                    if short and short.lower() in toss_str:
                        toss_winner_fid = fid
                        break
                if toss_winner_fid and m.get("winner") == toss_winner_fid:
                    toss_win_match_win += 1
            total_toss = len(toss_matches)
            toss_lines = [
                f"  Elected to bat: {bat_first}/{total_toss}"
                f" | Elected to field: {field_first}/{total_toss}",
                f"  Toss-win → match-win: {toss_win_match_win}/{total_toss}"
                f" ({round(toss_win_match_win / total_toss * 100)}%)",
            ]
            parts.append("TOSS TRENDS:\n" + "\n".join(toss_lines))

    return "\n\n".join(parts)


def _build_mcp_context(today_matches: list[ScheduleMatch]) -> str:
    """Career stats from MCP for today's match teams."""
    parts: list[str] = []
    try:
        from pipeline.sources.cricsheet import _EVENT, _connect

        conn = _connect()

        # Top run scorers for today's teams
        team_fids = set()
        for m in today_matches:
            team_fids.add(m.team1)
            team_fids.add(m.team2)

        if team_fids:
            from pipeline.sources.cricsheet import _CRICSHEET_TO_FID
            fid_to_name = {v: k for k, v in _CRICSHEET_TO_FID.items()}
            for fid in team_fids:
                cname = fid_to_name.get(fid)
                if not cname:
                    continue
                rows = conn.execute("""
                    SELECT p.name, SUM(bs.runs) as total,
                           ROUND(AVG(CASE WHEN bs.runs > 0 THEN bs.strike_rate END), 1) as avg_sr
                    FROM batting_scorecard bs
                    JOIN players p ON bs.player_id = p.id
                    JOIN matches m ON bs.match_id = m.id
                    WHERE m.event_name = ?
                      AND (m.team1 = ? OR m.team2 = ?)
                      AND bs.runs > 0
                    GROUP BY p.name
                    ORDER BY total DESC
                    LIMIT 5
                """, [_EVENT, cname, cname]).fetchall()
                if rows:
                    lines = [f"  {name}: {total} runs (SR {sr})" for name, total, sr in rows]
                    parts.append(f"{_short(fid)} TOP BATTERS (all-time IPL):\n" + "\n".join(lines))

        # Venue stats for today's match venues
        venue_cities = set()
        for m in today_matches:
            if m.city:
                venue_cities.add(m.city)

        for city in venue_cities:
            venue_rows = conn.execute(
                """
                SELECT
                    ROUND(AVG(i1.total_runs), 1) as avg_first_innings,
                    COUNT(*) as total_matches,
                    SUM(
                        CASE WHEN m.outcome_winner = i2.batting_team THEN 1 ELSE 0 END
                    ) as chase_wins
                FROM matches m
                JOIN innings i1 ON i1.match_id = m.id AND i1.innings_number = 1
                JOIN innings i2 ON i2.match_id = m.id AND i2.innings_number = 2
                WHERE m.event_name = ? AND m.city = ?
                  AND i1.total_runs IS NOT NULL AND i2.total_runs IS NOT NULL
                  AND m.outcome_result IS DISTINCT FROM 'no result'
                """,
                [_EVENT, city],
            ).fetchone()
            if venue_rows and venue_rows[0] is not None:
                avg_score, total_matches, chase_wins = venue_rows
                chase_pct = (
                    round(chase_wins / total_matches * 100) if total_matches > 0 else 0
                )
                parts.append(
                    f"VENUE — {city} (IPL all-time):\n"
                    f"  Avg 1st innings: {avg_score}"
                    f" | Chase win%: {chase_pct}% ({chase_wins}/{total_matches})"
                )

        conn.close()
    except Exception as e:
        parts.append(f"(MCP query failed: {e})")

    return "\n\n".join(parts) if parts else ""


def _build_enrichment_context(
    conn: duckdb.DuckDBPyConnection,
    today_matches: list[ScheduleMatch],
    season: str,
) -> str:
    """Auction / squad context from enrichment DB for today's teams."""
    parts: list[str] = []
    team_fids: set[str] = set()
    for m in today_matches:
        team_fids.add(m.team1)
        team_fids.add(m.team2)

    if not team_fids:
        return ""

    try:
        season_int = int(season)
    except (ValueError, TypeError):
        return ""

    for fid in team_fids:
        try:
            rows = conn.execute(
                """
                SELECT player_name, price_inr, acquisition_type
                FROM ipl_season_squad
                WHERE franchise_id = ? AND season = ? AND price_inr IS NOT NULL
                ORDER BY price_inr DESC
                LIMIT 3
                """,
                [fid, season_int],
            ).fetchall()
        except Exception:
            rows = []

        if rows:
            entries = []
            for player_name, price_inr, acq_type in rows:
                crores = price_inr / 1_00_00_000
                acq = (acq_type or "").lower()
                tag = "retained" if "retain" in acq else ("RTM" if "rtm" in acq else "auctioned")
                entries.append(f"  {player_name} (₹{crores:.2f} Cr, {tag})")
            parts.append(f"{_short(fid)} TOP BUYS:\n" + "\n".join(entries))

    return "\n\n".join(parts)


# ── LLM generation ───────────────────────────────────────────────────

_VALID_SEVERITIES = {"signal", "alert", "alarm"}

_FRANCHISE_IDS = "rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt"

_SYSTEM_PROMPT = load_prompt("wire_system.md")
_USER_PROMPT = load_prompt("wire_user.md")


async def generate_wire(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    today_matches: list[ScheduleMatch],
    *,
    force: bool = False,
) -> list[dict]:
    """Generate incremental wire entries if context has changed.

    Args:
        force: bypass context hash check and generate fresh dispatches.

    Returns the newly generated entries (empty list if skipped).
    """
    today_str = date.today().isoformat()

    # Daily reset — expire yesterday's entries
    expired = _expire_previous_day(conn, season, today_str)
    if expired:
        console.print(f"  [dim]Wire: expired {expired} previous-day entries[/dim]")

    # Load context data
    standings = _load_json("standings.json") or []
    caps = _load_json("caps.json")
    schedule = _load_json("schedule.json")

    if not standings:
        console.print("  [yellow]Wire: no standings — skipping[/yellow]")
        return []

    # Check if context changed since last generation
    article_count = _count_recent_articles(conn)
    ctx_hash = _build_context_hash(standings, caps, schedule, article_count)

    if not force and _context_already_processed(conn, ctx_hash, season):
        console.print(f"  [dim]Wire: context unchanged ({ctx_hash[:8]})[/dim]")
        return []

    if force:
        console.print("  [dim]Wire: forced regeneration[/dim]")

    # Build LLM context
    previous = _get_previous_entries(conn, season)
    prev_text = "\n".join(
        f"- [{e['category']}] {e['headline']}: {e['text']}" for e in previous
    ) if previous else "(none yet — this is the first wire generation)"

    season_context = _build_season_context(standings, caps, schedule)

    # Full roster context — all teams, all players (with prices, captain, overseas)
    try:
        from pipeline.intel.roster_context import all_squads

        roster_text = all_squads(conn, season)
        if roster_text:
            season_context += f"\n\n{roster_text}"
    except Exception:
        pass

    article_context = _build_article_context(conn)
    mcp_context = _build_mcp_context(today_matches)
    enrichment_context = _build_enrichment_context(conn, today_matches, season)

    # Fold in cross-panel intelligence (scenarios, records) when available
    intel_parts: list[str] = []
    scenarios = _load_json("scenarios.json")
    if scenarios:
        brief = scenarios.get("situation_brief", "")
        elim = scenarios.get("elimination_watch", [])
        if brief:
            intel_parts.append(f"PLAYOFF PICTURE: {brief}")
        for e in elim[:4]:
            intel_parts.append(
                f"  {e['team']} ({e['risk']}): {e['insight']}"
            )
    records = _load_json("records.json")
    if records:
        for entry in records.get("imminent", [])[:3]:
            intel_parts.append(
                f"MILESTONE WATCH: {entry['player']} — "
                f"{entry['current']} → {entry['target']}"
            )
    intel_context = "\n".join(intel_parts) if intel_parts else ""

    prompt = _USER_PROMPT.format(
        season_context=season_context,
        article_context=article_context,
        mcp_context=mcp_context or "(no MCP data)",
        enrichment_context=enrichment_context or "(no auction data)",
        previous_entries=prev_text,
        franchise_ids=_FRANCHISE_IDS,
        time_window=_time_window(),
    )

    # Append cross-panel intel if available
    if intel_context:
        prompt += f"\n\nCROSS-PANEL INTELLIGENCE:\n{intel_context}"

    # LLM call — Gemini Pro with tool access
    from pipeline.intel.tools import execute_tool, get_tool_declarations
    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider(model=GEMINI_MODEL_PRO)
    result = await provider.generate_with_tools(
        prompt,
        system=_SYSTEM_PROMPT,
        tools=get_tool_declarations(),
        tool_executor=execute_tool,
        temperature=0.85,
    )

    # Parse response
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

    valid_fids = {fid.strip() for fid in _FRANCHISE_IDS.split(",")}
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
                teams = [t.strip().lower() for t in teams
                         if isinstance(t, str) and t.strip().lower() in valid_fids]
            else:
                teams = []
            items.append({
                "headline": headline, "text": txt, "emoji": emoji,
                "category": category, "severity": severity, "teams": teams,
            })

    if not items:
        console.print("  [yellow]Wire: LLM returned no valid items[/yellow]")
        return []

    # Insert into DB
    row = conn.execute(
        "SELECT coalesce(max(id), 0) FROM war_room_wire"
    ).fetchone()
    next_id = (row[0] if row else 0) + 1

    for i, item in enumerate(items):
        conn.execute(
            """
            INSERT INTO war_room_wire
                (id, headline, text, emoji, category, severity, teams,
                 context_hash, season, match_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                next_id + i,
                item["headline"],
                item["text"],
                item["emoji"],
                item["category"],
                item["severity"],
                item["teams"],
                ctx_hash,
                season,
                today_str,
            ],
        )

    console.print(f"  [green]Wire: {len(items)} new dispatches generated[/green]")
    return items


def export_wire_json(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> list[dict]:
    """Export all non-expired wire entries for the frontend."""
    rows = conn.execute(
        """
        SELECT headline, text, emoji, category, severity,
               teams, generated_at::VARCHAR, match_day
        FROM war_room_wire
        WHERE season = ? AND expired = FALSE
        ORDER BY
            CASE severity
                WHEN 'alarm' THEN 0
                WHEN 'alert' THEN 1
                ELSE 2
            END,
            generated_at DESC
        """,
        [season],
    ).fetchall()
    return [
        {
            "headline": r[0],
            "text": r[1],
            "emoji": r[2],
            "category": r[3],
            "severity": r[4],
            "teams": r[5] or [],
            "generated_at": r[6],
            "match_day": r[7],
        }
        for r in rows
    ]
