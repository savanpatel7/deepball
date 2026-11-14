# Deep Ball: coaches and managers data
# Paste this whole thing into ONE cell of a brand-new Google Colab notebook and run it.
# Takes about 10-20 minutes. When it finishes, deepball_coaches.json.gz downloads automatically.
# Upload that one file to Claude. (If the download is blocked, open the folder icon on the left.)

import concurrent.futures as cf, datetime, gzip, json, re, time, urllib.parse, urllib.request
from bs4 import BeautifulSoup   # already installed in Colab

UA_WIKI = "DeepBallResearch/1.0 (personal sports trivia project)"
UA_WEB = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT = {"made": datetime.datetime.utcnow().isoformat(), "errors": []}

def get(url, ua=UA_WIKI, timeout=120, tries=4, pause=5):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "en"})
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
        except Exception as e:
            code = getattr(e, "code", None)
            if code == 404: return None
            if k == tries - 1:
                OUT["errors"].append(f"{url}: {e}"); print(f"   gave up on {url} ({e})"); return None
            wait = 70 if code == 429 else pause * (k + 1)
            print(f"   retrying in {wait}s ({e})"); time.sleep(wait)

# ---------------------------------------------------------------- 1. Sports-Reference (NBA + NFL head coaches by season, full history)
SR_PAUSE = 3.6   # Sports-Reference allows about 20 pages a minute; stay under it

def sr_page(url):
    time.sleep(SR_PAUSE)
    html = get(url, ua=UA_WEB)
    return html.replace("<!--", "").replace("-->", "") if html else None   # some tables hide inside HTML comments

def table_rows(html, table_id=None):
    soup = BeautifulSoup(html, "html.parser")
    tables = [soup.find("table", id=table_id)] if table_id else soup.find_all("table")
    rows = []
    for t in tables:
        if t is None: continue
        for tr in t.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells or not any(c.get("data-stat") for c in cells): continue
            r = {c.get("data-stat"): c.get_text(" ", strip=True) for c in cells if c.get("data-stat")}
            r["_links"] = [[a.get("href"), a.get_text(strip=True)] for a in tr.find_all("a")]
            r["_coaches_html"] = str(tr.find(attrs={"data-stat": "coaches"}) or "")
            rows.append(r)
    return rows

def scrape_sr(base, index_url, link_re, page_fmt, table_id_fn, coach_index, coach_re):
    print(f"\n{base}: list of franchises ...")
    html = sr_page(base + index_url)
    if not html: return {"franchises": {}, "coach_names": {}}
    fr = sorted(set(re.findall(link_re, html)))
    print(f"   {len(fr)} franchises")
    out = {}
    for i, f in enumerate(fr, 1):
        h = sr_page(base + page_fmt.format(f))
        out[f] = table_rows(h, table_id_fn(f)) if h else []
        if not out[f] and h: out[f] = table_rows(h)   # fall back to every table on the page
        print(f"   {i}/{len(fr)} {f}: {len(out[f])} rows")
    print("   coach name index ...")
    h = sr_page(base + coach_index)
    names = dict(re.findall(coach_re, h)) if h else {}
    print(f"   {len(names)} coach names")
    return {"franchises": out, "coach_names": names}

OUT["nba"] = scrape_sr("https://www.basketball-reference.com", "/teams/", r'href="/teams/([A-Z]{3})/"', "/teams/{}/",
                       lambda f: f, "/coaches/", r'href="/coaches/([a-z0-9]+)\.html">([^<]+)</a>')
OUT["nfl"] = scrape_sr("https://www.pro-football-reference.com", "/teams/", r'href="/teams/([a-z]{3})/"', "/teams/{}/index.htm",
                       lambda f: "team_index", "/coaches/", r'href="/coaches/([A-Za-z0-9]+)\.htm">([^<]+)</a>')
print("\nBaseball-Reference manager names ...")
h = sr_page("https://www.baseball-reference.com/managers/")
OUT["mlb_names"] = dict(re.findall(r'href="/managers/([a-z0-9\.]+)\.shtml">([^<]+)</a>', h)) if h else {}
print(f"   {len(OUT['mlb_names'])} manager names")

