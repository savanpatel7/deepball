# Deep Ball: the pages the first NFL run missed (Offensive and Defensive Rookie of the Year; Michigan State, Minnesota,
# Boise State and UCF head coaches) plus readership for the people on them.
# Paste into ONE cell of a NEW Colab notebook and run (about 1-2 minutes). Upload deepball_nfl_extra.json.gz to Claude.
import gzip, json, re, time, urllib.parse, urllib.request
UA = "DeepBallResearch/1.0 (personal sports trivia project)"
API = "https://en.wikipedia.org/w/api.php"
def q(params):
    for k in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(API + "?" + urllib.parse.urlencode({"format": "json", **params}), headers={"User-Agent": UA}), timeout=60)
            return json.loads(r.read().decode())
        except Exception as e:
            time.sleep(70 if getattr(e, "code", None) == 429 else 5 * (k + 1))
    return {}
def parse(title):
    p = q({"action": "parse", "page": title, "prop": "text", "redirects": 1}).get("parse", {})
    time.sleep(1); return p.get("title"), p.get("text", {}).get("*", "")
def page(exact, search, must):
    # exact titles first (redirects followed), then a search whose hit title holds every word in must
    for t in exact:
        title, html = parse(t)
        if html and "wikitable" in html: return {"title": title, "html": html}
    hits = q({"action": "query", "list": "search", "srsearch": search, "srlimit": 10}).get("query", {}).get("search", [])
    for h in hits:
        if all(m in h["title"].lower() for m in must):
            title, html = parse(h["title"])
            if html and "wikitable" in html: return {"title": title, "html": html}
    return {"title": None, "html": ""}

OUT = {"awards": {}, "cfb_extra": {}}
for k, side in [("oroy", "Offensive"), ("droy", "Defensive")]:
    OUT["awards"][k] = page([f"AP NFL {side} Rookie of the Year", f"AP NFL {side} Rookie of the Year Award", f"NFL {side} Rookie of the Year Award",
                             f"Associated Press NFL {side} Rookie of the Year Award"], f"AP NFL {side} Rookie of the Year", [side.lower(), "rookie"])
    print(k, OUT["awards"][k]["title"], len(OUT["awards"][k]["html"]))
for school, team in [("Michigan State", "Michigan State Spartans"), ("Minnesota", "Minnesota Golden Gophers"), ("Boise State", "Boise State Broncos"), ("UCF", "UCF Knights")]:
    OUT["cfb_extra"][school] = page([f"List of {team} head football coaches", f"List of {team} football head coaches", f"{team} football"],
                                    f"{team} head football coaches", [team.split()[0].lower(), "football"])
    print(school, OUT["cfb_extra"][school]["title"], len(OUT["cfb_extra"][school]["html"]))

names = set()
for grp in OUT.values():
    for v in grp.values(): names |= set(re.findall(r'<a href="/wiki/([^"#:]+)"', v["html"]))
names = sorted(names)[:4000]; OUT["views"] = {}; OUT["views_days"] = 60
print(f"\nReadership for {len(names):,} linked articles ...")
for i in range(0, len(names), 20):
    chunk = [urllib.parse.unquote(n) for n in names[i:i + 20]]
    base = {"action": "query", "prop": "pageviews", "pvipdays": 60, "redirects": 1, "titles": "|".join(c.replace("_", " ") for c in chunk)}
    got, hop, red, cont = {}, {}, {}, {}
    while True:
        j = q({**base, **cont}); d = j.get("query", {})
        hop.update({x["from"]: x["to"] for x in d.get("normalized", [])}); red.update({x["from"]: x["to"] for x in d.get("redirects", [])})
        for p in d.get("pages", {}).values():
            pv = p.get("pageviews") or {}
            if pv: got[p["title"]] = got.get(p["title"], 0) + sum(v or 0 for v in pv.values())
        if "continue" not in j: break
        cont = j["continue"]; time.sleep(1)
    for c in chunk:
        f = c.replace("_", " "); f = hop.get(f, f); f = red.get(f, f); OUT["views"][c] = got.get(f, 0)
    if (i // 20) % 20 == 0: print(f"   {min(i + 20, len(names)):,}/{len(names):,}")
    time.sleep(1.2)
with gzip.open("deepball_nfl_extra.json.gz", "wt", encoding="utf-8") as f: json.dump(OUT, f)
print("\nDone. Upload deepball_nfl_extra.json.gz to Claude.")
try:
    from google.colab import files; files.download("deepball_nfl_extra.json.gz")
except ImportError:
    pass
