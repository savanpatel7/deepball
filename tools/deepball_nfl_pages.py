# Deep Ball: NFL head coach lists (all 32 teams), NFL award winner lists, 4 more college programs, and readership
# Paste into ONE cell of a NEW Colab notebook and run (about 5-8 minutes). Upload deepball_nfl_pages.json.gz to Claude.
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
def page(search, must):
    hits = q({"action": "query", "list": "search", "srsearch": search, "srlimit": 6}).get("query", {}).get("search", [])
    title = next((h["title"] for h in hits if all(m in h["title"].lower() for m in must)), None)
    html = q({"action": "parse", "page": title, "prop": "text", "redirects": 1}).get("parse", {}).get("text", {}).get("*", "") if title else ""
    time.sleep(1); return {"title": title, "html": html}

NFL = ["Arizona Cardinals", "Atlanta Falcons", "Baltimore Ravens", "Buffalo Bills", "Carolina Panthers", "Chicago Bears", "Cincinnati Bengals",
       "Cleveland Browns", "Dallas Cowboys", "Denver Broncos", "Detroit Lions", "Green Bay Packers", "Houston Texans", "Indianapolis Colts",
       "Jacksonville Jaguars", "Kansas City Chiefs", "Las Vegas Raiders", "Los Angeles Chargers", "Los Angeles Rams", "Miami Dolphins",
       "Minnesota Vikings", "New England Patriots", "New Orleans Saints", "New York Giants", "New York Jets", "Philadelphia Eagles",
       "Pittsburgh Steelers", "San Francisco 49ers", "Seattle Seahawks", "Tampa Bay Buccaneers", "Tennessee Titans", "Washington Commanders"]
OUT = {"nfl_coaches": {}, "awards": {}, "cfb_extra": {}}
for i, t in enumerate(NFL, 1):
    OUT["nfl_coaches"][t] = page(f"List of {t} head coaches", ["head coach"]); print(f"{i}/32 {t}: {OUT['nfl_coaches'][t]['title']}")
AWARDS = {"mvp": ("AP NFL Most Valuable Player", ["most valuable"]), "opoy": ("AP NFL Offensive Player of the Year", ["offensive player"]),
          "dpoy": ("AP NFL Defensive Player of the Year", ["defensive player"]), "oroy": ("AP NFL Offensive Rookie of the Year", ["offensive rookie"]),
          "droy": ("AP NFL Defensive Rookie of the Year", ["defensive rookie"]), "sbmvp": ("Super Bowl Most Valuable Player Award", ["super bowl"]),
          "coy": ("AP NFL Coach of the Year", ["coach of the year"])}
for k, (srch, must) in AWARDS.items():
    OUT["awards"][k] = page(srch, must); print(k, OUT["awards"][k]["title"])
for school, team in [("Michigan State", "Michigan State Spartans"), ("Minnesota", "Minnesota Golden Gophers"), ("Boise State", "Boise State Broncos"), ("UCF", "UCF Knights")]:
    OUT["cfb_extra"][school] = page(f"{team} football head coaches list", ["coach"]); print(school, OUT["cfb_extra"][school]["title"])

# readership for every linked person on the NFL coach pages (the builder matches them by name)
names = set()
for v in OUT["nfl_coaches"].values():
    names |= set(re.findall(r'<a href="/wiki/([^"#:]+)"', v["html"]))
names = sorted(names)[:6000]; OUT["views"] = {}; OUT["views_days"] = 60
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
with gzip.open("deepball_nfl_pages.json.gz", "wt", encoding="utf-8") as f: json.dump(OUT, f)
print("\nDone. Upload deepball_nfl_pages.json.gz to Claude.")
try:
    from google.colab import files; files.download("deepball_nfl_pages.json.gz")
except ImportError:
    pass
