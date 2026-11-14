#!/usr/bin/env python3
"""
Deep Ball: collect Wikipedia clickstream data for sports articles.

Google Colab: paste this whole file into one cell and run it (set MONTHS below).
When it finishes, both output files download to your computer automatically.

Or run on your own computer (needs internet, Python 3.8+, no extra packages):
    python3 wiki_clickstream.py              # last 12 months (about 30-60 min)
    python3 wiki_clickstream.py --months 3   # quicker test run

It writes two small files next to this script. Upload both to Claude:
    wikidata_players.tsv.gz      Wikipedia article title for each player ID
                                 (Baseball-Reference, Pro-Football-Reference, ESPN, Transfermarkt...)
    clickstream_sports.tsv.gz    referrer -> player-article click counts, summed over the months

Nothing big is saved to disk: each monthly dump (several hundred MB) is streamed and filtered on the fly.
"""
import argparse, collections, csv, gzip, io, json, re, sys, time, urllib.parse, urllib.request

MONTHS = 12   # how many recent months of clickstream to add up (3 is a quick test)

UA = "DeepBallResearch/1.0 (personal sports trivia project; python urllib)"
DUMPS = "https://dumps.wikimedia.org/other/clickstream/"
SPARQL = "https://query.wikidata.org/sparql"

# Wikidata properties that match the IDs in Deep Ball's data sources
PROPS = {
    "P1825": "bbref_mlb",      # Baseball-Reference MLB player ID (Lahman bbrefID)
    "P3561": "pfr",            # Pro-Football-Reference player ID
    "P3686": "espn_nfl",       # ESPN NFL player ID
    "P2685": "bbref_nba",      # Basketball-Reference NBA player ID
    "P3685": "espn_nba",       # ESPN NBA player ID
    "P3696": "sr_cbb",         # Sports-Reference college basketball player ID
    "P2446": "transfermarkt",  # Transfermarkt player ID
}

# referrer pages that look like teams, seasons, rosters, programs, national teams, constructors
TEAMISH = re.compile(
    r"(season|seasons|team|teams|roster|players|draft|football|basketball|baseball|soccer|F\.C\.|FC|C\.F\.|A\.F\.C\.|"
    r"national|Formula One|Grand Prix|Racing|Motorsport|"
    r"Cardinals|Falcons|Ravens|Bills|Panthers|Bears|Bengals|Browns|Cowboys|Broncos|Lions|Packers|Texans|Colts|Jaguars|Chiefs|"
    r"Raiders|Chargers|Rams|Dolphins|Vikings|Patriots|Saints|Giants|Jets|Eagles|Steelers|49ers|Seahawks|Buccaneers|Titans|Commanders|Redskins|Oilers|"
    r"Diamondbacks|Braves|Orioles|Red Sox|Cubs|White Sox|Reds|Guardians|Indians|Rockies|Tigers|Astros|Royals|Angels|Dodgers|Marlins|Brewers|Twins|"
    r"Mets|Yankees|Athletics|Phillies|Pirates|Padres|Mariners|Rays|Rangers|Blue Jays|Nationals|Expos|"
    r"Hawks|Celtics|Nets|Hornets|Bulls|Cavaliers|Mavericks|Nuggets|Pistons|Warriors|Rockets|Pacers|Clippers|Lakers|Grizzlies|Heat|Bucks|"
    r"Timberwolves|Pelicans|Knicks|Thunder|Magic|76ers|Suns|Trail Blazers|Kings|Spurs|Raptors|Jazz|Wizards|SuperSonics|Bobcats)"
)

def get(url, timeout=120, tries=4):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)
        except Exception as e:
            if k == tries - 1: raise
            print(f"   retrying ({e})"); time.sleep(5 * (k + 1))

def wikidata():
    rows = []
    for prop, name in PROPS.items():
        q = f"""SELECT ?id ?title WHERE {{ ?p wdt:{prop} ?id . ?a schema:about ?p ;
                schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?title . }}"""
        url = SPARQL + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
        print(f"Wikidata {name} ...", end=" ", flush=True)
        try:
            data = json.load(get(url, timeout=300))["results"]["bindings"]
        except Exception as e:
            print(f"FAILED ({e}), skipping"); continue
        for b in data: rows.append((name, b["id"]["value"], b["title"]["value"].replace(" ", "_")))
        print(len(data))
    with gzip.open("wikidata_players.tsv.gz", "wt", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t"); w.writerow(["source", "id", "title"]); w.writerows(rows)
    return {t for _, _, t in rows}

def months(n):
    html = get(DUMPS).read().decode()
    ms = sorted(set(re.findall(r'href="(\d{4}-\d{2})/"', html)))
    return ms[-n:]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--months", type=int, default=MONTHS)
    a, _ = ap.parse_known_args()   # ignore the extra arguments Jupyter/Colab passes
    players = wikidata()
    print(f"{len(players):,} player articles found\n")
    agg = collections.Counter(); totals = collections.Counter()
    for m in months(a.months):
        url = f"{DUMPS}{m}/clickstream-enwiki-{m}.tsv.gz"
        print(f"Clickstream {m} (streaming, a few minutes) ...", flush=True); t0 = time.time(); kept = 0
        with gzip.open(get(url, timeout=600), "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) != 4: continue
                ref, tgt, typ, n = p; n = int(n)
                if tgt in players:
                    totals[tgt] += n                      # all traffic into the player article (fame)
                    if typ != "external": agg[(ref, tgt)] += n; kept += 1
                elif typ != "external" and TEAMISH.search(ref) and not ref.startswith("other-"):
                    agg[(ref, tgt)] += n; kept += 1      # team page -> someone not in Wikidata list (college, F1...)
        print(f"   kept {kept:,} rows in {time.time() - t0:.0f}s")
    with gzip.open("clickstream_sports.tsv.gz", "wt", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t"); w.writerow(["referrer", "target", "clicks"])
        for t, n in totals.items(): w.writerow(["__ALL__", t, n])
        for (r, t), n in agg.items():
            if n >= 30 or t in players: w.writerow([r, t, n])   # drop tiny non-player pairs to keep the file small
    print("\nDone. Upload wikidata_players.tsv.gz and clickstream_sports.tsv.gz to Claude.\n")
    try:   # in Google Colab, download both files to your computer automatically
        from google.colab import files
        files.download("wikidata_players.tsv.gz"); files.download("clickstream_sports.tsv.gz")
    except ImportError:
        pass
    print("Sanity check, top pages sending readers to Drew Bledsoe:")
    for (r, t), n in sorted(((k, v) for k, v in agg.items() if k[1] == "Drew_Bledsoe"), key=lambda x: -x[1])[:12]:
        print(f"   {n:>8,}  {r}")

if __name__ == "__main__":
    main()