# ---------------------------------------------------------------- 2. Wikidata (soccer managers of the big clubs, and title winners)
SPARQL = "https://query.wikidata.org/sparql"
def sparql(q):
    txt = get(SPARQL + "?" + urllib.parse.urlencode({"query": q, "format": "json"}), timeout=300)
    if not txt: return []
    return [{k: v["value"] for k, v in b.items()} for b in json.loads(txt)["results"]["bindings"]]

# Transfermarkt club IDs of the clubs Deep Ball asks about
CLUBS = {"Arsenal": 11, "Chelsea": 631, "Liverpool": 31, "Manchester City": 281, "Manchester United": 985, "Tottenham Hotspur": 148,
         "Newcastle United": 762, "Everton": 29, "Aston Villa": 405, "West Ham United": 379, "Real Madrid": 418, "FC Barcelona": 131,
         "Atlético de Madrid": 13, "Sevilla": 368, "Valencia": 1049, "Villarreal": 1050, "Athletic Bilbao": 621, "Real Sociedad": 681,
         "Real Betis": 150, "Juventus": 506, "Inter Milan": 46, "AC Milan": 5, "AS Roma": 12, "SS Lazio": 398, "Napoli": 6195,
         "ACF Fiorentina": 430, "Atalanta BC": 800, "Bayern Munich": 27, "Borussia Dortmund": 16, "Bayer Leverkusen": 15,
         "Schalke 04": 33, "Werder Bremen": 86, "VfB Stuttgart": 79, "Eintracht Frankfurt": 24, "VfL Wolfsburg": 82,
         "Paris Saint-Germain": 583, "Marseille": 244, "Lyon": 1041, "AS Monaco": 162, "Lille": 1082, "Bordeaux": 40,
         "LA Galaxy": 1061, "Seattle Sounders": 9636, "Toronto FC": 11141, "New York Red Bulls": 623, "D.C. United": 2440,
         "Inter Miami": 69261, "Atlanta United": 51663, "LAFC": 51828, "Portland Timbers": 4291, "Chicago Fire": 432,
         "Ajax Amsterdam": 610, "SL Benfica": 294, "FC Porto": 720}
VALS = " ".join(f'"{v}"' for v in CLUBS.values())
TITLE = '''OPTIONAL { ?art schema:about ?coach ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?title . }'''

print("\nWikidata: managers listed on each club (head coach) ...")
OUT["soc_club_side"] = sparql(f'''SELECT ?tm ?coach ?coachLabel ?title ?start ?end ?roleLabel WHERE {{
  VALUES ?tm {{ {VALS} }} ?club wdt:P7223 ?tm . ?club p:P286 ?st . ?st ps:P286 ?coach .
  OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }} OPTIONAL {{ ?st pq:P2868 ?role }}
  {TITLE} SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }}''')
print(f"   {len(OUT['soc_club_side'])} rows")

print("Wikidata: clubs listed on each manager (coach of sports team) ...")
OUT["soc_person_side"] = sparql(f'''SELECT ?tm ?coach ?coachLabel ?title ?start ?end ?posLabel WHERE {{
  VALUES ?tm {{ {VALS} }} ?club wdt:P7223 ?tm . ?coach p:P6087 ?st . ?st ps:P6087 ?club .
  OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }} OPTIONAL {{ ?st pq:P39 ?pos }}
  {TITLE} SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }}''')
print(f"   {len(OUT['soc_person_side'])} rows")

print("Wikidata: league and Champions League winners by season ...")
OUT["soc_winners"] = sparql('''SELECT ?compLabel ?season ?seasonLabel ?winner ?winnerLabel ?wtm ?start ?end ?pt WHERE {
  VALUES ?comp { wd:Q9448 wd:Q324867 wd:Q15804 wd:Q82595 wd:Q13394 wd:Q18543 wd:Q18756 }
  ?season wdt:P3450 ?comp ; wdt:P1346 ?winner .
  OPTIONAL { ?winner wdt:P7223 ?wtm } OPTIONAL { ?season wdt:P580 ?start } OPTIONAL { ?season wdt:P582 ?end }
  OPTIONAL { ?season wdt:P585 ?pt } SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }''')
print(f"   {len(OUT['soc_winners'])} rows")

