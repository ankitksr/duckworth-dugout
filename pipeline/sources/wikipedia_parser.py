"""Parsers for IPL season pages on Wikipedia."""

import re
from datetime import datetime

from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.sources.wikipedia_parser_base import clean_wikitext, parse_infobox

_SECTION_RE = re.compile(r"^==+\s*(.*?)\s*==+\s*$", re.MULTILINE)
_LINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")
_HEADING_RE = re.compile(r"^===+\s*(.*?)\s*===+\s*$", re.MULTILINE)
_SCORE_RE = re.compile(r"(\d{1,3}(?:/\d{1,2})?)")
_OVERS_RE = re.compile(r"\(([\d.]+)\s*overs?\)", re.IGNORECASE)
_PLAYER_STAT_RE = re.compile(r"(.+?)\s+(\d+)\s*\((\d+)\)")
_BOWLER_STAT_RE = re.compile(r"(.+?)\s+(\d+)/(\d+)\s*\(([\d.]+)\s*overs?\)", re.IGNORECASE)
_MATCH_NO_RE = re.compile(r"(\d+)")
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")
_START_DATE_RE = re.compile(
    r"\{\{Start date\|(\d{4})\|(\d{1,2})\|(\d{1,2})[^}]*\}\}",
    re.IGNORECASE,
)
_TEAM_NAME_TO_ID: dict[str, str] = {}
for _fid, _data in IPL_FRANCHISES.items():
    names = {_data["name"], _data["short_name"], *_data["cricsheet_names"]}
    for _name in names:
        _TEAM_NAME_TO_ID[_name.lower()] = _fid

_TEAM_NAME_TO_ID.update(
    {
        "royal challengers bangalore": "rcb",
        "royal challengers bengaluru": "rcb",
        "delhi daredevils": "dc",
        "kings xi punjab": "pbks",
        "punjab kings": "pbks",
    }
)

_INDIA_CODES = {"india", "ind"}


def _section_text(wikitext: str, names: tuple[str, ...]) -> str | None:
    matches = list(_SECTION_RE.finditer(wikitext))
    for i, match in enumerate(matches):
        title = clean_wikitext(match.group(1)).strip().lower()
        if title not in names:
            continue
        level = len(match.group(0)) - len(match.group(0).lstrip("="))
        start = match.end()
        end = len(wikitext)
        for later in matches[i + 1:]:
            later_level = len(later.group(0)) - len(later.group(0).lstrip("="))
            if later_level <= level:
                end = later.start()
                break
        return wikitext[start:end]
    return None


# Transient Wikipedia result strings that indicate a live match, not a final result
_TRANSIENT_RESULTS = re.compile(
    r"innings break|in progress|match delayed|rain delay|strategic time-?out",
    re.IGNORECASE,
)


def _is_transient_result(result_text: str | None) -> bool:
    """True if result text describes an in-progress state, not a final outcome."""
    return bool(result_text and _TRANSIENT_RESULTS.search(result_text))


def _strip_cell(cell: str, *, strip_parens: bool = True) -> str:
    cell = re.sub(r"<ref[^>]*>.*?</ref>", "", cell, flags=re.IGNORECASE | re.DOTALL)
    cell = re.sub(r"<br\s*/?>", " ", cell, flags=re.IGNORECASE)
    cell = re.sub(
        r"\{\{INR\s*convert?\|([^|}]+)\|c[^}]*\}\}",
        r"\1 crore", cell, flags=re.IGNORECASE,
    )
    cell = re.sub(
        r"\{\{INR\s*convert?\|([^|}]+)\|l[^}]*\}\}",
        r"\1 lakh", cell, flags=re.IGNORECASE,
    )
    cell = re.sub(r"\{\{cr\|([^|}]+)\}\}", r"\1", cell, flags=re.IGNORECASE)
    cell = re.sub(
        r"\{\{sortname\|([^|]+)\|([^}|]+).*?\}\}",
        r"\1 \2", cell, flags=re.IGNORECASE,
    )
    cell = re.sub(r"\{\{nowrap\|([^}]+)\}\}", r"\1", cell, flags=re.IGNORECASE)
    cell = re.sub(r"\{\{small\|([^}]+)\}\}", r"\1", cell, flags=re.IGNORECASE)
    cell = re.sub(r"\{\{abbr\|([^|}]+)\|[^}]+\}\}", r"\1", cell, flags=re.IGNORECASE)
    cell = re.sub(r"\{\{[^{}]+\}\}", "", cell)
    if strip_parens:
        cell = clean_wikitext(cell)
    else:
        cell = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", cell)
        cell = re.sub(r"\[https?://[^\s\]]+\s*([^\]]*)\]", r"\1", cell)
        cell = re.sub(r"'{2,3}", "", cell)
        cell = re.sub(r"<[^>]+>", "", cell)
    return " ".join(cell.replace("&nbsp;", " ").split())


