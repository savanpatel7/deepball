# Deep Ball: download each program's "List of ... head football coaches" page from Wikipedia (about 2-3 minutes)
# Paste into ONE cell of a NEW Colab notebook and run. Upload deepball_cfb_coach_pages.json.gz to Claude.
import gzip, json, time, urllib.parse, urllib.request
UA = "DeepBallResearch/1.0 (personal sports trivia project)"
API = "https://en.wikipedia.org/w/api.php"
def q(params):
    for k in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(API + "?" + urllib.parse.urlencode({"format": "json", **params}), headers={"User-Agent": UA}), timeout=60)
            return json.loads(r.read().decode())
        except Exception as e:
            time.sleep(70 if getattr(e, "code", None) == 429 else 5 * (k + 1))
    return {}
SCHOOLS = {"Alabama": "Alabama Crimson Tide", "Auburn": "Auburn Tigers", "LSU": "LSU Tigers", "Georgia": "Georgia Bulldogs", "Florida": "Florida Gators",
  "Tennessee": "Tennessee Volunteers", "Texas A&M": "Texas A&M Aggies", "Ole Miss": "Ole Miss Rebels", "Mississippi State": "Mississippi State Bulldogs",
  "Arkansas": "Arkansas Razorbacks", "South Carolina": "South Carolina Gamecocks", "Kentucky": "Kentucky Wildcats", "Missouri": "Missouri Tigers",
  "Vanderbilt": "Vanderbilt Commodores", "Texas": "Texas Longhorns", "Oklahoma": "Oklahoma Sooners", "Ohio State": "Ohio State Buckeyes",
  "Michigan": "Michigan Wolverines", "Penn State": "Penn State Nittany Lions", "Michigan State": "Michigan State Spartans", "Wisconsin": "Wisconsin Badgers",
  "Iowa": "Iowa Hawkeyes", "Nebraska": "Nebraska Cornhuskers", "Minnesota": "Minnesota Golden Gophers", "Illinois": "Illinois Fighting Illini",
  "Purdue": "Purdue Boilermakers", "Indiana": "Indiana Hoosiers", "Northwestern": "Northwestern Wildcats", "USC": "USC Trojans", "UCLA": "UCLA Bruins",
  "Oregon": "Oregon Ducks", "Washington": "Washington Huskies", "Notre Dame": "Notre Dame Fighting Irish", "Clemson": "Clemson Tigers",
  "Florida State": "Florida State Seminoles", "Miami": "Miami Hurricanes", "Virginia Tech": "Virginia Tech Hokies", "North Carolina": "North Carolina Tar Heels",
  "NC State": "NC State Wolfpack", "Louisville": "Louisville Cardinals", "Pittsburgh": "Pittsburgh Panthers", "Syracuse": "Syracuse Orange",
  "Boston College": "Boston College Eagles", "Stanford": "Stanford Cardinal", "California": "California Golden Bears", "Utah": "Utah Utes",
  "Colorado": "Colorado Buffaloes", "Arizona": "Arizona Wildcats", "Arizona State": "Arizona State Sun Devils", "Oklahoma State": "Oklahoma State Cowboys",
  "Texas Tech": "Texas Tech Red Raiders", "TCU": "TCU Horned Frogs", "Baylor": "Baylor Bears", "Kansas State": "Kansas State Wildcats",
  "Kansas": "Kansas Jayhawks", "West Virginia": "West Virginia Mountaineers", "BYU": "BYU Cougars", "Iowa State": "Iowa State Cyclones",
  "Boise State": "Boise State Broncos", "Cincinnati": "Cincinnati Bearcats", "Houston": "Houston Cougars", "UCF": "UCF Knights",
  "Army": "Army Black Knights", "Navy": "Navy Midshipmen"}
OUT = {}
for i, (school, team) in enumerate(SCHOOLS.items(), 1):
    hits = q({"action": "query", "list": "search", "srsearch": f"List of {team} head football coaches", "srlimit": 5}).get("query", {}).get("search", [])
    title = next((h["title"] for h in hits if "head football coach" in h["title"].lower()), None)
    html = q({"action": "parse", "page": title, "prop": "text", "redirects": 1}).get("parse", {}).get("text", {}).get("*", "") if title else ""
    OUT[school] = {"title": title, "html": html}
    print(f"{i}/{len(SCHOOLS)} {school}: {title} ({len(html):,} chars)")
    time.sleep(1)
with gzip.open("deepball_cfb_coach_pages.json.gz", "wt", encoding="utf-8") as f: json.dump(OUT, f)
print("\nDone. Upload deepball_cfb_coach_pages.json.gz to Claude.  missing:", [s for s, v in OUT.items() if not v["html"]])
try:
    from google.colab import files; files.download("deepball_cfb_coach_pages.json.gz")
except ImportError:
    pass
