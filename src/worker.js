// Deep Ball Worker: serves the game from public/ and the stats API at /api/score.
// POST {day:"dYYYYMMDD", uid, score, picks:[player index or -1, x7]}
//   saves one run per player per day, returns the day's scores and, for each prompt,
//   how many players gave the same answer (so the game can show real rarity).
const ROUNDS = 7, MAX_SCORE = 7 * 230;   // seven Deep Balls

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}
function allowedDays() {
  const fmt = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });
  return [0, 1].map((d) => "d" + fmt.format(new Date(Date.now() - d * 86400000)).replace(/-/g, ""));
}
async function stats(db, day, picks) {
  const { results: sc } = await db.prepare("SELECT score FROM scores WHERE day = ? LIMIT 5000").bind(day).all();
  const { results: pk } = await db.prepare("SELECT slot, player, COUNT(*) AS n FROM picks WHERE day = ? GROUP BY slot, player").bind(day).all();
  const tot = Array(ROUNDS).fill(0), cnt = {};
  for (const r of pk) { tot[r.slot] += r.n; cnt[r.slot + ":" + r.player] = r.n; }
  const shares = (picks || []).map((p, i) => ({ n: p >= 0 ? cnt[i + ":" + p] || 0 : 0, total: tot[i] }));
  return { scores: sc.map((r) => r.score), shares };
}
async function handlePost(request, env) {
  let b; try { b = await request.json(); } catch { return json({ error: "bad json" }, 400); }
  const { day, uid, score, picks } = b || {};
  if (typeof day !== "string" || !allowedDays().includes(day)) return json({ error: "bad day" }, 400);
  if (typeof uid !== "string" || uid.length < 8 || uid.length > 64) return json({ error: "bad uid" }, 400);
  if (!Number.isInteger(score) || score < 0 || score > MAX_SCORE) return json({ error: "bad score" }, 400);
  if (!Array.isArray(picks) || picks.length !== ROUNDS || !picks.every((p) => Number.isInteger(p) && p >= -1 && p < 100000))
    return json({ error: "bad picks" }, 400);
  const ins = await env.DB.prepare("INSERT OR IGNORE INTO scores (day, uid, score, created_at) VALUES (?, ?, ?, ?)")
    .bind(day, uid, score, Date.now()).run();
  if (ins.meta && ins.meta.changes > 0) {
    await env.DB.batch(picks.map((p, i) => p >= 0
      ? env.DB.prepare("INSERT OR IGNORE INTO picks (day, uid, slot, player) VALUES (?, ?, ?, ?)").bind(day, uid, i, p)
      : null).filter(Boolean));
  }
  return json(await stats(env.DB, day, picks));
}
// POST {day, dig, sport, prompt, note}: a player's "something wrong or missing" report
async function handleReport(request, env) {
  let b; try { b = await request.json(); } catch { return json({ error: "bad json" }, 400); }
  const s = (v, n) => (typeof v === "string" ? v.slice(0, n) : "");
  const note = s(b && b.note, 500).trim();
  if (!note) return json({ error: "empty" }, 400);
  await env.DB.prepare("INSERT INTO reports (created_at, day, sport, prompt, note) VALUES (?, ?, ?, ?, ?)")
    .bind(Date.now(), String((b && b.dig) ?? (b && b.day) ?? ""), s(b.sport, 20), s(b.prompt, 300), note).run();
  return json({ ok: true });
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/score") {
      try {
        if (request.method === "POST") return await handlePost(request, env);
        return json({ error: "method not allowed" }, 405);
      } catch (e) { return json({ error: "server error" }, 500); }
    }
    if (url.pathname === "/api/report") {
      try {
        if (request.method === "POST") return await handleReport(request, env);
        return json({ error: "method not allowed" }, 405);
      } catch (e) { return json({ error: "server error" }, 500); }
    }
    return env.ASSETS.fetch(request);
  },
};
