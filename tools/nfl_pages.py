import json, gzip, re
from bs4 import BeautifulSoup
import os
P = json.load(gzip.open("raw/nflpages/p.json.gz"))
X = json.load(gzip.open("raw/nflpages/extra.json.gz")) if os.path.exists("raw/nflpages/extra.json.gz") else {"awards": {}, "cfb_extra": {}, "views": {}}
for k, v in X["awards"].items():
    if v.get("html") and not (P["awards"].get(k) or {}).get("html"): P["awards"][k] = v            # rookie awards from the follow-up run
VIEWS = {**X.get("views", {}), **P["views"]}                                                      # both runs read 60 days
SECTION = {"oroy": "Offensive", "droy": "Defensive"}                                               # both rookie awards share one page
YR = re.compile(r"^(1[89]\d\d|20[0-2]\d)\s*(?:[–-]\s*(\d{4}|present|\d{2}))?$")
def _cells(r): return r.find_all(["th", "td"])
def _person(c):
    for a in c.find_all("a"):
        h = a.get("href", ""); t = a.get("title") or ""
        if "/wiki/" in h and not h.split("/wiki/")[1].startswith(("File:", "Help:", "Category:")) and not re.search(r"^\d{4}|\d{4} .*season|List of|Hall of Fame|Coach of the Year", t):
            return a.get_text(" ", strip=True), t.replace(" (page does not exist)", "")
    return None
def coach_rows(team):
    """[(name, article, first, last, games, interim)] for one franchise, every stint"""
    s = BeautifulSoup(P["nfl_coaches"][team]["html"], "html.parser"); out = []
    for t in s.find_all("table", class_="wikitable"):
        head = " ".join(c.get_text(" ", strip=True) for r in t.find_all("tr")[:2] for c in _cells(r))
        if "Name" not in head and "Coach" not in head: continue
        prev = None
        for r in t.find_all("tr"):
            cs = _cells(r)
            if len(cs) < 4: continue
            txt = [c.get_text(" ", strip=True) for c in cs]
            ni = next((i for i, c in enumerate(cs) if _person(c) and not YR.match(txt[i])), None)
            if ni is None: continue
            name, art = _person(cs[ni])
            yrs = []; last_y = None
            for i in range(ni + 1, len(cs)):
                m = YR.match(re.sub(r"\[.*?\]|[*†‡§#^]", "", txt[i]).strip())
                if m:
                    a = int(m.group(1)); b = m.group(2)
                    b = 2025 if b == "present" else (int(str(a)[:2] + b) if b and len(b) == 2 else int(b) if b else a)
                    yrs += [a, b]; last_y = i
            if not yrs:                                   # interim row sharing the season above (rowspan): same year
                if prev is None: continue
                yrs = [prev, prev]; last_y = ni
            nums = []
            for i in range(last_y + 1, len(cs)):
                v = re.sub(r"\[.*?\]", "", txt[i]).strip()
                if re.fullmatch(r"\d{1,3}", v): nums.append(int(v))
            # games coached is the number equal to wins + losses + ties right after it
            k = next((i for i in range(len(nums) - 2) if nums[i] > 0 and nums[i] == sum(nums[i + 1:i + 4]) or (i + 2 < len(nums) and nums[i] == nums[i + 1] + nums[i + 2])), None)
            gc = nums[k] if k is not None else (nums[0] if nums else None); w = nums[k + 1] if k is not None else None
            prev = max(yrs)
            interim = bool(re.search(r"interim", " ".join(txt), re.I))
            out.append((name, art, min(yrs), max(yrs), gc, interim, w))
    return out
if __name__ == "__main__":
    tot = 0
    for team in P["nfl_coaches"]:
        rows = coach_rows(team); tot += len(rows)
        print(f"{team:24s} {len(rows):3d}  first {min((r[2] for r in rows), default=0)}  nogc {sum(r[4] is None for r in rows)}  e.g. {rows[0][:5] if rows else None} | {rows[-1][:5] if rows else None}")
    print("total", tot)

import unicodedata
def norm(n):
    n = "".join(ch for ch in unicodedata.normalize("NFKD", str(n)) if not unicodedata.combining(ch)).lower()
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", n); return re.sub(r"[^a-z]", "", n)
POS = re.compile(r"^(Quarterback|Running back|Fullback.*|Halfback.*|Wide receiver|Tight end|Linebacker|Cornerback|Defensive (end|tackle|back)|Offensive (tackle|guard|lineman)|Safety.*|Kicker.*|Punter.*|Return specialist|Center.*|Guard.*|Nose tackle|Defensive lineman|Offensive lineman|Placekicker)$", re.I)
TEAMW = ("Cardinals","Falcons","Ravens","Bills","Panthers","Bears","Bengals","Browns","Cowboys","Broncos","Lions","Packers","Texans","Colts","Jaguars","Chiefs",
         "Raiders","Chargers","Rams","Dolphins","Vikings","Patriots","Saints","Giants","Jets","Eagles","Steelers","49ers","Seahawks","Buccaneers","Titans","Oilers",
         "Commanders","Redskins","Football Team","Super Bowl","Pro Bowl")
def _winners(c):
    out = []
    for a in c.find_all("a"):
        h = a.get("href", ""); t = (a.get("title") or "").replace(" (page does not exist)", "")
        if "/wiki/" not in h or h.split("/wiki/")[1].startswith(("File:", "Help:", "Category:")): continue
        if not t or re.search(r"\d{4}", t) or POS.match(t) or t.startswith(("Super Bowl", "List of")) or t.endswith((" football", " Football")) or any(t.endswith(w) or (" " + w + " ") in t for w in TEAMW): continue
        out.append((a.get_text(" ", strip=True), t))
    return out
def award_rows(key):
    """[(season, winner name, article)] from the year-by-year table of an award page"""
    v = P["awards"].get(key) or {}
    if not v.get("html"): return []
    s = BeautifulSoup(v["html"], "html.parser"); out = []
    for t in s.find_all("table", class_="wikitable"):
        hd = [c.get_text(" ", strip=True) for c in t.find_all("tr")[0].find_all(["th", "td"])]
        if not hd or not re.match(r"(Season|Year)", hd[0]): continue
        if key in SECTION:
            h = t.find_previous(["h2", "h3"])
            if not h or SECTION[key] not in h.get_text(): continue
        yr = None
        for r in t.find_all("tr")[1:]:
            cs = r.find_all(["th", "td"]); txt = [c.get_text(" ", strip=True) for c in cs]
            if not cs: continue
            m = re.match(r"^(19|20)\d\d", txt[0])
            if m: yr = int(txt[0][:4]); cs = cs[1:]
            if yr is None: continue
            for w in [x for c in cs for x in _winners(c)]:
                out.append((yr, re.sub(r"\s*\(\d+\)|[*†‡~^#§]", "", w[0]).strip(), w[1]))
        break
    return out