def _normalize_table_cell(cell: str) -> str:
    if "|" in cell:
        left, right = cell.split("|", 1)
        left_clean = left.strip().lower()
        if (
            "=" in left_clean
            or left_clean.startswith((
                "scope", "style", "rowspan", "colspan",
                "class", "align", "width", "bgcolor",
            ))
        ):
            cell = right
    return _strip_cell(cell)


def _split_table_rows(table_text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    current: list[str] = []
    for raw_line in table_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("{|") or line == "|}" or line.startswith("|+"):
            continue
        if line.startswith("|-"):
            if current:
                rows.append(current)
            current = []
            continue
        if line.startswith("!"):
            cells = re.split(r"!!", line[1:])
            current.extend(_normalize_table_cell(cell) for cell in cells)
            continue
        if line.startswith("|"):
            cells = re.split(r"\|\|", line[1:])
            current.extend(_normalize_table_cell(cell) for cell in cells)
    if current:
        rows.append(current)
    return [row for row in rows if any(cell for cell in row)]


def _extract_tables(section_text: str) -> list[str]:
    tables: list[str] = []
    pos = 0
    while True:
        start = section_text.find("{|", pos)
        if start == -1:
            break
        end = section_text.find("|}", start)
        if end == -1:
            break
        tables.append(section_text[start:end + 2])
        pos = end + 2
    return tables


def _extract_tables_with_spans(section_text: str) -> list[tuple[str, int, int]]:
    tables: list[tuple[str, int, int]] = []
    pos = 0
    while True:
        start = section_text.find("{|", pos)
        if start == -1:
            break
        end = section_text.find("|}", start)
        if end == -1:
            break
        tables.append((section_text[start:end + 2], start, end + 2))
        pos = end + 2
    return tables


def _template_blocks(text: str, template_name: str) -> list[str]:
    pattern = "{{" + template_name
    blocks: list[str] = []
    pos = 0
    while True:
        start = text.find(pattern, pos)
        if start == -1:
            break
        depth = 0
        i = start
        while i < len(text) - 1:
            pair = text[i:i + 2]
            if pair == "{{":
                depth += 1
                i += 2
                continue
            if pair == "}}":
                depth -= 1
                i += 2
                if depth == 0:
                    blocks.append(text[start:i])
                    pos = i
                    break
                continue
            i += 1
        else:
            break
    return blocks


def _parse_template_fields(template: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in _split_top_level_params(template):
        stripped = part.strip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def _split_top_level_params(template: str) -> list[str]:
    if template.startswith("{{") and template.endswith("}}"):
        body = template[2:-2]
    else:
        body = template

    parts: list[str] = []
    current: list[str] = []
    brace_depth = 0
    link_depth = 0
    i = 0
    while i < len(body):
        pair = body[i:i + 2]
        if pair == "{{":
            brace_depth += 1
            current.append(pair)
            i += 2
            continue
        if pair == "}}" and brace_depth > 0:
            brace_depth -= 1
            current.append(pair)
            i += 2
            continue
        if pair == "[[":
            link_depth += 1
            current.append(pair)
            i += 2
            continue
        if pair == "]]" and link_depth > 0:
            link_depth -= 1
            current.append(pair)
            i += 2
            continue
        if body[i] == "|" and brace_depth == 0 and link_depth == 0:
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(body[i])
        i += 1
    parts.append("".join(current))
    return parts


def _find_team_context(text: str, pos: int) -> str | None:
    lookback = text[max(0, pos - 500):pos]
    headings = list(_HEADING_RE.finditer(lookback))
    if headings:
        team = _resolve_team_id(headings[-1].group(1))
        if team:
            return team
    best_team = None
    best_index = -1
    for known, fid in _TEAM_NAME_TO_ID.items():
        idx = lookback.lower().rfind(known)
        if idx > best_index:
            best_team = fid
            best_index = idx
    return best_team


def _team_context_from_table(table: str) -> str | None:
    caption_match = re.search(r"\|\+(.*)", table)
    if caption_match:
        return _resolve_team_id(_normalize_table_cell(caption_match.group(1)))
    return None


def _find_col_index(header: list[str], names: tuple[str, ...]) -> int | None:
    for idx, col in enumerate(header):
        if any(name in col for name in names):
            return idx
    return None


def _parse_money_to_inr(
    raw: str,
    *,
    header_hint: str = "",
    default_unit: str | None = None,
) -> int | None:
    cleaned = _strip_cell(raw, strip_parens=False).lower().replace(",", "")
    if not cleaned:
        return None
    match = _NUM_RE.search(cleaned)
    if not match:
        return None
    value = float(match.group(1))
    hint = header_hint.lower()
    if "crore" in cleaned or "crore" in hint or "cr" in cleaned:
        return int(round(value * 10_000_000))
    if "lakh" in cleaned or "lakh" in hint:
        return int(round(value * 100_000))
    if default_unit == "crore":
        return int(round(value * 10_000_000))
    if default_unit == "lakh":
        return int(round(value * 100_000))
    if "₹" in cleaned and value >= 1_000_000:
        return int(round(value))
    return None


def _resolve_team_id(raw: str) -> str | None:
    cleaned = _strip_cell(raw).replace("(H)", "").strip()
    key = cleaned.lower()
    if key in _TEAM_NAME_TO_ID:
        return _TEAM_NAME_TO_ID[key]
    for known, fid in _TEAM_NAME_TO_ID.items():
        if known in key or key in known:
            return fid
    return None


def _extract_link_text(raw: str) -> str | None:
    links = _LINK_RE.findall(raw)
    if links:
        return links[0].strip()
    cleaned = _strip_cell(raw)
    return cleaned or None


def _parse_top_batter(raw: str) -> dict | None:
    cleaned = _strip_cell(raw, strip_parens=False)
    if not cleaned:
        return None
    not_out = "*" in cleaned
    cleaned = cleaned.replace("*", "")
    match = _PLAYER_STAT_RE.match(cleaned)
    if not match:
        return {"name": cleaned}
    return {
        "name": match.group(1).strip(),
        "runs": int(match.group(2)),
        "balls": int(match.group(3)),
        "not_out": not_out,
    }


def _parse_top_bowler(raw: str) -> dict | None:
    cleaned = _strip_cell(raw, strip_parens=False)
    if not cleaned:
        return None
    match = _BOWLER_STAT_RE.match(cleaned)
    if not match:
        return {"name": cleaned}
    return {
        "name": match.group(1).strip(),
        "wickets": int(match.group(2)),
        "runs": int(match.group(3)),
        "overs": match.group(4),
    }


def _parse_score(raw: str) -> tuple[str | None, str | None]:
    cleaned = _strip_cell(raw, strip_parens=False)
    if not cleaned:
        return None, None
    score_match = _SCORE_RE.search(cleaned)
    overs_match = _OVERS_RE.search(cleaned)
    return (
        score_match.group(1) if score_match else None,
        overs_match.group(1) if overs_match else None,
    )


def _parse_match_number(fields: dict[str, str], default: int) -> int:
    for key in ("match", "match_number", "title"):
        raw = fields.get(key, "")
        match = _MATCH_NO_RE.search(raw)
        if match:
            return int(match.group(1))
    return default


def _parse_date(fields: dict[str, str]) -> str | None:
    for key in ("date", "date1", "start_date"):
        raw = fields.get(key, "")
        start_date = _START_DATE_RE.search(raw)
        if start_date:
            year, month, day = start_date.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        match = _DATE_RE.search(raw)
        if match:
            return match.group(1)
        cleaned = _strip_cell(raw)
        if cleaned:
            for fmt in ("%d %B %Y", "%d %b %Y"):
                try:
                    return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None


def _extract_invoke_block(text: str, needle: str) -> str | None:
    start = text.find(needle)
    if start == -1:
        return None
    depth = 0
    i = start
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return text[start:i]
            continue
        i += 1
    return None


def _parse_sports_table(section: str) -> list[list[str]]:
    block = _extract_invoke_block(section, "{{#invoke:Sports table")
    if not block:
        return []

    fields: dict[str, str] = {}
    for part in _split_top_level_params(block):
        stripped = part.strip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        fields[key.strip().lower()] = value.strip()

    order_raw = fields.get("team_order", "")
    team_codes = [token.strip() for token in order_raw.split(",") if token.strip()]
    if not team_codes:
        return []

    rows = [["Pos", "Team", "Mat", "Won", "Lost", "NR", "Pts", "NRR"]]
    for pos, code in enumerate(team_codes, 1):
        team_key = code.lower()
        name = _strip_cell(fields.get(f"name_{team_key}", ""))
        if not name:
            continue
        wins = int(fields.get(f"win_{team_key}", "") or 0)
        losses = int(fields.get(f"loss_{team_key}", "") or 0)
        no_results = int(fields.get(f"nr_{team_key}", "") or 0)
        played = wins + losses + no_results
        points = int(fields.get(f"pts_{team_key}", "") or (wins * 2 + no_results))
        nrr = fields.get(f"nrr_{team_key}", "") or "-"
        rows.append(
            [
                str(pos),
                name,
                str(played),
                str(wins),
                str(losses),
                str(no_results),
                str(points),
                nrr,
            ]
        )
    return rows if len(rows) > 1 else []


def parse_ipl_points_table(wikitext: str) -> list[list[str]]:
    section = _section_text(wikitext, ("points table", "league stage"))
    if not section:
        return []
    invoke_rows = _parse_sports_table(section)
    if invoke_rows:
        return invoke_rows
    for table in _extract_tables(section):
        rows = _split_table_rows(table)
        if not rows:
            continue
        header = " ".join(cell.lower() for cell in rows[0])
        if "team" in header and ("pts" in header or "point" in header):
            return rows
    return []


def parse_ipl_statistics(wikitext: str) -> dict[str, list[dict]]:
    section = _section_text(wikitext, ("statistics",))
    result = {"most_runs": [], "most_wickets": [], "mvp": []}
    if not section:
        return result

    for table in _extract_tables(section):
        rows = _split_table_rows(table)
        if len(rows) < 2:
            continue
        header = [cell.lower() for cell in rows[0]]
        header_str = " ".join(header)
        if not any(token in header_str for token in ("player", "batter", "bowler")):
            continue

        # Extract table caption (|+ line) for classification — Wikipedia uses
        # captions like "Most valuable player" while column headers may just say "Points"
        caption_match = re.search(r"^\|\+\s*(.+?)(?:<ref|$)", table, re.MULTILINE)
        caption = caption_match.group(1).strip().lower() if caption_match else ""
        classify_str = f"{caption} {header_str}"

        if "wicket" in classify_str or "wkt" in classify_str:
            key = "most_wickets"
            value_names = ("wickets", "wkts", "wkt")
        elif any(k in classify_str for k in ("mvp", "most valuable", "valuable player")):
            key = "mvp"
            value_names = ("points", "rating", "mvp")
        else:
            key = "most_runs"
            value_names = ("runs", "run")

        def _col_index(names: tuple[str, ...]) -> int | None:
            for idx, col in enumerate(header):
                if any(name in col for name in names):
                    return idx
            return None

        player_idx = _col_index(("player", "batter", "bowler"))
        team_idx = _col_index(("team",))
        value_idx = _col_index(value_names)
        if player_idx is None or value_idx is None:
            continue

        entries: list[dict] = []
        for row in rows[1:]:
            if player_idx >= len(row) or value_idx >= len(row):
                continue
            value_raw = row[value_idx].replace(",", "").strip()
            if not value_raw:
                continue
            try:
                value = float(value_raw) if "." in value_raw else int(value_raw)
            except ValueError:
                continue
            entries.append(
                {
                    "player": row[player_idx].strip(),
                    "team": (
                        _resolve_team_id(row[team_idx])
                        if team_idx is not None and team_idx < len(row)
                        else None
                    ),
                    "value": value,
                }
            )
        if entries:
            result[key] = entries
    return result


def parse_ipl_fixtures(wikitext: str) -> list[dict]:
    section = _section_text(wikitext, ("fixtures", "league stage"))
    source = section or wikitext
    fixtures: list[dict] = []
    for index, block in enumerate(_template_blocks(source, "Single-innings cricket match"), 1):
        fields = _parse_template_fields(block)
        team1 = _resolve_team_id(fields.get("team1", ""))
        team2 = _resolve_team_id(fields.get("team2", ""))
        if not team1 or not team2:
            continue

        home_team = None
        if "(H)" in fields.get("team1", ""):
            home_team = team1
        elif "(H)" in fields.get("team2", ""):
            home_team = team2

        score1, overs1 = _parse_score(fields.get("score1", ""))
        score2, overs2 = _parse_score(fields.get("score2", ""))
        result_text = _strip_cell(fields.get("result", ""))
        # Wikipedia editors often pre-fill `result` with a [URL Scorecard]
        # placeholder for upcoming matches; after link-stripping only
        # "Scorecard" / "Report" remains. Treat as no result so we don't
        # flag unplayed matches as completed.
        if result_text and re.fullmatch(r"(?i)\s*(scorecard|report)\s*", result_text):
            result_text = ""
        elif result_text:
            # Strip trailing "Scorecard"/"Report" label left behind when
            # an external link sits alongside real result text.
            result_text = re.sub(
                r"\s*\b(scorecard|report)\s*$", "",
                result_text, flags=re.IGNORECASE,
            ).strip()
        fixtures.append(
            {
                "match_number": _parse_match_number(fields, index),
                "date": _parse_date(fields),
                "team1": team1,
                "team2": team2,
                "home_team": home_team,
                "score1": score1,
                "score2": score2,
                "overs1": overs1,
                "overs2": overs2,
                "top_batter1": _parse_top_batter(fields.get("runs1", "")),
                "top_bowler1": _parse_top_bowler(fields.get("wickets1", "")),
                "top_batter2": _parse_top_batter(fields.get("runs2", "")),
                "top_bowler2": _parse_top_bowler(fields.get("wickets2", "")),
                "result": result_text or None,
                "motm": _extract_link_text(fields.get("motm", "")),
                "match_url": re.search(r"\[(https?://[^\s\]]+)", fields.get("report", "")),
                "toss": _strip_cell(fields.get("toss", "")) or None,
                "notes": _strip_cell(fields.get("notes", "")) or None,
                "status": (
                    "completed"
                    if (score1 or score2 or result_text)
                    and not _is_transient_result(result_text)
                    else "scheduled"
                ),
            }
        )
        if fixtures[-1]["match_url"] is not None:
            fixtures[-1]["match_url"] = fixtures[-1]["match_url"].group(1)
    return fixtures


def parse_ipl_match_summary(wikitext: str) -> list[dict]:
    summaries: list[dict] = []
    blocks = _template_blocks(wikitext, "Indian Premier League results summary")
    if not blocks:
        return summaries

    lines = [line.strip() for line in blocks[0].splitlines()]
    match_number = 1
    for line in lines:
        if not line.startswith("|"):
            continue
        stripped = line[1:].strip()
        if not stripped or "=" in stripped:
            continue
        cells = [_normalize_table_cell(cell) for cell in stripped.split("|")]
        if len(cells) < 4:
            continue
        home = _resolve_team_id(cells[0])
        away = _resolve_team_id(cells[1])
        if not home or not away:
            continue
        summaries.append(
            {
                "match_number": match_number,
                "home": home,
                "away": away,
                "result": cells[2] or "",
                "margin": cells[3] or "",
                "dls": len(cells) > 4 and bool(cells[4]),
            }
        )
        match_number += 1
    return summaries


def parse_ipl_team_leadership(wikitext: str) -> list[dict]:
    section = _section_text(wikitext, ("teams",))
    if not section:
        return []
    for table in _extract_tables(section):
        if "Head coach" not in table or "Captain" not in table:
            continue
        entries: list[dict] = []
        for raw_line in table.splitlines():
            line = raw_line.strip()
            if not line.startswith("|") or line.startswith(("|-", "|}", "|+")):
                continue
            if "||" not in line:
                continue
            cells = [_normalize_table_cell(cell) for cell in re.split(r"\|\|", line[1:])]
            if len(cells) < 4:
                continue
            if len(cells) == 4:
                team_raw, _performance, coach, captain = cells
            else:
                _group, team_raw, _performance, coach, captain = cells[:5]
            fid = _resolve_team_id(team_raw)
            if not fid:
                continue
            entries.append(
                {
                    "franchise_id": fid,
                    "coach": coach.strip() or None,
                    "captain": captain.strip() or None,
                }
            )
        if entries:
            return entries
    return []


def parse_ipl_season_meta(wikitext: str) -> dict:
    info = parse_infobox(wikitext)
    champion_name = _strip_cell(info.get("champions", "")) or None
    if champion_name and champion_name.startswith("|"):
        champion_name = None
    player_of_tournament = (
        _extract_link_text(info.get("most valuable player", ""))
        or _extract_link_text(info.get("player of the tournament", ""))
    )
    return {
        "champion": _resolve_team_id(champion_name) if champion_name else None,
        "champion_name": champion_name,
        "from_date": _strip_cell(info.get("fromdate", "")) or None,
        "to_date": _strip_cell(info.get("todate", "")) or None,
        "player_of_tournament": player_of_tournament,
    }


def parse_ipl_squads(wikitext: str, season: int) -> list[dict]:
    section = _section_text(wikitext, ("player retention",))
    if not section:
        return []

    squads: list[dict] = []
    for table, start, _end in _extract_tables_with_spans(section):
        rows = _split_table_rows(table)
        if len(rows) < 2:
            continue
        header = [cell.lower() for cell in rows[0]]
        if "player" not in " ".join(header):
            continue
        if "auctioned price" in " ".join(header) or "2026 ipl team" in " ".join(header):
            continue
        team = _team_context_from_table(table) or _find_team_context(section, start)
        if not team:
            continue

        player_idx = _find_col_index(header, ("player", "name"))
        salary_idx = _find_col_index(header, ("salary", "price"))
        nationality_idx = _find_col_index(header, ("nationality", "country"))
        if player_idx is None:
            continue

        for row in rows[1:]:
            if player_idx >= len(row):
                continue
            player_name = row[player_idx].strip()
            if not player_name:
                continue
            nationality = (
                row[nationality_idx].strip().lower()
                if nationality_idx is not None
                and nationality_idx < len(row)
                else ""
            )
            price_inr = None
            if salary_idx is not None and salary_idx < len(row):
                price_inr = _parse_money_to_inr(
                    row[salary_idx],
                    header_hint=rows[0][salary_idx],
                    default_unit="crore",
                )
            squads.append(
                {
                    "franchise_id": team,
                    "season": season,
                    "player_name": player_name,
                    "role": None,
                    "is_captain": False,
                    "is_overseas": bool(nationality and nationality not in _INDIA_CODES),
                    "acquisition_type": "retained",
                    "price_inr": price_inr,
                    "is_retained": True,
                    "is_rtm": False,
                }
            )
    return squads


def parse_ipl_auction_data(wikitext: str) -> list[dict]:
    records: list[dict] = []

    auction = _section_text(wikitext, ("auction",)) or ""
    for table in _extract_tables(auction):
        rows = _split_table_rows(table)
        if len(rows) < 2:
            continue
        header = [cell.lower() for cell in rows[0]]
        header_str = " ".join(header)
        if "auctioned price" not in header_str or "2026 ipl team" not in header_str:
            continue
        player_idx = _find_col_index(header, ("name", "player"))
        team_idx = _find_col_index(header, ("2026 ipl team", "team"))
        price_idx = _find_col_index(header, ("auctioned price", "price"))
        if player_idx is None or team_idx is None or price_idx is None:
            continue
        for row in rows[1:]:
            if max(player_idx, team_idx, price_idx) >= len(row):
                continue
            team = _resolve_team_id(row[team_idx])
            player_name = row[player_idx].strip()
            if not team or not player_name:
                continue
            price_inr = _parse_money_to_inr(
                row[price_idx],
                header_hint=rows[0][price_idx],
                default_unit="lakh",
            )
            records.append(
                {
                    "franchise_id": team,
                    "player_name": player_name,
                    "price_inr": price_inr,
                    "is_retained": False,
                    "is_rtm": False,
                    "acquisition_type": "auctioned",
                }
            )
    return records
