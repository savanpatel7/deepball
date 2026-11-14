# Deep Ball: college football head coaches 2014-2026 (ESPN) + Wikipedia readership for every coach since 1950
# Paste into ONE cell of a NEW Colab notebook and run. About 8-12 minutes. Upload deepball_cfb_coaches.json.gz to Claude.
# (Coaches up to 2013 come from a public GitHub dataset Claude already has; this fills in the years since.)

import csv, datetime, gzip, io, json, re, time, urllib.parse, urllib.request
UA = "DeepBallResearch/1.0 (personal sports trivia project)"
OUT = {"made": datetime.datetime.now(datetime.timezone.utc).isoformat(), "errors": [], "espn": {}}

def get(url, timeout=60, tries=4, pause=4):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout).read().decode("utf-8", "replace")
        except Exception as e:
            code = getattr(e, "code", None)
            if code == 404: return None
            if k == tries - 1: OUT["errors"].append(f"{url}: {e}"); return None
            time.sleep(70 if code == 429 else pause * (k + 1))

TEAMS = {"Alabama": 333, "Auburn": 2, "LSU": 99, "Georgia": 61, "Florida": 57, "Tennessee": 2633, "Texas A&M": 245, "Ole Miss": 145,
         "Mississippi State": 344, "Arkansas": 8, "South Carolina": 2579, "Kentucky": 96, "Missouri": 142, "Vanderbilt": 238, "Texas": 251,
         "Oklahoma": 201, "Ohio State": 194, "Michigan": 130, "Penn State": 213, "Michigan State": 127, "Wisconsin": 275, "Iowa": 2294,
         "Nebraska": 158, "Minnesota": 135, "Illinois": 356, "Purdue": 2509, "Indiana": 84, "Northwestern": 77, "USC": 30, "UCLA": 26,
         "Oregon": 2483, "Washington": 264, "Notre Dame": 87, "Clemson": 228, "Florida State": 52, "Miami": 2390, "Virginia Tech": 259,
         "North Carolina": 153, "NC State": 152, "Louisville": 97, "Pittsburgh": 221, "Syracuse": 183, "Boston College": 103, "Stanford": 24,
         "California": 25, "Utah": 254, "Colorado": 38, "Arizona": 12, "Arizona State": 9, "Oklahoma State": 197, "Texas Tech": 2641,
         "TCU": 2628, "Baylor": 239, "Kansas State": 2306, "Kansas": 2305, "West Virginia": 277, "BYU": 252, "Iowa State": 66,
         "Boise State": 68, "Cincinnati": 2132, "Houston": 248, "UCF": 2116, "Army": 349, "Navy": 2426}
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
coach_cache = {}
print("ESPN: head coach of each program, 2014-2026 ...")
for n_i, (school, tid) in enumerate(TEAMS.items(), 1):
    for y in range(2014, 2027):
        txt = get(f"{CORE}/seasons/{y}/teams/{tid}/coaches?limit=20")
        names = []
        for it in (json.loads(txt).get("items", []) if txt else []):
            ref = it.get("$ref", "").replace("http://", "https://")
            if ref not in coach_cache:
                c = get(ref); c = json.loads(c) if c else {}
                coach_cache[ref] = (c.get("firstName", "") + " " + c.get("lastName", "")).strip()
            if coach_cache[ref]: names.append(coach_cache[ref])
        OUT["espn"].setdefault(school, {})[y] = names
    print(f"   {n_i}/{len(TEAMS)} {school}: " + ", ".join(sorted({x for v in OUT['espn'][school].values() for x in v})))

# every coach name we will need readership for: ESPN's plus the GitHub dataset's (since 1950)
gh = get("https://raw.githubusercontent.com/lebebr01/ncaafb/master/data-raw/coaches.csv") or ""
def clean(n):   # 'Lawrence T. "Buck" Shaw' -> 'Buck Shaw', 'Nick L. Saban' -> 'Nick Saban'
    m = re.search(r'"([^"]+)"', n); n = re.sub(r'"[^"]+"', " ", n)
    parts = [p for p in n.split() if not re.fullmatch(r"[A-Z]\.?", p)]
    if m and len(parts) >= 2: parts = [m.group(1)] + parts[1:]
    return " ".join(parts)
names = set(x for v in OUT["espn"].values() for l in v.values() for x in l)
for r in csv.DictReader(io.StringIO(gh)):
    if r.get("Year", "0").isdigit() and int(r["Year"]) >= 1950: names.add(clean(r["coach"]))
names = sorted(n for n in names if n)
print(f"\n{len(names):,} coach names; finding their Wikipedia articles ...")

API = "https://en.wikipedia.org/w/api.php"
def wq(params):
    t = get(API + "?" + urllib.parse.urlencode({"action": "query", "format": "json", **params}))
    return json.loads(t) if t else {}
cands = {n: [f"{n} (American football coach)", f"{n} (American football)", n] for n in names}
allc = sorted({c for v in cands.values() for c in v}); got = {}
for i in range(0, len(allc), 50):
    d = wq({"redirects": 1, "prop": "pageprops|description", "ppprop": "disambiguation", "titles": "|".join(allc[i:i + 50])}).get("query", {})
    hop = {x["from"]: x["to"] for x in d.get("normalized", [])}; red = {x["from"]: x["to"] for x in d.get("redirects", [])}
    pages = {p["title"]: p for p in d.get("pages", {}).values() if "missing" not in p and "invalid" not in p}
    for t in allc[i:i + 50]:
        f = hop.get(t, t); f = red.get(f, f)
        if f in pages: got[t] = (f, "disambiguation" in pages[f].get("pageprops", {}), pages[f].get("description", ""))
    time.sleep(1)
OUT["titles"] = {}
for n in names:
    for c in cands[n]:
        if c in got and not got[c][1] and ("football" in got[c][2].lower() or (c != n and not got[c][2])):
            OUT["titles"][n] = got[c][0].replace(" ", "_"); break
print(f"   {len(OUT['titles']):,}/{len(names):,} matched")

titles = sorted(set(OUT["titles"].values())); OUT["views"] = {}; OUT["views_days"] = 60
print(f"Readership for {len(titles):,} articles ...")
for i in range(0, len(titles), 20):
    chunk = titles[i:i + 20]; base = {"prop": "pageviews", "pvipdays": 60, "redirects": 1, "titles": "|".join(t.replace("_", " ") for t in chunk)}
    got2, hop, red, cont = {}, {}, {}, {}
    while True:
        j = wq({**base, **cont}); d = j.get("query", {})
        hop.update({x["from"]: x["to"] for x in d.get("normalized", [])}); red.update({x["from"]: x["to"] for x in d.get("redirects", [])})
        for p in d.get("pages", {}).values():
            pv = p.get("pageviews") or {}
            if pv: got2[p["title"]] = got2.get(p["title"], 0) + sum(v or 0 for v in pv.values())
        if "continue" not in j: break
        cont = j["continue"]; time.sleep(1)
    for t in chunk:
        f = t.replace("_", " "); f = hop.get(f, f); f = red.get(f, f); OUT["views"][t] = got2.get(f, 0)
    if (i // 20) % 10 == 0: print(f"   {min(i + 20, len(titles)):,}/{len(titles):,}")
    time.sleep(1.5)

with gzip.open("deepball_cfb_coaches.json.gz", "wt", encoding="utf-8") as f: json.dump(OUT, f)
print("\nDone. Upload deepball_cfb_coaches.json.gz to Claude.  errors:", len(OUT["errors"]))
try:
    from google.colab import files; files.download("deepball_cfb_coaches.json.gz")
except ImportError:
    pass
