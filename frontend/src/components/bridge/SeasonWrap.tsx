import type { CSSProperties } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import { SEASON } from "../../lib/season";

/**
 * Center-column panel shown in place of the pre-match Briefing once the
 * season has concluded. The briefing was a forward-looking tactical read —
 * meaningless in the off-season — so this replaces it with the terminal
 * state: who won, and a glance at the season just gone. The standings,
 * pulse and narrative panels around it remain as the season archive.
 */
export function SeasonWrap() {
  const { standings, schedule } = useWarRoomState();
  const champ = standings?.find((t) => t.franchise_id === SEASON.champion);
  const champColor =
    champ?.war_room_color ?? champ?.primary_color ?? `var(--${SEASON.champion})`;
  const champShort = champ?.short_name ?? SEASON.champion.toUpperCase();

  const completed = schedule?.filter((m) => m.status === "completed").length ?? 0;

  const heroStyle = {
    "--champ": champColor,
    background: [
      `radial-gradient(ellipse 80% 120% at 50% -10%, color-mix(in srgb, ${champColor} 22%, transparent), transparent)`,
      "linear-gradient(180deg, rgba(16, 20, 30, 0.96), rgba(12, 14, 19, 0.98))",
    ].join(", "),
  } as CSSProperties;

  return (
    <div className="wr-pnl wr-briefing-pnl wr-seasonwrap-pnl">
      <div className="wr-ph">
        Season Wrap <sub>IPL {SEASON.year}</sub>
      </div>

      <section className="wr-sw-hero" style={heroStyle}>
        <span className="wr-sw-trophy" aria-hidden>🏆</span>
        <span className="wr-sw-champ-tag">CHAMPIONS</span>
        <span className="wr-sw-champ-name" style={{ color: champColor }}>
          {champShort}
        </span>
        <span className="wr-sw-champ-full">{SEASON.championName}</span>
        {SEASON.finalResult && (
          <span className="wr-sw-final">{SEASON.finalResult}</span>
        )}
      </section>

      <div className="wr-sw-glance">
        <div className="wr-sw-stat">
          <strong>{SEASON.year}</strong>
          <span>SEASON</span>
        </div>
        {completed > 0 && (
          <div className="wr-sw-stat">
            <strong>{completed}</strong>
            <span>MATCHES PLAYED</span>
          </div>
        )}
        <div className="wr-sw-stat">
          <strong>{champShort}</strong>
          <span>LEAGUE TOPPER</span>
        </div>
      </div>

      <div className="wr-sw-note">
        Dugout is in off-season — live sync is paused. The standings, season
        pulse, narratives and intel below are a frozen archive of how the
        season closed. See you for IPL {Number(SEASON.year) + 1}.
      </div>
    </div>
  );
}
