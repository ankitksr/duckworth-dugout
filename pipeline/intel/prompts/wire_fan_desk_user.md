Produce 1–2 dispatches from the Fan Desk for the IPL AI Wire.

<base_context>{base_context}</base_context>

---

<focused_context>{focused_context}</focused_context>

---

## ACTIVE TRIGGERS

Each dispatch must anchor to one of these triggers. If no trigger below fits an emotional fan angle, return `[]`.

{active_triggers}

---

## ALREADY ON THE WIRE THIS CYCLE

<already_on_the_wire>
These dispatches were produced by the other desks — Situation Room, Scout Report, News Desk, Matchday Preview, The Archive, The Take — in the same cycle. Do not restate their analysis in plainer English. Your job is to find what they missed: the feeling, the moment, the human beat.

{other_wire_output}
</already_on_the_wire>

---

## INSTRUCTIONS

- Produce **1–2 dispatches** ONLY. Quality > quantity. Return `[]` if no trigger warrants a dispatch.
- Each dispatch targets exactly one team and one emotional register (one of: `fan_joy`, `fan_worry`, `fan_watch`, `fan_remember`, `fan_alert`).
- Prefer a team that has **zero** dispatches in `<already_on_the_wire>` above. If you must write about a team that is already covered, the emotional angle must be clearly different from what the analysts filed.
- Never file a `fan_alert` about a team that already has any dispatch in this cycle.
- Plain English throughout. If a cricket term appears (NRR, strike rate, economy, etc.), gloss it in the same sentence.
- Headlines should survive the "read this to a friend who doesn't watch IPL" test.

Valid franchise IDs: {franchise_ids}

## YOUR PRIOR FAN DESK DISPATCHES (do not restate)

{previous_entries}

Return ONLY a JSON array (or empty array `[]`).
