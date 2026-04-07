"""Parse Wikipedia wikitext for cricket tour and ICC tournament articles.

Extracts structured data from MediaWiki templates:
  - {{Infobox cricket tour}} — tour dates, captains, results, player of series
  - {{cricket squad}} / {{Squads}} — squad listings with (c)/(wk) annotations
  - Narrative text from Background and match sections

Input:  cache/wikipedia/tours/{article}.json (contains wikitext)
Output: Enrichment data for Series, SeriesSquadEntry models
"""

import re


def parse_infobox(wikitext: str) -> dict:
    """Extract fields from infobox templates in cricket tour/series articles.

    Handles two infobox styles:
      - Bilateral tours:  team1_captain / team2_captain
      - Tri-series/ICC:   captain1 / captain2 / captain3

    Also detects format-specific captains like:
      "[[Ricky Ponting]] (Tests)<br />[[Michael Clarke]] (T20Is)"

    Returns a dict with keys like:
      team1_captain, team2_captain (cleaned names),
      team1_captains_by_format: {"test": "...", "odi": "...", "t20i": "..."},
      team1, team2, tour_name, from_date, to_date, etc.
    """
    result: dict = {}

    # Extract all | key = value pairs from infoboxes
    # Match across multi-line infobox blocks
    field_pattern = re.compile(
        r"\|\s*([a-zA-Z0-9_]+)\s*=\s*(.*?)(?=\n\s*\||\n\s*\}\})", re.DOTALL
    )

    for match in field_pattern.finditer(wikitext):
        key = match.group(1).strip().lower()
        raw_value = match.group(2).strip()
        if not raw_value:
            continue
        result[key] = raw_value

    # Now parse captain fields into structured data
    captain_fields = {}
    for key, raw in result.items():
        if "captain" not in key:
            continue

        # Determine which team number this is for
        team_num = None
        for prefix in ("team1_", "team2_", "team3_"):
            if key.startswith(prefix):
                team_num = prefix.rstrip("_")
                break
        if team_num is None:
            # captainN format (tri-series)
            m = re.match(r"captain(\d+)", key)
            if m:
                team_num = f"team{m.group(1)}"

        if team_num is None:
            continue

        # Parse format-specific captains: "Name (Tests)<br />Name2 (T20Is)"
        by_format = _parse_captain_by_format(raw)
        if by_format:
            captain_fields[f"{team_num}_captains_by_format"] = by_format
            # Primary captain = first one listed
            first_name = next(iter(by_format.values()))
            captain_fields[f"{team_num}_captain"] = first_name
        else:
            # Single captain for all formats
            names = _extract_names(raw)
            if names:
                captain_fields[f"{team_num}_captain"] = names[0]

    result.update(captain_fields)
    return result


def _parse_captain_by_format(raw: str) -> dict[str, str] | None:
    """Parse format-specific captain strings.

    e.g., "[[Ricky Ponting]] (Tests)<br />[[Michael Clarke]] (T20Is)"
    Returns {"test": "Ricky Ponting", "t20i": "Michael Clarke"} or None.
    """
    format_map = {
        "tests": "test", "test": "test",
        "odis": "odi", "odi": "odi",
        "t20is": "t20i", "t20i": "t20i", "t20": "t20i",
    }

    # Split on <br> variants
    parts = re.split(r"<br\s*/?\s*>", raw, flags=re.IGNORECASE)
    if len(parts) < 2:
        return None

    result = {}
    for part in parts:
        # Look for format hint in parentheses or after the name
        fmt_match = re.search(r"\(([^)]+)\)", part)
        if not fmt_match:
            continue
        fmt_hint = fmt_match.group(1).strip().lower()

        # Map to canonical format
        for keyword, canonical in format_map.items():
            if keyword in fmt_hint:
                names = _extract_names(part)
                if names:
                    result[canonical] = names[0]
                break

    return result if result else None


