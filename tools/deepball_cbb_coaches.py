# Deep Ball: college basketball head coaches (Sports-Reference) + Wikipedia readership
# Paste this whole thing into ONE cell of a brand-new Google Colab notebook and run it.
# Takes about 8-12 minutes. When it finishes, deepball_cbb_coaches.json.gz downloads automatically.
# Upload that one file to Claude.

import datetime, gzip, json, re, time, urllib.parse, urllib.request
from bs4 import BeautifulSoup   # already installed in Colab

UA_WIKI = "DeepBallResearch/1.0 (personal sports trivia project)"
UA_WEB = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT = {"made": datetime.datetime.now(datetime.timezone.utc).isoformat(), "errors": []}

def get(url, ua=UA_WIKI, timeout=120, tries=4, pause=5):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "en"})
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
        except Exception as e:
            code = getattr(e, "code", None)
            if code == 404: return None
            if code == 403: OUT["errors"].append(f"{url}: 403"); print(f"   blocked (403): {url}"); return None
            if k == tries - 1:
                OUT["errors"].append(f"{url}: {e}"); print(f"   gave up on {url} ({e})"); return None
            wait = 70 if code == 429 else pause * (k + 1)
            print(f"   retrying in {wait}s ({e})"); time.sleep(wait)

SR = "https://www.sports-reference.com"
def sr_page(path):
    time.sleep(3.6)   # Sports-Reference allows about 20 pages a minute
    h = get(SR + path, ua=UA_WEB)
    return h.replace("<!--", "").replace("-->", "") if h else None

