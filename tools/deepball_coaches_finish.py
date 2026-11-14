# Deep Ball: finish the coaches data (run in the SAME Colab session, in a NEW cell, after stopping the first cell)
# Uses what the first cell already collected (it is still in memory as OUT). Takes about 3-5 minutes.

import json, gzip, time, urllib.parse

# 1. NFL head coaches by team from Wikidata (Pro-Football-Reference blocks Colab)
print("Wikidata: NFL head coaches by team ...")
OUT["nfl_wd"] = sparql('''SELECT ?team ?teamLabel ?coach ?coachLabel ?title ?start ?end WHERE {
  ?team wdt:P118 wd:Q1215884 . ?team p:P286 ?st . ?st ps:P286 ?coach .
  OPTIONAL { ?st pq:P580 ?start } OPTIONAL { ?st pq:P582 ?end }
  OPTIONAL { ?art schema:about ?coach ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?title . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }''')
print(f"   {len(OUT['nfl_wd'])} rows")

# 2. Readership: 50 articles per request (last 60 days), slowly, so Wikipedia doesn't rate-limit us
every = set()
for d in OUT["titles"].values(): every |= set(d.values())
for r in OUT["soc_club_side"] + OUT["soc_person_side"] + OUT["nfl_wd"]:
    if r.get("title"): every.add(r["title"].replace(" ", "_"))
titles = sorted(every); OUT["views"] = {}; OUT["views_days"] = 60
print(f"\nReadership for {len(titles):,} articles, 50 at a time ...")
for i in range(0, len(titles), 50):
    chunk = titles[i:i + 50]
    q = {"action": "query", "format": "json", "prop": "pageviews", "pvipdays": 60, "redirects": 1,
         "titles": "|".join(t.replace("_", " ") for t in chunk)}
    txt = get(API + "?" + urllib.parse.urlencode(q))
    if txt:
        d = json.loads(txt).get("query", {})
        hop = {x["from"]: x["to"] for x in d.get("normalized", [])}
        red = {x["from"]: x["to"] for x in d.get("redirects", [])}
        got = {p["title"]: sum(v or 0 for v in (p.get("pageviews") or {}).values()) for p in d.get("pages", {}).values()}
        for t in chunk:
            f = t.replace("_", " "); f = hop.get(f, f); f = red.get(f, f)
            OUT["views"][t] = got.get(f, 0)
    print(f"   {min(i + 50, len(titles)):,}/{len(titles):,}")
    time.sleep(1.5)

with gzip.open("deepball_coaches.json.gz", "wt", encoding="utf-8") as f: json.dump(OUT, f)
top = sorted(OUT["views"].items(), key=lambda x: -x[1])[:8]
print("\nDone. Most-read:", ", ".join(f"{t} {v:,}" for t, v in top))
print("Upload deepball_coaches.json.gz to Claude.")
try:
    from google.colab import files; files.download("deepball_coaches.json.gz")
except ImportError:
    pass