def _extract_names(raw: str) -> list[str]:
    """Extract player names from wiki markup.

    Handles:
      [[Ricky Ponting]]         → "Ricky Ponting"
      [[Michael Clarke (cricketer)|Michael Clarke]]  → "Michael Clarke"
      [[Ricky Ponting|RT Ponting]]  → "Ricky Ponting" (prefer display name)
      Multiple names separated by <br> or /
    """
    # First try wiki links
    link_pattern = re.compile(r"\[\[([^]]+)\]\]")
    names = []
    for m in link_pattern.finditer(raw):
        link_text = m.group(1)
        if "|" in link_text:
            # [[Target|Display]] — use target (full name) unless it has qualifier
            target, display = link_text.split("|", 1)
            # If target has a qualifier like "(cricketer)", use display
            if "(" in target:
                names.append(display.strip())
            else:
                names.append(target.strip())
        else:
            names.append(link_text.strip())

    if names:
        return names

    # Fallback: clean the raw text
    cleaned = clean_wikitext(raw)
    if cleaned:
        return [cleaned.split("<")[0].strip()]
    return []


def parse_squads(wikitext: str) -> list[dict]:
    """Extract squad listings from wikitext.

    Handles three major Wikipedia squad formats:

    1. **Bullet-list columns** (most common, ~80% of articles):
       Multi-column wikitables where each column is a team's squad as
       ``* [[Player Name]] ([[Captain (cricket)|c]])`` bullet items.
       Team names appear as column headers using ``{{cr|CODE}}`` or plain text.

    2. **Row-based multi-column** (tri-series side-by-side):
       Each row has one player per team separated by ``||``, e.g.
       ``| [[Player1]] (c) || [[Player2]] (wk) || [[Player3]]``.

    3. **Separate tables per team** (e.g. Chappell-Hadlee format):
       Multiple ``{| class="wikitable"`` blocks within the squad section,
       each with a ``colspan`` header naming the team and player rows with
       ``||`` separating Name, Style, and Domestic team columns.

    Player annotations recognised:
      - ``(c)`` / ``([[Captain (cricket)|c]])`` → captain
      - ``(vc)`` / ``([[Captain (cricket)|vc]])`` → vice-captain
      - ``(wk)`` / ``([[Wicket-keeper|wk]])`` / ``([[wicket-keeper|wk]])`` → wicketkeeper
      - ``<s>[[Name]]</s>`` → was_replaced (struck-through = dropped/injured)

    Returns list of dicts with keys:
      player_name, team_name, is_captain, is_vice_captain,
      is_wicketkeeper, was_replaced
    """
    squad_sections = _find_squad_sections(wikitext)
    if not squad_sections:
        return []

    results: list[dict] = []
    for section in squad_sections:
        parsed = _parse_squad_section(section)
        results.extend(parsed)

    return results


def _find_squad_sections(wikitext: str) -> list[str]:
    """Extract the text of squad sections from wikitext.

    Collects everything under ==Squad== or ==Squads== headers, including
    sub-sections like ===Test squads=== and ===ODI squads===. Stops at the
    next == level-2 header that is not squad-related.
    """
    lines = wikitext.split("\n")
    sections: list[str] = []
    in_squad = False
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Detect squad section headers at level 2 or 3:
        # ==Squads==, ===Squads===, == Squad ==, etc.
        if re.match(r"^={2,3}\s*Squads?\s*={2,3}\s*$", stripped, re.IGNORECASE):
            if current_lines:
                sections.append("\n".join(current_lines))
            current_lines = []
            in_squad = True
            continue

        if in_squad:
            # End on next level-2 header that isn't squad-related
            # Allow === sub-sections (e.g. ===Test squads===) to continue
            if re.match(r"^==\s*[^=]", stripped) and not re.match(
                r"^={2,3}\s*Squads?\s*={2,3}", stripped, re.IGNORECASE
            ):
                sections.append("\n".join(current_lines))
                current_lines = []
                in_squad = False
                continue
            current_lines.append(line)

    if in_squad and current_lines:
        sections.append("\n".join(current_lines))

    return sections


