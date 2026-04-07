import type { WRFixture, WRFormEntry, WRMatchup } from "../types/war-room";

// ── Time formatting ──

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function istClock(): string {
  const now = new Date();
  const ist = new Date(now.getTime() + 5.5 * 3600000);
  return [ist.getUTCHours(), ist.getUTCMinutes(), ist.getUTCSeconds()]
    .map((v) => String(v).padStart(2, "0"))
    .join(":") + " IST";
}

export function formatMatchDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  const months = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
  return `${months[d.getMonth()]} ${d.getDate()}`;
}

// ── Display formatting ──

export function nrrDisplay(nrr: string): { text: string; positive: boolean } {
  if (nrr === "-" || nrr === "") return { text: "-", positive: false };
  const positive = !nrr.startsWith("-");
  return { text: nrr.startsWith("+") || nrr.startsWith("-") ? nrr : `+${nrr}`, positive };
}

// ── Data helpers ──

export function teamInvolved(fixture: WRFixture, teamId: string): boolean {
  return fixture.team1 === teamId || fixture.team2 === teamId;
}

export function isStructuredMatchup(mu: WRMatchup | { matchup: string; insight: string }): mu is WRMatchup {
  return "player1" in mu;
}

export function getFormEntry(form: Record<string, unknown>, team: string): WRFormEntry | null {
  const entry = form[team];
  if (!entry || typeof entry !== "object") return null;
  if ("wins" in (entry as Record<string, unknown>)) return entry as WRFormEntry;
  return null;
}