def season_rows(html):
    """every table row that has a coaches cell: season text + (coach link id, name, W-L)"""
    soup = BeautifulSoup(html, "html.parser"); rows = []
    for td in soup.find_all(attrs={"data-stat": "coaches"}):
        tr = td.find_parent("tr")
        if not tr: continue
        cells = {c.get("data-stat"): c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"]) if c.get("data-stat")}
        coaches = []
        for a in td.find_all("a"):
            m = re.search(r"/coaches/([a-z0-9\-]+)\.html", a.get("href", ""))
            tail = a.next_sibling if isinstance(a.next_sibling, str) else ""
            wl = re.search(r"\((\d+)-(\d+)(?:-(\d+))?\)", tail or "")
            if m: coaches.append([m.group(1), a.get_text(strip=True), [int(x) for x in wl.groups() if x] if wl else []])
        rows.append({"cells": cells, "coaches": coaches})
    return rows

# programs Deep Ball asks about (Sports-Reference school slugs)
CFB = """alabama auburn louisiana-state georgia florida tennessee texas-am mississippi mississippi-state arkansas south-carolina kentucky
missouri vanderbilt texas oklahoma ohio-state michigan penn-state michigan-state wisconsin iowa nebraska minnesota illinois purdue
indiana northwestern southern-california ucla oregon washington notre-dame clemson florida-state miami-fl virginia-tech north-carolina
north-carolina-state louisville pittsburgh syracuse boston-college stanford california utah colorado arizona arizona-state
oklahoma-state texas-tech texas-christian baylor kansas-state kansas west-virginia brigham-young iowa-state boise-state cincinnati
houston central-florida army navy""".split()
CBB = """duke north-carolina kentucky kansas ucla villanova michigan-state connecticut gonzaga arizona louisville indiana syracuse florida
michigan ohio-state wisconsin purdue illinois iowa maryland georgetown marquette butler creighton xavier st-johns-ny texas baylor
houston tennessee auburn alabama arkansas louisiana-state memphis cincinnati virginia wake-forest north-carolina-state oklahoma
oklahoma-state texas-tech iowa-state kansas-state west-virginia oregon washington southern-california stanford nevada-las-vegas
san-diego-state saint-marys-ca notre-dame pittsburgh seton-hall providence miami-fl florida-state georgia-tech missouri
mississippi-state mississippi south-carolina vanderbilt brigham-young utah colorado arizona-state minnesota nebraska northwestern
penn-state rutgers loyola-il wichita-state virginia-commonwealth dayton""".split()

for sport, slugs, fmt in [("cbb", CBB, "/cbb/schools/{}/men/index.html")]:
    print(f"\n{sport}: {len(slugs)} programs")
    OUT[sport] = {}
    for i, sl in enumerate(slugs, 1):
        h = sr_page(fmt.format(sl))
        OUT[sport][sl] = season_rows(h) if h else []
        print(f"   {i}/{len(slugs)} {sl}: {len(OUT[sport][sl])} seasons")
        if i == 3 and not any(OUT[sport].values()):
            print("   Sports-Reference is blocking this Colab session. Stop here and tell Claude."); break

# Wikipedia article + readership for each coach
API = "https://en.wikipedia.org/w/api.php"
def wq(params):
    txt = get(API + "?" + urllib.parse.urlencode({"action": "query", "format": "json", **params}))
    return json.loads(txt) if txt else {}
def resolve(titles):
    d = wq({"redirects": 1, "prop": "pageprops|description", "ppprop": "disambiguation", "titles": "|".join(titles)}).get("query", {})
    hop = {x["from"]: x["to"] for x in d.get("normalized", [])}; red = {x["from"]: x["to"] for x in d.get("redirects", [])}
    pages = {p["title"]: p for p in d.get("pages", {}).values() if "missing" not in p and "invalid" not in p}
    out = {}
    for t in titles:
        f = hop.get(t, t); f = red.get(f, f)
        if f in pages: out[t] = (f, "disambiguation" in pages[f].get("pageprops", {}), pages[f].get("description", ""))
    return out
SUF = {"cfb": (["American football coach", "American football"], "football"), "cbb": (["basketball coach", "basketball"], "basketball")}
OUT["titles"] = {}
for sport in ("cbb",):
    names = sorted({c[1] for rows in OUT.get(sport, {}).values() for r in rows for c in r["coaches"]})
    sufs, kw = SUF[sport]; cands = {n: [f"{n} ({s})" for s in sufs] + [n] for n in names}
    allc = sorted({c for v in cands.values() for c in v}); got = {}
    for i in range(0, len(allc), 50): got.update(resolve(allc[i:i + 50])); time.sleep(1)
    found = {}
    for n in names:
        for c in cands[n]:
            if c not in got: continue
            final, dis, desc = got[c]
            if dis: continue
            if kw in desc.lower() or (c != n and not desc): found[n] = final.replace(" ", "_"); break
    OUT["titles"][sport] = found
    print(f"\n{sport}: {len(found)}/{len(names)} coaches matched to a Wikipedia article")

titles = sorted({t for d in OUT["titles"].values() for t in d.values()}); OUT["views"] = {}; OUT["views_days"] = 60
print(f"Readership for {len(titles):,} articles ...")
for i in range(0, len(titles), 20):
    chunk = titles[i:i + 20]; base = {"prop": "pageviews", "pvipdays": 60, "redirects": 1, "titles": "|".join(t.replace("_", " ") for t in chunk)}
    got, hop, red, cont = {}, {}, {}, {}
    while True:   # Wikipedia answers in pieces; keep asking until it is done
        j = wq({**base, **cont}); d = j.get("query", {})
        hop.update({x["from"]: x["to"] for x in d.get("normalized", [])}); red.update({x["from"]: x["to"] for x in d.get("redirects", [])})
        for p in d.get("pages", {}).values():
            pv = p.get("pageviews") or {}
            if pv: got[p["title"]] = got.get(p["title"], 0) + sum(v or 0 for v in pv.values())
        if "continue" not in j: break
        cont = j["continue"]; time.sleep(1)
    for t in chunk:
        f = t.replace("_", " "); f = hop.get(f, f); f = red.get(f, f); OUT["views"][t] = got.get(f, 0)
    if (i // 20) % 10 == 0: print(f"   {min(i + 20, len(titles)):,}/{len(titles):,}")
    time.sleep(1.5)

with gzip.open("deepball_cbb_coaches.json.gz", "wt", encoding="utf-8") as f: json.dump(OUT, f)
print("\nDone. Upload deepball_cbb_coaches.json.gz to Claude.  errors:", len(OUT["errors"]))
top = sorted(OUT["views"].items(), key=lambda x: -x[1])[:8]
print("Most-read:", ", ".join(f"{t} {v:,}" for t, v in top))
try:
    from google.colab import files; files.download("deepball_cbb_coaches.json.gz")
except ImportError:
    pass
