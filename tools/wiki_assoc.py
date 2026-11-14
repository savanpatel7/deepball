# Player-team association from Wikipedia clickstream (last 12 months of English Wikipedia).
# share(player, team) = clicks into the player's article from that team's pages
#                       / clicks from all of the player's teams' pages
# Clicks from every team's pages count in the total (so careers before our data starts still count); pages naming two teams or rivalries are skipped.
# Active players are damped toward their share of seasons, so a current team doesn't swamp a long past career.
import gzip, re, csv
import pandas as pd

WIKI = "wiki"
_CS = None

def clicks():
    global _CS
    if _CS is None:
        _CS = pd.read_csv(f"{WIKI}/cs.tsv.gz", sep="\t", quoting=csv.QUOTE_NONE, dtype={"referrer": str, "target": str, "clicks": int}, keep_default_na=False)
        _CS = _CS[_CS.referrer != "__ALL__"]
    return _CS

def titles(source):
    wd = pd.read_csv(f"{WIKI}/wd.tsv.gz", sep="\t", dtype=str, keep_default_na=False)
    wd = wd[wd.source == source].drop_duplicates("id")
    return dict(zip(wd.id.str.split("/").str[-1], wd.title))

SKIP = re.compile(r"rivalry|–|_vs\.?_|_trade|Draft|draft|All-Star|Pro_Bowl|Hall_of_Fame", re.I)

RECENT = 2   # seasons back that still count as recent
def shares(played, title_of, team_tokens, active_since, min_clicks=150, damp=0.5):
    """played: DataFrame with columns pid, team, season.  title_of: pid -> article title.
    team_tokens: team -> list of strings that identify that team's pages (e.g. 'Dallas_Cowboys', 'Cowboys').
    Returns {(pid, team): share}."""
    played = played[played.pid.isin(title_of.keys())]
    by_title = {}
    for p in played.pid.unique(): by_title.setdefault(title_of[p], []).append(p)
    cs = clicks(); cs = cs[cs.target.isin(by_title.keys()) & ~cs.referrer.str.contains(SKIP)]
    tok = sorted(((t, team) for team, ts in team_tokens.items() for t in ts), key=lambda x: -len(x[0]))
    rx = re.compile("|".join(r"(?:^|_)" + re.escape(t) + r"(?:_|$|,)" for t, _ in tok))
    lookup = {t: team for t, team in tok}
    def teams_in(ref):
        out = set()
        for m in rx.finditer(ref):
            s = m.group(0).strip("_,")
            if s in lookup: out.add(lookup[s])
        return out
    seasons = played.groupby(["pid", "team"]).season.nunique()
    tlast = played.groupby(["pid", "team"]).season.max(); newest = played.season.max()
    last = played.groupby("pid").season.max()
    myteams = played.groupby("pid").team.apply(set).to_dict()
    tot = {}
    for ref, tgt, n in zip(cs.referrer, cs.target, cs.clicks):
        ts = teams_in(ref)
        if not ts: continue
        if len(ts) != 1: continue                 # a page about two teams says nothing about either
        t = next(iter(ts))
        for p in by_title[tgt]: tot[(p, t)] = tot.get((p, t), 0) + n
    ALL = {}
    for (q, _), v in tot.items(): ALL[q] = ALL.get(q, 0) + v
    out = {}
    for p, teams in myteams.items():
        c = {t: tot.get((p, t), 0) for t in teams}
        s = ALL.get(p, 0)   # all team pages, including teams before our data starts
        if s < min_clicks: continue          # too little traffic to say anything; keep the fame model
        ss = seasons[p]; sn = ss.sum()
        for t in teams:
            # a current or recent stint (Rodgers on the Steelers and Jets) is fresh in fans' minds even when years
            # of old readership point elsewhere, so it gets no "obscure stint" penalty
            if tlast[(p, t)] >= newest - RECENT: continue
            sh = c[t] / s
            if last[p] >= active_since: sh = (1 - damp) * sh + damp * ss.get(t, 0) / sn
            out[(p, t)] = sh
    return out

_V = None
def views(title_of):
    """pid -> total readers of the player's article over the 12 months (all sources)."""
    global _V
    if _V is None:
        v = pd.read_csv(f"{WIKI}/cs.tsv.gz", sep="\t", quoting=csv.QUOTE_NONE, dtype={"referrer": str, "target": str, "clicks": int}, keep_default_na=False)
        _V = v[v.referrer == "__ALL__"].set_index("target").clicks.to_dict()
    return {p: _V.get(t, 0) for p, t in title_of.items()}

FOOT = re.compile(r"F\.C\.|_FC\b|\bFC_|C\.F\.|_CF\b|football|Calcio|Bundesliga|Premier_League|La_Liga|Serie_A|Ligue_1|Major_League_Soccer|UEFA|FIFA|Eredivisie")
def football_views(names):
    """Soccer players have no Wikidata ids here, so match their article by name ('Max Dowman', or 'Rodri (footballer)')
    and count only readers arriving from football pages (club, season, national team, league), which also screens out namesakes."""
    cs = clicks(); cs = cs[cs.referrer.str.contains(FOOT)]
    tot = cs.groupby("target").clicks.sum()
    base = {}
    for t, n in tot.items():
        b = re.sub(r"_\((footballer|soccer|association_football)[^)]*\)$", "", t)
        base[b] = max(base.get(b, 0), n)
    return {p: base.get(str(n).replace(" ", "_"), 0) for p, n in names.items()}
