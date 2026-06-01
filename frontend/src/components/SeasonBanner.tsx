import type { CSSProperties } from "react";
import { useWarRoomState } from "../hooks/useWarRoom";
import { SEASON } from "../lib/season";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function fmtDate(iso: string): string {
  // Accept full ISO timestamps too — keep just the date head.
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/**
 * Slim ribbon under the top bar announcing the season is over and who won.
 * Renders nothing in-season. Tinted with the champion's franchise colour.
 * The frozen date is read from the deployed data (meta.last_sync) so it
 * always reflects the snapshot actually shipped — SEASON.frozenAt is only
 * a fallback if meta is missing.
 */
export function SeasonBanner() {
  const { meta } = useWarRoomState();
  if (!SEASON.concluded) return null;
  const style = { "--champ": `var(--${SEASON.champion})` } as CSSProperties;
  const frozen = fmtDate(meta?.last_sync || SEASON.frozenAt);

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
        Off-season · data frozen {frozen}
      </span>
    </div>
  );
}