# ---------------------------------------------------------------- 3. Wikipedia article for each NBA / NFL / MLB coach (by name)
API = "https://en.wikipedia.org/w/api.php"
def resolve(titles):
    """title asked -> (final title, is_disambiguation, short description) for up to 50 titles"""
    q = {"action": "query", "format": "json", "redirects": 1, "prop": "pageprops|description", "ppprop": "disambiguation",
         "titles": "|".join(titles)}
    txt = get(API + "?" + urllib.parse.urlencode(q))
    if not txt: return {}
    d = json.loads(txt).get("query", {})
    hop = {x["from"]: x["to"] for x in d.get("normalized", [])}
    red = {x["from"]: x["to"] for x in d.get("redirects", [])}
    pages = {p["title"]: p for p in d.get("pages", {}).values() if "missing" not in p and "invalid" not in p}
    out = {}
    for t in titles:
        f = hop.get(t, t); f = red.get(f, f)
        if f in pages: out[t] = (f, "disambiguation" in pages[f].get("pageprops", {}), pages[f].get("description", ""))
    return out

SUFFIX = {"nba": (["basketball coach", "basketball"], "basketball"),
          "nfl": (["American football coach", "American football", "coach"], "football"),
          "mlb": (["baseball manager", "baseball"], "baseball")}
def find_titles(names, sport):
    sufs, kw = SUFFIX[sport]
    names = sorted(set(n for n in names if n))
    cands = {n: [f"{n} ({s})" for s in sufs] + [n] for n in names}
    allc = sorted({c for v in cands.values() for c in v}); got = {}
    for i in range(0, len(allc), 50): got.update(resolve(allc[i:i + 50]))
    found = {}
    for n in names:
        for c in cands[n]:
            if c not in got: continue
            final, dis, desc = got[c]
            if dis: continue
            if kw in desc.lower() or (c != n and not desc): found[n] = final.replace(" ", "_"); break
    print(f"   {sport}: {len(found)}/{len(names)} coaches matched to a Wikipedia article")
    return found

print("\nMatching coaches to Wikipedia articles ...")
OUT["titles"] = {"nba": find_titles(OUT["nba"]["coach_names"].values(), "nba"),
                 "nfl": find_titles(OUT["nfl"]["coach_names"].values(), "nfl"),
                 "mlb": find_titles(OUT["mlb_names"].values(), "mlb")}

# ---------------------------------------------------------------- 4. Wikipedia readership over the last 12 full months
today = datetime.date.today().replace(day=1)
end = today - datetime.timedelta(days=1); start = (end.replace(day=1) - datetime.timedelta(days=330)).replace(day=1)
PV = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{}/monthly/{}/{}"
def views(t):
    txt = get(PV.format(urllib.parse.quote(t, safe=""), start.strftime("%Y%m01"), end.strftime("%Y%m%d")), tries=3, pause=3)
    return t, (sum(i["views"] for i in json.loads(txt)["items"]) if txt else 0)
every = set()
for d in OUT["titles"].values(): every |= set(d.values())
for r in OUT["soc_club_side"] + OUT["soc_person_side"]:
    if r.get("title"): every.add(r["title"].replace(" ", "_"))
print(f"\nReadership for {len(every):,} articles ({start} to {end}) ...")
OUT["views"] = {}
with cf.ThreadPoolExecutor(8) as ex:
    for i, (t, v) in enumerate(ex.map(views, sorted(every)), 1):
        OUT["views"][t] = v
        if i % 500 == 0: print(f"   {i:,}")

# ---------------------------------------------------------------- save
with gzip.open("deepball_coaches.json.gz", "wt", encoding="utf-8") as f: json.dump(OUT, f)
print("\nDone. Upload deepball_coaches.json.gz to Claude.")
print(f"NBA franchises {len(OUT['nba']['franchises'])}, NFL franchises {len(OUT['nfl']['franchises'])}, "
      f"soccer rows {len(OUT['soc_club_side']) + len(OUT['soc_person_side'])}, errors {len(OUT['errors'])}")
top = sorted(OUT["views"].items(), key=lambda x: -x[1])[:8]
print("Most-read coach articles:", ", ".join(f"{t} {v:,}" for t, v in top))
try:
    from google.colab import files; files.download("deepball_coaches.json.gz")
except ImportError:
    pass
