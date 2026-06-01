import type { CSSProperties } from "react";
import { SEASON } from "../lib/season";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function fmtDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/**
 * Slim ribbon under the top bar announcing the season is over and who won.
 * Renders nothing in-season. Tinted with the champion's franchise colour.
 */
export function SeasonBanner() {
  if (!SEASON.concluded) return null;
  const style = { "--champ": `var(--${SEASON.champion})` } as CSSProperties;

  return (
    <div className="wr-season-banner" style={style}>
      <span className="wr-sb-trophy" aria-hidden>🏆</span>
      <span className="wr-sb-title">IPL {SEASON.year} CONCLUDED</span>
      <span className="wr-sb-sep" aria-hidden>·</span>
      <span className="wr-sb-champ">{SEASON.championName} — Champions</span>
      {SEASON.finalResult && (
        <>
          <span className="wr-sb-sep" aria-hidden>·</span>
          <span className="wr-sb-result">{SEASON.finalResult}</span>
        </>
      )}
      <span className="wr-sb-spacer" />
      <span className="wr-sb-frozen">
        Off-season · data frozen {fmtDate(SEASON.frozenAt)}
      </span>
    </div>
  );
}
