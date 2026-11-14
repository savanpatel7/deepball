# NBA from Basketball-Reference (sumitrodatta/bball-reference-datasets): every NBA/BAA season since 1947.
# Player ids are Basketball-Reference ids. ESPN box scores (2002+) are mapped onto them for playoff stints,
# single-game feats, birthplaces and jersey numbers.
import re, unicodedata
import numpy as np, pandas as pd

BB = "/home/claude/sumitrodatta/bball-reference-datasets/Data/"
TWO_WORD = {"Trail Blazers"}

def nick(full):
    for t in TWO_WORD:
        if full.endswith(t): return t
    return full.split()[-1]

def tm_of(y, abv, full):
    """Team name used in prompts. Goes by name (the Bullets are not the Wizards), except that two unrelated clubs that shared
    a name are kept apart: the defunct 1947-54 Baltimore Bullets, and the New Orleans Hornets (2002-13, now Pelicans history)."""
    if abv == "BLB": return "Baltimore Bullets (1947-54)"
    if full.startswith("New Orleans") and nick(full) == "Hornets": return "New Orleans Hornets"
    return nick(full)

# what each name covers, shown with every prompt that names the team
TEAM_NOTE = {"Bullets": "1963-97, before they became the Wizards", "Hornets": "Charlotte only", "SuperSonics": "Seattle, before the move to Oklahoma City"}

def norm(n):
    n = "".join(c for c in unicodedata.normalize("NFKD", str(n)) if not unicodedata.combining(c)).lower()
    n = re.sub(r"[.'\-]", "", n); n = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n)
    return " ".join(n.split())

def load():
    tot = pd.read_csv(BB + "Player Totals.csv"); tot = tot[tot.lg.isin(["NBA", "BAA"])]
    pg = pd.read_csv(BB + "Player Per Game.csv"); pg = pg[pg.lg.isin(["NBA", "BAA"])]
    info = pd.read_csv(BB + "Player Season Info.csv"); info = info[info.lg.isin(["NBA", "BAA"])]
    car = pd.read_csv(BB + "Player Career Info.csv")
    ab = pd.read_csv(BB + "Team Abbrev.csv"); ab = ab[ab.lg.isin(["NBA", "BAA"])]
    asg = pd.read_csv(BB + "All-Star Selections.csv"); asg = asg[asg.lg.isin(["NBA", "BAA"])]
    dr = pd.read_csv(BB + "Draft Pick History.csv"); dr = dr[dr.lg.isin(["NBA", "BAA"])]
    full = {(s, a): t.replace("*", "") for s, a, t in zip(ab.season, ab.abbreviation, ab.team)}
    one = tot[~tot.team.str.match(r"^\dTM$|^TOT$")].copy()
    one["full"] = [full.get((s, a)) for s, a in zip(one.season, one.team)]
    one = one[one.full.notna()]; one["tm"] = [tm_of(y, a, f) for y, a, f in zip(one.season, one.team, one.full)]
    return tot, one, pg, info, car, asg, dr, full

def espn_map(D, one, wd_espn, wd_bbref):
    """ESPN athlete id -> Basketball-Reference id: Wikidata first, then unique name + overlapping seasons."""
    t2b = {t: b for b, t in wd_bbref.items()}
    m = {e: t2b[t] for e, t in wd_espn.items() if t in t2b}
    span = one.groupby("player_id").season.agg(["min", "max"])
    bynm = {}
    for b, n in one.drop_duplicates("player_id")[["player_id", "player"]].values: bynm.setdefault(norm(n), []).append(b)
    es = D.groupby("pid").agg(n=("athlete_display_name", "last"), lo=("season", "min"), hi=("season", "max"))
    for e, r in es.iterrows():
        if e in m: continue
        c = [b for b in bynm.get(norm(r.n), []) if span.loc[b, "min"] <= r.hi and span.loc[b, "max"] >= r.lo]
        if len(c) == 1: m[e] = c[0]
    return m

CHAMPS = {1947: "PHW", 1948: "BLB", 1949: "MNL", 1950: "MNL", 1951: "ROC", 1952: "MNL", 1953: "MNL", 1954: "MNL", 1955: "SYR", 1956: "PHW",
          1957: "BOS", 1958: "STL", 1959: "BOS", 1960: "BOS", 1961: "BOS", 1962: "BOS", 1963: "BOS", 1964: "BOS", 1965: "BOS", 1966: "BOS",
          1967: "PHI", 1968: "BOS", 1969: "BOS", 1970: "NYK", 1971: "MIL", 1972: "LAL", 1973: "NYK", 1974: "BOS", 1975: "GSW", 1976: "BOS",
          1977: "POR", 1978: "WSB", 1979: "SEA", 1980: "LAL", 1981: "BOS", 1982: "LAL", 1983: "PHI", 1984: "BOS", 1985: "LAL", 1986: "BOS",
          1987: "LAL", 1988: "LAL", 1989: "DET", 1990: "DET", 1991: "CHI", 1992: "CHI", 1993: "CHI", 1994: "HOU", 1995: "HOU", 1996: "CHI",
          1997: "CHI", 1998: "CHI", 1999: "SAS", 2000: "LAL", 2001: "LAL", 2002: "LAL", 2003: "SAS", 2004: "DET", 2005: "SAS", 2006: "MIA",
          2007: "SAS", 2008: "BOS", 2009: "LAL", 2010: "LAL", 2011: "DAL", 2012: "MIA", 2013: "MIA", 2014: "SAS", 2015: "GSW", 2016: "CLE",
          2017: "GSW", 2018: "GSW", 2019: "TOR", 2020: "LAL", 2021: "MIL", 2022: "GSW", 2023: "DEN", 2024: "BOS", 2025: "OKC", 2026: "NYK"}