# Map of {{cr|CODE}} and {{flagcricket|CODE}} country codes to team names
_CR_CODE_TO_TEAM: dict[str, str] = {
    "AUS": "Australia", "IND": "India", "ENG": "England",
    "PAK": "Pakistan", "SA": "South Africa", "NZ": "New Zealand",
    "WI": "West Indies", "WIN": "West Indies",
    "SL": "Sri Lanka", "SRI": "Sri Lanka",
    "BAN": "Bangladesh", "ZIM": "Zimbabwe",
    "AFG": "Afghanistan", "IRE": "Ireland",
    "SCO": "Scotland", "NED": "Netherlands",
    "UAE": "United Arab Emirates", "NAM": "Namibia",
    "KEN": "Kenya", "HK": "Hong Kong",
    "USA": "United States of America",
}


def _extract_team_from_header(header: str) -> str | None:
    """Extract a team name from a wikitable column header.

    Handles: ``{{cr|IND}}``, ``{{flagcricket|AUS}}``, plain text like
    ``New Zealand``, or wikilinked ``[[Australian cricket team|Australia]]``.
    """
    # {{cr|CODE}} or {{flagcricket|CODE}} or {{flagicon|CODE}}
    cr_match = re.search(
        r"\{\{(?:cr|flagcricket|flag cricket)\|([^}|]+)", header, re.IGNORECASE,
    )
    if cr_match:
        code = cr_match.group(1).strip().upper()
        return _CR_CODE_TO_TEAM.get(code)

    # Plain text team name (strip refs, templates, and formatting first)
    cleaned = re.sub(r"<ref[^>]*>.*?</ref>", "", header, flags=re.DOTALL)
    cleaned = re.sub(r"<ref[^/]*/>", "", cleaned)
    cleaned = re.sub(r"\{\{[^}]*\}\}", "", cleaned)
    cleaned = re.sub(r"'{2,3}", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Remove colspan/style attributes
    cleaned = re.sub(r'colspan\s*=\s*"?\d+"?\s*\|?', "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'style\s*=\s*"[^"]*"', "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" !|")

    if not cleaned:
        return None

    # Known country names (case-insensitive match)
    known_teams = {
        "australia", "india", "england", "pakistan", "south africa",
        "new zealand", "west indies", "sri lanka", "bangladesh", "zimbabwe",
        "afghanistan", "ireland", "scotland", "netherlands",
        "united arab emirates", "namibia", "kenya", "hong kong",
        "united states of america",
    }
    cleaned_lower = cleaned.lower()
    for team in known_teams:
        if team in cleaned_lower:
            return team.title()

    # Reject non-team strings (format names, generic labels)
    non_team = {
        "test", "tests", "odi", "odis", "t20i", "t20is", "t20",
        "squads", "squad", "name", "style", "domestic team",
        "opening batsmen", "middle order", "fast bowlers", "spin bowler",
        "captain", "wicketkeeper",
    }
    if cleaned_lower in non_team:
        return None
    # Also reject if the entire string is a format label
    if any(cleaned_lower.startswith(w) for w in ("test ", "odi ", "t20")):
        return None

    return None


def _parse_player_entry(text: str) -> dict | None:
    """Parse a single player entry from wikitext.

    Returns dict with player_name, is_captain, is_vice_captain,
    is_wicketkeeper, was_replaced, or None if no player found.
    """
    text = text.strip()
    if not text:
        return None

    # Detect replaced players (strikethrough)
    was_replaced = bool(re.search(r"<s>|<strike>", text, re.IGNORECASE))

    # Extract player name from first [[wikilink]] only
    link_match = re.search(r"\[\[([^\]]+)\]\]", text)
    if not link_match:
        return None

    link_text = link_match.group(1)
    if "|" in link_text:
        target, display = link_text.split("|", 1)
        # Use target unless it has qualifier like "(cricketer)"
        if "(" in target:
            player_name = display.strip()
        else:
            player_name = target.strip()
    else:
        player_name = link_text.strip()

    if not player_name:
        return None

    # Skip non-player wikilinks (teams, domestic sides, bowling styles, etc.)
    skip_patterns = (
        "cricket team", "batsman", "bowling", "wicket-keeper",
        "captain", "spin", "firebirds", "warriors", "bulls",
    )
    if any(p in player_name.lower() for p in skip_patterns):
        return None

    # Detect annotations — search the full text
    text_lower = text.lower()

    # Captain: (c) or ([[Captain (cricket)|c]])
    is_captain = bool(re.search(
        r"\(\[\[(?:captain\s*\(cricket\))\|c\]\]\)|\(\s*c\s*\)",
        text_lower,
    ))

    # Vice-captain: (vc) or ([[Captain (cricket)|vc]])
    is_vice_captain = bool(re.search(
        r"\(\[\[(?:captain\s*\(cricket\))\|vc\]\]\)|\(\s*vc\s*\)",
        text_lower,
    ))

    # Wicketkeeper: (wk) or ([[Wicket-keeper|wk]]) or ([[wicketkeeper|wk]])
    is_wicketkeeper = bool(re.search(
        r"\(\[\[(?:wicket-?keeper)\|wk\]\]\)|\(\s*wk\s*\)",
        text_lower,
    ))

    return {
        "player_name": player_name,
        "is_captain": is_captain,
        "is_vice_captain": is_vice_captain,
        "is_wicketkeeper": is_wicketkeeper,
        "was_replaced": was_replaced,
    }


def _parse_squad_section(section: str) -> list[dict]:
    """Parse a single squad section into player entries.

    Detects the format and delegates:
      - Multiple wikitables → separate-table-per-team format
      - Single wikitable with bullet lists → bullet-list columns
      - Single wikitable without bullets → row-based format
      - Section may contain multiple wikitables (e.g. Test + ODI sub-sections)
    """
    results: list[dict] = []

    # Split into individual wikitable blocks
    table_pattern = re.compile(r"\{\|[^\n]*\n(.*?)\|\}", re.DOTALL)
    table_matches = list(table_pattern.finditer(section))

    if not table_matches:
        return []

    # Check for separate-table-per-team format:
    # Multiple tables, each with a colspan header naming one team
    if len(table_matches) >= 2:
        # Peek at the first table to check if it has a single-team colspan header
        first_body = table_matches[0].group(1)
        first_lines = first_body.split("\n")
        teams_in_first = _extract_teams_from_section(first_lines)
        if len(teams_in_first) == 1:
            return _parse_separate_table_squads(section)

    # Process each table (handles ===Test squads=== / ===ODI squads=== sections)
    for tm in table_matches:
        table_body = tm.group(1)
        table_lines = table_body.split("\n")

        teams = _extract_teams_from_section(table_lines)
        if not teams:
            continue

        has_bullets = any(re.match(r"\s*\*\s*\[?\[", line) for line in table_lines)

        if has_bullets:
            results.extend(_parse_bullet_list_squads(table_lines, teams))
        else:
            results.extend(_parse_row_based_squads(table_lines, teams))

    return results


def _extract_teams_from_section(lines: list[str]) -> list[str]:
    """Extract ordered list of team names from wikitable column headers.

    Handles multiple layouts:
      - All teams on one ``!`` line separated by ``!!``
      - Each team on its own ``!`` line
      - Colspan sub-headers: ``! colspan="3" | {{cr|ENG}}``
    Also stores the number of columns per team if colspan is used,
    for use by _parse_row_based_squads.
    """
    teams: list[str] = []

    # First pass: look for !! separated headers on a single line
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("!"):
            continue
        if "!!" in stripped:
            header_cells = re.split(r"\s*!!\s*", stripped.lstrip("! "))
            for cell in header_cells:
                team = _extract_team_from_header(cell)
                if team:
                    teams.append(team)
            if teams:
                return teams

    # Second pass: separate ! lines
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("!"):
            continue
        cell = stripped.lstrip("! ")
        cell_lower = cell.lower()
        # Skip generic column headers
        if cell_lower in ("name", "style", "domestic team", "", "|-"):
            continue
        # Skip colspan title rows that don't contain a team identifier
        if "colspan" in cell_lower:
            # But DO parse if it contains a team code or known team name
            if "{{cr" in cell_lower or "flagcricket" in cell_lower:
                team = _extract_team_from_header(cell)
                if team:
                    teams.append(team)
                continue
            # Try to extract a team name from the cleaned text
            team = _extract_team_from_header(cell)
            if team:
                teams.append(team)
            continue
        team = _extract_team_from_header(cell)
        if team:
            teams.append(team)

    return teams


def _parse_bullet_list_squads(lines: list[str], teams: list[str]) -> list[dict]:
    """Parse bullet-list squad format.

    Each team's squad is in a separate column cell, with players as
    ``* [[Name]] (annotations)`` bullet items. Column boundaries are
    marked by ``|`` on its own line (cell separator in wikitables).
    """
    results: list[dict] = []
    current_team_idx = -1
    in_player_list = False

    for line in lines:
        stripped = line.strip()

        # Cell separator: bare | (with possible whitespace)
        if re.match(r"^\|\s*$", stripped):
            current_team_idx += 1
            in_player_list = True
            continue

        # Row separator — ignore in bullet mode
        if stripped == "|-" or stripped.startswith("|- "):
            continue

        # End of table
        if stripped == "|}":
            in_player_list = False
            continue

        # Player bullet line
        if in_player_list and re.match(r"\s*\*\s*", stripped):
            if 0 <= current_team_idx < len(teams):
                entry = _parse_player_entry(stripped)
                if entry:
                    entry["team_name"] = teams[current_team_idx]
                    results.append(entry)

    return results


def _parse_row_based_squads(lines: list[str], teams: list[str]) -> list[dict]:
    """Parse row-based squad format.

    Handles three sub-formats:
      1. All cells on one line: ``| [[P1]] (c) || [[P2]] (wk) || [[P3]]``
      2. Multiple columns per team (Name/Style/Domestic) on one line
      3. Each cell on its own line (separated by ``|-``):
         ``| [[MS Dhoni]] (c)``
         ``| [[Ricky Ponting]] (c)``
    """
    results: list[dict] = []

    # Detect cols-per-team by examining the first data row
    cols_per_team = _detect_cols_per_team(lines, len(teams))

    # Check if cells are on separate lines (no || in data rows)
    has_inline_cells = any(
        "||" in line and "[[" in line
        for line in lines
        if line.strip().startswith("|")
        and not line.strip().startswith("|-")
        and not line.strip().startswith("|}")
    )

    if has_inline_cells:
        # Format 1 or 2: cells separated by || on the same line
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            if stripped.startswith(("|-", "|}", "!")):
                continue
            if "[[" not in stripped:
                continue

            row_content = stripped[1:]  # remove leading |
            cells = re.split(r"\|\|+", row_content)

            if cols_per_team > 1:
                for team_idx in range(len(teams)):
                    cell_idx = team_idx * cols_per_team
                    if cell_idx >= len(cells):
                        break
                    cell = cells[cell_idx].strip()
                    if not cell or "[[" not in cell:
                        continue
                    entry = _parse_player_entry(cell)
                    if entry:
                        entry["team_name"] = teams[team_idx]
                        results.append(entry)
            else:
                for i, cell in enumerate(cells):
                    if i >= len(teams):
                        break
                    cell = cell.strip()
                    if not cell or "[[" not in cell:
                        continue
                    entry = _parse_player_entry(cell)
                    if entry:
                        entry["team_name"] = teams[i]
                        results.append(entry)
    else:
        # Format 3: each cell on its own | line, grouped by |- row separators
        current_row_cells: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped == "|-" or stripped.startswith("|- "):
                # Process accumulated row
                if current_row_cells:
                    _assign_row_cells(current_row_cells, teams, results)
                current_row_cells = []
                continue
            if stripped == "|}" or stripped.startswith("!"):
                if current_row_cells:
                    _assign_row_cells(current_row_cells, teams, results)
                current_row_cells = []
                continue
            if stripped.startswith("|") and "[[" in stripped:
                current_row_cells.append(stripped[1:].strip())

        # Process any remaining cells
        if current_row_cells:
            _assign_row_cells(current_row_cells, teams, results)

    return results


def _assign_row_cells(
    cells: list[str], teams: list[str], results: list[dict],
) -> None:
    """Assign player cells to teams based on position within a table row."""
    for i, cell in enumerate(cells):
        if i >= len(teams):
            break
        if not cell or "[[" not in cell:
            continue
        entry = _parse_player_entry(cell)
        if entry:
            entry["team_name"] = teams[i]
            results.append(entry)


def _detect_cols_per_team(lines: list[str], num_teams: int) -> int:
    """Detect how many table columns belong to each team.

    Looks at colspan values in team sub-headers (only those containing a
    team identifier like {{cr|...}}), or infers from the ratio of cells
    in data rows to the number of teams.
    """
    if num_teams == 0:
        return 1

    # Check for colspan in team sub-headers that contain a team identifier
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("!"):
            continue
        if "colspan" not in stripped.lower():
            continue
        # Only consider lines with a team code ({{cr|...}})
        if "{{cr" not in stripped.lower() and "flagcricket" not in stripped.lower():
            continue
        m = re.search(r'colspan\s*=\s*"?(\d+)"?', stripped, re.IGNORECASE)
        if m:
            colspan_val = int(m.group(1))
            if colspan_val >= 2:
                return colspan_val

    # Infer from data rows: count cells in rows with player links
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|-") or stripped.startswith("|}"):
            continue
        if "[[" not in stripped:
            continue
        cells = re.split(r"\|\|+", stripped[1:])
        num_cells = len(cells)
        if num_cells > 0 and num_teams > 0:
            ratio = num_cells / num_teams
            if ratio >= 2.5:
                return round(ratio)
            break

    return 1


def _parse_separate_table_squads(section: str) -> list[dict]:
    """Parse squad sections with one wikitable per team.

    Each table has a colspan header naming the team, followed by player
    rows where the first cell (before ||) is the player entry.
    """
    results: list[dict] = []

    # Split section into individual tables
    table_pattern = re.compile(
        r"\{\|[^\n]*\n(.*?)\|\}", re.DOTALL,
    )

    for table_match in table_pattern.finditer(section):
        table_body = table_match.group(1)
        table_lines = table_body.split("\n")

        # Find team name from colspan header
        team_name = None
        for tl in table_lines:
            tl_stripped = tl.strip()
            if tl_stripped.startswith("!") and "colspan" in tl_stripped.lower():
                team_name = _extract_team_from_header(tl_stripped)
                break

        if not team_name:
            continue

        # Parse player rows — first cell before || is the player
        for tl in table_lines:
            tl_stripped = tl.strip()
            if not tl_stripped.startswith("|"):
                continue
            if tl_stripped.startswith("|-") or tl_stripped.startswith("|}"):
                continue
            if "[[" not in tl_stripped:
                continue

            # First cell is the player entry
            cells = re.split(r"\|\|+", tl_stripped[1:])
            if not cells:
                continue

            entry = _parse_player_entry(cells[0])
            if entry:
                entry["team_name"] = team_name
                results.append(entry)

    return results


def extract_narrative(wikitext: str) -> str | None:
    """Extract the Background / Overview section narrative.

    This provides the historical context for a tour that we feed
    to the LLM for narrative generation.

    TODO: Implement
    """
    pass


def clean_wikitext(text: str) -> str:
    """Remove wiki markup: [[links]], {{templates}}, '''bold''', etc."""
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)  # [[link|text]] → text
    text = re.sub(r"\{\{[^}]+\}\}", "", text)  # remove templates
    text = re.sub(r"'{2,3}", "", text)  # remove bold/italic markers
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)  # remove refs
    text = re.sub(r"<[^>]+>", "", text)  # remove HTML tags
    text = re.sub(r"\([^)]*\)", "", text)  # remove parenthetical qualifiers
    return text.strip()
