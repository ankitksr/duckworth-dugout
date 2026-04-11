// Cloudflare Worker that fires GitHub workflow_dispatch events on a
// reliable cron. Replaces GitHub Actions cron, which drifts 10-40 min
// randomly during peak times. Cloudflare Cron fires within ~1s of the
// schedule.
//
// Setup (one-time):
//   1. Create a fine-grained GitHub PAT scoped to ankitksr/duckworth-
//      dugout with Actions: Read & Write permission.
//   2. wrangler secret put GITHUB_PAT     (paste the PAT)
//   3. wrangler deploy
//
// Three cron triggers, all gated server-side here so out-of-window
// fires never reach GitHub Actions and never burn CI minutes:
//
//   */5 * * * *     → live-update.yml — every 5 min during match window
//   */30 * * * *    → sync-deploy.yml — live,hot (in window) / hot (off)
//   10 1,5,9,13,17,21 * * * → sync-deploy.yml — all (warm+cool full sync)
//
// All three are gated to IPL season (March-May UTC). The live-update
// cron is additionally gated to the match window (weekday UTC 13-19,
// weekend UTC 9-19).
//
// Worker logs surface dispatch failures (e.g. expired PAT). Cloudflare
// retries scheduled events on transient failures automatically.

const REPO = "ankitksr/duckworth-dugout";
const REF = "main";

function isInSeason(date) {
  const month = date.getUTCMonth() + 1;
  return month >= 3 && month <= 5;
}

function isMatchWindow(date) {
  const dow = date.getUTCDay(); // 0=Sun .. 6=Sat
  const hour = date.getUTCHours();
  // Last fire in both windows is UTC 18:55 = IST 00:25 — ~1.5h past a
  // normal 23:00 IST match end. Covers rain delays + super overs +
  // post-match standings settle without burning runner minutes on the
  // 00:30-01:30 IST tail where nothing meaningful changes.
  //
  // Weekend (Sat/Sun): day + evening matches, UTC 9-18 (IST 14:30-00:25)
  if (dow === 0 || dow === 6) {
    return hour >= 9 && hour <= 18;
  }
  // Weekday: evening matches only, UTC 13-18 (IST 18:30-00:25)
  return hour >= 13 && hour <= 18;
}

async function dispatch(env, workflow, inputs) {
  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`;
  const body = inputs ? { ref: REF, inputs } : { ref: REF };

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "duckworth-dugout-cron",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    console.error(`Dispatch failed (${workflow}): ${res.status} ${text}`);
    throw new Error(`GitHub dispatch ${res.status}`);
  }
  console.log(`Dispatched ${workflow}${inputs ? ` (${JSON.stringify(inputs)})` : ""}`);
}

export default {
  async scheduled(event, env, ctx) {
    const now = new Date();

    if (!isInSeason(now)) {
      console.log(`Off-season (month=${now.getUTCMonth() + 1}), skipping`);
      return;
    }

    if (event.cron === "*/5 * * * *") {
      // live-update — only during match window
      if (!isMatchWindow(now)) {
        console.log(`Outside match window, skipping live-update`);
        return;
      }
      return dispatch(env, "live-update.yml");
    }

    if (event.cron === "*/30 * * * *") {
      // sync-deploy hot tier. In match window: live + hot. Off-window:
      // hot only, and only on the hour (every other 30-min tick) to
      // mirror the existing off-peak hourly cadence.
      if (isMatchWindow(now)) {
        return dispatch(env, "sync-deploy.yml", { tiers: "live,hot" });
      }
      if (now.getUTCMinutes() === 0) {
        return dispatch(env, "sync-deploy.yml", { tiers: "hot" });
      }
      return;
    }

    // 10 1,5,9,13,17,21 * * * — full sync (live + hot + warm + cool)
    return dispatch(env, "sync-deploy.yml", { tiers: "all" });
  },
};
