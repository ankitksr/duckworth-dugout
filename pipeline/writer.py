"""Panel writer — write JSON to data + public dirs, with optional snapshotting."""

import json
from pathlib import Path

from rich.console import Console

console = Console()


def write_json(path: Path, data: dict | list) -> None:
    """Write JSON with readable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_panel(
    panel: str,
    data: dict | list,
    *,
    data_dir: Path,
    public_dir: Path,
    db_conn: object | None = None,
    season: str = "",
) -> None:
    """Write panel JSON to both output dirs and snapshot if changed."""
    write_json(data_dir / f"{panel}.json", data)
    write_json(public_dir / f"{panel}.json", data)

    if db_conn and season:
        try:
            from pipeline.snapshots import maybe_snapshot

            if maybe_snapshot(db_conn, panel, data, season):
                console.print(f"  [dim]Snapshot: {panel}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]Snapshot ({panel}): {e}[/yellow]")
