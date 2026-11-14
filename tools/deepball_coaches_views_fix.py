# Deep Ball: fill in readership the last cell missed (Wikipedia only answered for part of each batch)
# Run in the SAME Colab session as a new cell. About 2-4 minutes.
import json, gzip, time, urllib.parse

missing = [t for t, v in OUT["views"].items() if not v]
print(f"{len(missing):,} articles still without readership")
for i in range(0, len(missing), 20):
    chunk = missing[i:i + 20]
    q = {"action": "query", "format": "json", "prop": "pageviews", "pvipdays": 60, "redirects": 1,
         "titles": "|".join(t.replace("_", " ") for t in chunk)}
    got, hop, red, cont = {}, {}, {}, {}
    while True:   # Wikipedia hands the answer back in pieces; keep asking until it says it's done
        txt = get(API + "?" + urllib.parse.urlencode({**q, **cont}))
        if not txt: break
        j = json.loads(txt); d = j.get("query", {})
        hop.update({x["from"]: x["to"] for x in d.get("normalized", [])})
        red.update({x["from"]: x["to"] for x in d.get("redirects", [])})
        for p in d.get("pages", {}).values():
            pv = p.get("pageviews") or {}
            if pv: got[p["title"]] = got.get(p["title"], 0) + sum(v or 0 for v in pv.values())
        if "continue" not in j: break
        cont = j["continue"]; time.sleep(1)
    for t in chunk:
        f = t.replace("_", " "); f = hop.get(f, f); f = red.get(f, f)
        if got.get(f): OUT["views"][t] = got[f]
    print(f"   {min(i + 20, len(missing)):,}/{len(missing):,}")
    time.sleep(1.5)

print("still missing:", sum(1 for v in OUT["views"].values() if not v))
with gzip.open("deepball_coaches.json.gz", "wt", encoding="utf-8") as f: json.dump(OUT, f)
print("Done. Upload deepball_coaches.json.gz to Claude.")
try:
    from google.colab import files; files.download("deepball_coaches.json.gz")
except ImportError:
    pass
