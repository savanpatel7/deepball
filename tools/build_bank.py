# Deep Ball multi-sport prompt bank: MLB (Lahman), NFL (nflverse), NBA (ESPN box scores via sportsdataverse).
# Broad prompts (teams, awards, milestones, colleges, birthplaces) with full answer lists and depth tiers.
# Outputs site/public/data/{players_mlb,players_nfl,players_nba}.json, data/days/N.json, data/calendar.json
import urllib.parse
import pandas as pd, numpy as np, json, os, glob, itertools, unicodedata, re
from collections import Counter

OUT = "site/public/data"; os.makedirs(OUT + "/days", exist_ok=True)
CUTS = [0.14, 0.26, 0.38, 0.50, 0.62, 0.75]
rng = np.random.default_rng(7)

# a prompt must have at least MIN_NAMEABLE answers among each sport's NAMEABLE_K most famous players
MIN_NAMEABLE = 8
MIN_STARS = int(os.environ.get("MIN_STARS", 3)); STARLOG = []
MIN_EASY_STARS = int(os.environ.get("MIN_EASY_STARS", 2)); EASY_VIEWS = 300000; EASY_K = {"nba": 200, "nfl": 250, "mlb": 300}
STAR_VIEWS = {"mlb": int(os.environ.get("SV_US", 250000)), "nfl": int(os.environ.get("SV_US", 250000)), "nba": int(os.environ.get("SV_US", 250000)),
              **{k: int(os.environ.get("SV_SOC", 120000)) for k in ("soc", "epl", "liga", "seriea", "bund", "ligue1", "mls", "ucl")},
              "cfbcoach": 100000}   # college coaches are read far less than pros: Mack Brown draws about 160k a year
STAR_K = {"mlb": 60, "nfl": 60, "nba": 40, "f1": 25, "cfb": 150, "mbb": 120, "intl": 150, "nflcoach": 100, "mlbmgr": 110, "nbacoach": 60, "soccoach": 80, "cfbcoach": 70, "cbbcoach": 140, "soc": 60, "epl": 40, "liga": 40, "seriea": 40, "bund": 40, "ligue1": 40, "mls": 25, "ucl": 50}
NAMEABLE_K = {"mlb": 2500, "nfl": 2000, "nba": 900, "soc": 1000, "epl": 1000, "liga": 1000, "seriea": 1000, "bund": 1000, "ligue1": 1000, "mls": 400, "ucl": 1200, "f1": 100, "cfb": 1500, "mbb": 1500, "intl": 1000,
              "nflcoach": 200, "mlbmgr": 220, "nbacoach": 120, "soccoach": 200, "cfbcoach": 220, "cbbcoach": 220}
DAY_MIX = [0, 0, 0, 1, 1, 1, 2]   # each day: 3 easy, 3 medium, 1 hard, played in that order
MIN_COACH = 8; MIN_NAMEABLE_COACH = 5; MIN_AWARD = 15   # coach prompts: answer lists are short by nature, the nameable gate below does the real work
# player-team association (wiki_assoc.py): for well-known players, a low share of their team-page traffic sets a minimum tier
TEAMKINDS = {"Team season", "Team", "Two teams", "Team decade", "Position", "Draft", "Draft by team", "Country + team", "All-Star", "Hall of Fame", "Champion"}
WELL_KNOWN_VIEWS = 60000   # Wikipedia readers in 12 months; catches stars our stat-based fame underrates (pre-2000 NFL)
SHARE_FLOOR = [(0.06, 5), (0.12, 4), (0.20, 3), (0.30, 2), (9, 0)]   # share under 6% -> Diamond, 12% Gold, 20% Silver, 30% Coal
DBG_NAMES = {"Drew Bledsoe", "Michael Jordan", "Shaquille O'Neal", "Emmitt Smith", "Patrick Ewing", "Ken Griffey", "Pedro Martinez", "Albert Pujols", "Jerry Rice", "Brett Favre", "Aaron Rodgers", "Willie Mays", "Tom Brady", "Joe Montana", "Troy Aikman"}
import wiki_assoc as WA
# coaches and managers collected in Colab (deepball_coaches.py): team-by-season lists, Wikipedia titles, readership
import gzip as _gz
CO = json.load(_gz.open("raw/coaches/c.json.gz")); CO_VSCALE = 365 / CO.get("views_days", 365)   # readership is scaled to a year
def coach_views(sport_key, name_of):
    ti = CO["titles"].get(sport_key, {}); v = CO["views"]
    return {i: v.get(ti.get(n), 0) * CO_VSCALE for i, n in name_of.items() if v.get(ti.get(n), 0)}

STAT_WEIGHT = 2.5
# college programs a casual fan follows; answers for every other program grade one tier deeper
PREMIER = {"cfb": {"Alabama", "Ohio State", "Georgia", "LSU", "Michigan", "Texas", "USC", "Clemson", "Oklahoma", "Notre Dame", "Florida", "Penn State",
                   "Oregon", "Miami", "Florida State", "Auburn", "Tennessee", "Texas A&M"},
           "mbb": {"Duke", "Kentucky", "North Carolina", "Kansas", "UCLA", "Villanova", "Michigan State", "UConn", "Gonzaga", "Arizona", "Louisville",
                   "Indiana", "Syracuse", "Florida"}}
STATKINDS = {"Season", "Career", "Big game", "Caps", "Goals", "Club stalwart", "Team season"}
def at_least(t):
    """'Ran for 12 touchdowns in a season' -> 'Ran for at least 12 touchdowns in a season' (a bare number reads as 'exactly')."""
    if "at least" in t or "or more" in t or "+" in re.sub(r"\(.*?\)", "", t): return t
    t2 = re.sub(r" \.(\d{3})\b", r" at least .\1", t, count=1)          # batting averages: .350
    if t2 != t: return t2
    return re.sub(r"(?<![\w.#-])(\d[\d,]*(?:\.\d+)?)(?![\d-]|th\b|st\b|nd\b|rd\b|s\b)", r"at least \1", t, count=1)

NAMEFIX = {"Jay Rosburg": "Jerry Rosburg", "Tony LaRussa": "Tony La Russa", "A. J. Hinch": "A.J. Hinch", "Klint Kubliak": "Klint Kubiak"}   # source typos and spellings
class Sport:
    def __init__(s, key, label):
        s.key, s.label, s.prompts = key, label, []
    def setup(s, names, first, last, fame):
        # names/first/last/fame: dicts keyed by player id
        names = {p: n.strip() for p, n in names.items() if isinstance(n, str) and n.strip()}   # skip nameless records
        names = {p: NAMEFIX.get(n, n) for p, n in names.items()}
        s.ids = list(names.keys()); s.IDX = {p: i for i, p in enumerate(s.ids)}
        iv=lambda v: 0 if v is None or (isinstance(v,float) and np.isnan(v)) else int(v)
        s.players = [[names[p], iv(first.get(p)), iv(last.get(p))] for p in s.ids]
        f = pd.Series({p: fame.get(p, 0.0) for p in s.ids}); s.FAME = f.to_dict()
        s.GQ = f.rank(ascending=False, pct=True).to_dict()
    def add(s, text, kind, ids, era="", pool=None, who=None, floor=None):
        if kind in STATKINDS: text = at_least(text)
        if pool is not None:   # answers come from another sport's pool (e.g. coaches)
            sp = pool; ids = [i for i in set(ids) if i in sp.IDX]
            s.prompts.append({"t": text, "k": kind, "ids": ids, "era": era, "pool": sp, "who": who, "_floor": floor or {}}); return
        ids = [i for i in set(ids) if i in s.IDX]
        # data ends with 2025; only open-ended prompts need to say so ("in the 2010s" is already closed)
        if s.key == "mlb" and kind != "Teammate" and not re.search(r"\b(19|20)[0-1]0s\b", text): era = (era + ", " if era else "") + "through 2025"
        if s.key == "nba":   # names that meant different teams over the years say which one they mean
            notes = [n_ for t_, n_ in NH.TEAM_NOTE.items() if f"the {t_}" in text]
            if notes: era = "; ".join(notes + ([era] if era else []))
        s.prompts.append({"t": text, "k": kind, "ids": ids, "era": era, "pool": None, "who": who})
    VIEWS = {}; NPOOL = None
    def blend_views(s, w=0.5):
        # Wikipedia readership (12 months) as a second fame signal: a player's readership rank is mapped onto the
        # stat-based fame scale and averaged with it (fixes stars whose stats we lack, e.g. pre-2000 NFL)
        v = {i: s.VIEWS[i] for i in s.ids if s.VIEWS.get(i, 0) > 0}
        if not v: return
        ids = sorted(v, key=lambda i: -v[i]); fs = sorted((s.FAME[i] for i in ids), reverse=True)
        for r, i in enumerate(ids): s.FAME[i] = (1 - w) * s.FAME[i] + w * fs[r]
        s.GQ = pd.Series(s.FAME).rank(ascending=False, pct=True).to_dict()
    def team_share(s, p):
        # for prompts about a team: how strongly each answer is tied to that team in readers' minds (Wikipedia clickstream)
        if p["k"] not in TEAMKINDS or not getattr(s, "ASSOC", None): return None
        txt = p["t"]; teams = []
        for disp in sorted(s.TEAMTXT, key=len, reverse=True):
            if disp in txt: teams.append(s.TEAMTXT[disp]); txt = txt.replace(disp, "")
        if not teams: return None
        out = {}
        for i in p["ids"]:
            v = [s.ASSOC.get((i, t)) for t in teams]
            if all(x is not None for x in v): out[i] = min(v)   # two-team prompts: the weaker link decides
        return out
    def tiers(s, ids, share=None):
        srt = sorted(ids, key=lambda i: -s.FAME[i]); n = len(srt); out = {}
        for r, i in enumerate(srt):
            o = 0.5 * (r / max(1, n - 1)) + 0.5 * s.GQ[i]; out[i] = sum(o >= c for c in CUTS)
        for i in ids:   # a widely read player is never an obscure pull, even at the bottom of an all-star list (Max Dowman, Arsenal 2020s)
            v = s.VIEWS.get(i, 0)
            if v >= 100000: out[i] = min(out[i], 3)
            elif v >= 50000: out[i] = min(out[i], 4)
        if share:   # well-known player with a weak link to this team (Bledsoe on the Cowboys): the stint is a deep pull
            N = s.NPOOL or len(s.ids); K = NAMEABLE_K.get(s.key, 1500)
            for i in ids:
                if i in share and (s.GQ[i] * N <= K or s.VIEWS.get(i, 0) >= WELL_KNOWN_VIEWS):
                    out[i] = max(out[i], next(t for lim, t in SHARE_FLOOR if share[i] < lim))
        if os.environ.get("DBGT") and share:
            for i in ids:
                if s.players[s.IDX[i]][0] in DBG_NAMES: print("   DBG", s.key, s.players[s.IDX[i]][0], "share", round(share.get(i, -1), 3), "tier", out[i])
        return out
    def bank(s, lo=15, hi=1600):
        seen = set(); out = []
        for p in s.prompts:
            if os.environ.get("DBGK") and p["k"] == os.environ["DBGK"]: print(" DBGK", s.key, p["t"], len(p["ids"]))
            n = len(p["ids"]); key = (frozenset(p["ids"]), p["t"][:12])
            if (MIN_COACH if p.get("pool") is not None else MIN_AWARD if p["k"] == "Award" else lo) <= n <= hi and key not in seen:   # a team has only so many coaches
                sp = p.get("pool") or s
                seen.add(key); sh = None if p.get("pool") is not None else s.team_share(p)
                if os.environ.get("DBGT") and sh: print(" DBGP", s.key, p["t"])
                t = sp.tiers(p["ids"], sh)
                for i, v in p.get("_floor", {}).items():   # a famous name's brief fill-in stint (Mattingly, 2 games for the Yankees) is a deep pull
                    if i in t: t[i] = max(t[i], v)
                for i in p.get("_xfer", ()): t[i] = max(t[i], 3)   # transferred away (Kyler Murray, Texas A&M): at least Silver
                if s.key in PREMIER and p["k"] in ("School", "Pros"):
                    school = re.sub(r" and made the (NFL|NBA)$", "", p["t"][len("Played for "):])
                    if school not in PREMIER[s.key]: t = {i: min(6, v + 1) for i, v in t.items()}   # outside the blue bloods, every name is a deeper pull
                q = {"t": p["t"], "k": p["k"], "s": s.key, "era": p["era"], "a": sorted([[sp.IDX[i], int(t[i])] for i in p["ids"]])}
                if p.get("pool") is not None: q["p"] = sp.key
                if p.get("who"): q["w"] = p["who"]
                q["h"] = [sp.IDX[i] for i in sorted(p["ids"], key=lambda i: (i in p.get("_floor", {}), -sp.FAME[i]))[:3]]   # the three best-known answers, shown when time runs out
                # difficulty gate: count answers a regular fan could name (inside the sport's top-K most famous players)
                nm = sum(sp.GQ[i] * (sp.NPOOL or len(sp.ids)) <= NAMEABLE_K.get(sp.key, 1500) for i in p["ids"])
                if nm < (MIN_NAMEABLE_COACH if p.get("pool") is not None else MIN_NAMEABLE): continue
                # household names: everyone should know at least a few answers (judged by today's readership, not career stats)
                N_ = sp.NPOOL or len(sp.ids); sv = STAR_VIEWS.get(sp.key, 250000) if sp.VIEWS else None
                stars = sum(1 for i in p["ids"] if (sv is not None and sp.VIEWS.get(i, 0) >= sv) or sp.GQ[i] * N_ <= STAR_K.get(sp.key, 120))
                STARLOG.append((s.key, p["t"], stars))
                if stars < MIN_STARS: continue
                # the easy end has to be easy: at least 2 of the Dirt/Stone answers must be household names
                # (Jazz + Raptors: the "common" answers were Kelly Olynyk and Kyle Anderson)
                if sp.key in EASY_K:   # pros: a real household name (Joe Johnson yes, Kelly Olynyk no)
                    isstar = lambda i: sp.VIEWS.get(i, 0) >= EASY_VIEWS or sp.GQ[i] * N_ <= EASY_K[sp.key]
                else:
                    isstar = lambda i: (sv is not None and sp.VIEWS.get(i, 0) >= sv) or sp.GQ[i] * N_ <= STAR_K.get(sp.key, 120)
                easy_stars = sum(1 for i in p["ids"] if t[i] <= 1 and isstar(i))
                STARLOG.append((s.key, p["t"], -easy_stars))
                if easy_stars < MIN_EASY_STARS: continue
                q["_d"] = 0 if nm >= 25 else 1 if nm >= 12 else 2   # 0 easy, 1 medium, 2 hard
                out.append(q)
        print(s.key, len(s.prompts), "candidates ->", len(out), "difficulty", Counter(p["_d"] for p in out), Counter(p["k"] for p in out))
        return out

def teammates(sport, df, pid, team, year, n_anchor, min_last, era="", min_seasons=5, label=lambda n: f"Was a teammate of {n}", ok=lambda p: True):
    """df has one row per player-team-season. Anchors = most famous players with long careers."""
    df = df[[pid, team, year]].dropna().drop_duplicates()
    span = df.groupby(pid)[year].agg(["min", "max", "nunique"])
    cand = [p for p in span.index if span.loc[p, "nunique"] >= min_seasons and span.loc[p, "max"] >= min_last and p in sport.FAME and ok(p)]
    cand = sorted(cand, key=lambda p: -sport.FAME[p])[:n_anchor]
    if os.environ.get("DBG"): print("teammates", sport.key, len(cand), [sport.players[sport.IDX[a]][0] for a in cand[:5]])
    seen_names = set()
    for a in cand:
        nm0 = sport.players[sport.IDX[a]][0]
        if nm0 in seen_names: continue      # two players with the same name would make an ambiguous prompt
        seen_names.add(nm0)
        stints = df[df[pid] == a][[team, year]]
        mates = df.merge(stints, on=[team, year])[pid]
        # the anchor's own career already sets the years; only say where the data stops if he is still playing
        # or where it starts, if his career may reach back before our data (Robben before 2005)
        live = span.loc[a, "max"] >= df[year].max(); early = span.loc[a, "min"] <= df[year].min()
        e_ = [f"since {int(df[year].min())}"] if early else []
        if live and sport.key == "mlb": e_.append(f"through {int(df[year].max())}")
        sport.add(label(sport.players[sport.IDX[a]][0]), "Teammate", [m for m in mates if m != a], era=", ".join(e_))
def team_decades(sport, df, pid, team, year, names, decades, era_fmt=lambda d: ""):
    for t in names:
        for d in decades:
            x = df[(df[team] == t) & (df[year] >= d) & (df[year] <= d + 9)]
            sport.add(f"Played for {names[t]} in the {d}s", "Team decade", x[pid], era=era_fmt(d))

# ======================= MLB =======================
L = {t: pd.read_pickle(f"{t}.pkl") for t in ["People", "Batting", "Pitching", "AwardsPlayers", "AllstarFull",
     "Teams", "Appearances", "HallOfFame", "AwardsSharePlayers", "CollegePlaying", "Schools"]}
P, B, PI, AW, AS, T, AP, HOF, ASH, CP, SC = (L[k] for k in ["People", "Batting", "Pitching", "AwardsPlayers",
     "AllstarFull", "Teams", "Appearances", "HallOfFame", "AwardsSharePlayers", "CollegePlaying", "Schools"])
P["name"] = (P.nameFirst.fillna("") + " " + P.nameLast.fillna("")).str.strip()
P["first"] = pd.to_numeric(P.debut.astype(str).str[:4], errors="coerce")
P["last"] = pd.to_numeric(P.finalGame.astype(str).str[:4], errors="coerce")
P = P[P["first"].notna() & (P.name != "")]
cur = T.sort_values("yearID").groupby("franchID").last()["name"].to_dict()
def nick(n):
    if "Angels" in n: return "Angels"
    for two in ("Red Sox", "White Sox", "Blue Jays"):
        if n.endswith(two): return two
    return n.split()[-1]
NICK = {f: nick(n) for f, n in cur.items()}
T["ok"] = [NICK[f] in n or (f == "CLE" and "Indians" in n) for n, f in zip(T.name, T.franchID)]   # "Los Angeles Angels of Anaheim" still counts as the Angels
FR = T[T.ok].set_index(["yearID", "teamID"])["franchID"].to_dict()
def fr(df):
    df = df.copy(); df["fr"] = [FR.get((y, t)) for y, t in zip(df.yearID, df.teamID)]; return df
active = sorted(T[T.yearID == 2025].franchID.unique())
g = AP.groupby("playerID").G_all.sum(); asg = AS.drop_duplicates(["playerID", "yearID"]).groupby("playerID").size()
aw = AW.groupby(["playerID", "awardID"]).size().unstack(fill_value=0)
ash = ASH.assign(s=ASH.pointsWon / ASH.pointsMax).groupby("playerID").s.sum()
hof = set(HOF[(HOF.inducted == "Y") & (HOF.category == "Player")].playerID)
ch = B.groupby("playerID").H.sum(); chr_ = B.groupby("playerID").HR.sum(); cw = PI.groupby("playerID").W.sum()
fm = pd.DataFrame(index=P.playerID)
fm["g"] = g; fm["as"] = asg; fm["ash"] = ash
for c, a in [("mvp", "Most Valuable Player"), ("cy", "Cy Young Award"), ("roy", "Rookie of the Year"), ("gg", "Gold Glove"), ("ss", "Silver Slugger"), ("wsmvp", "World Series MVP")]:
    fm[c] = aw[a] if a in aw.columns else 0
fm = fm.fillna(0); fm["hof"] = fm.index.isin(hof).astype(int)
fm["mil"] = ((ch.reindex(fm.index).fillna(0) >= 3000) | (chr_.reindex(fm.index).fillna(0) >= 500) | (cw.reindex(fm.index).fillna(0) >= 300)).astype(int)
rec = np.clip((P.set_index("playerID")["last"].reindex(fm.index).fillna(1900) - 1950) / 75, 0, 1)
fm["score"] = (np.log1p(fm.g) + .6 * np.minimum(fm["as"], 15) + 2 * fm.ash + 6 * fm.hof + 2.5 * fm.mvp + 2 * fm.cy + fm.roy + .3 * fm.gg + .2 * fm.ss + 1.5 * fm.wsmvp + 3 * fm.mil + 2 * rec)
mlb = Sport("mlb", "MLB")
mlb.setup(P.set_index("playerID").name.to_dict(), P.set_index("playerID")["first"].to_dict(), P.set_index("playerID")["last"].to_dict(), fm.score.to_dict())
# "Played for" = appeared in a regular-season (Appearances) or postseason game (Batting/Pitching/FieldingPost) for that team
import pyreadr
_post = pd.concat([pyreadr.read_r(f"raw/Lahman/data/{t}.RData")[t][["yearID", "teamID", "playerID"]] for t in ["BattingPost", "PitchingPost", "FieldingPost"]]).drop_duplicates()
_post = _post.merge(AP[["yearID", "teamID", "playerID"]], how="left", indicator=True); _post = _post[_post["_merge"] == "left_only"].drop(columns="_merge")
print("mlb: postseason-only team appearances added:", len(_post))
ap = fr(pd.concat([AP, _post.assign(G_all=0)], ignore_index=True)); byp = ap.groupby("playerID").fr.apply(lambda s: set(s.dropna()))
TN = {f: "the " + NICK[f] for f in active}; TN["CLE"] = "the Indians/Guardians"
for f in active: mlb.add(f"Played for {TN[f]}", "Team", ap[ap.fr == f].playerID)
_bb = P.set_index("playerID").bbrefID.dropna().to_dict(); _wt = WA.titles("bbref_mlb")
_tok = {f: sorted({n.replace(" ", "_") for n in T[(T.franchID == f) & T.ok].name}) for f in active}
mlb.ASSOC = WA.shares(ap.rename(columns={"playerID": "pid", "fr": "team", "yearID": "season"})[["pid", "team", "season"]].dropna(),
                      _mt := {p: _wt[b] for p, b in _bb.items() if b in _wt}, _tok, active_since=2025); mlb.VIEWS = WA.views(_mt)
mlb.TEAMTXT = {TN[f]: f for f in active}; print("mlb association pairs:", len(mlb.ASSOC))
# position + team (fielded at least 10 games there for that franchise in a season)
_apf = fr(AP)
for col, lab in [("G_c", "catcher"), ("G_ss", "shortstop")]:
    for f in active: mlb.add(f"Played {lab} for {TN[f]}", "Position", _apf[(_apf.fr == f) & (_apf[col] >= 10)].playerID)
# height
_ht = P.set_index("playerID").height
mlb.add("Was 6 feet 7 inches or taller", "Height", _ht[_ht >= 79].index)
mlb.add("Was 5 feet 7 inches or shorter", "Height", _ht[(_ht <= 67) & (P.set_index("playerID")["last"] >= 1950)].index, era="since 1950")
pairs = []
for a, b in itertools.combinations(active, 2):
    ids = byp[byp.apply(lambda s: a in s and b in s)].index
    if 40 <= len(ids) <= 400: pairs.append((a, b, ids))
for k in rng.permutation(len(pairs))[:120]:
    a, b, ids = pairs[k]; mlb.add(f"Played for both {TN[a]} and {TN[b]}", "Two teams", ids)
for a_id, nm in [("Most Valuable Player", "an MVP award"), ("Cy Young Award", "a Cy Young Award"), ("Rookie of the Year", "Rookie of the Year"),
                 ("World Series MVP", "World Series MVP"), ("Gold Glove", "a Gold Glove"), ("Silver Slugger", "a Silver Slugger"),
                 ("Comeback Player of the Year", "Comeback Player of the Year")]:
    mlb.add(f"Won {nm}", "Award", AW[AW.awardID == a_id].playerID)
asf = fr(AS)
for f in active: mlb.add(f"Made an All-Star team as a member of {TN[f]}", "All-Star", asf[asf.fr == f].playerID)
mlb.add("Is in the Hall of Fame", "Hall of Fame", list(hof))
hp = fr(AP[AP.playerID.isin(hof)])
for f in active: mlb.add(f"Is a Hall of Famer and played for {TN[f]}", "Hall of Fame", hp[hp.fr == f].playerID)
bat = B.groupby(["playerID", "yearID"])[["AB", "H", "HR", "RBI", "SB", "R", "X2B", "X3B", "BB"]].sum().reset_index(); bat["AVG"] = bat.H / bat.AB.replace(0, np.nan)
pit = PI.groupby(["playerID", "yearID"])[["W", "SV", "SO", "ER", "IPouts"]].sum().reset_index(); pit["ERA"] = 27 * pit.ER / pit.IPouts.replace(0, np.nan)
cab = B.groupby("playerID")[["AB", "H"]].sum(); csb = B.groupby("playerID").SB.sum(); cso = PI.groupby("playerID").SO.sum(); csv_ = PI.groupby("playerID").SV.sum()
for ids, t in [(ch[ch >= 3000].index, "Got 3,000 career hits"), (ch[ch >= 2500].index, "Got 2,500 career hits"), (chr_[chr_ >= 500].index, "Hit 500 career home runs"),
               (chr_[chr_ >= 400].index, "Hit 400 career home runs"), (chr_[chr_ >= 300].index, "Hit 300 career home runs"), (cw[cw >= 300].index, "Won 300 career games"),
               (cw[cw >= 200].index, "Won 200 career games"), (cso[cso >= 3000].index, "Struck out 3,000 batters"), (cso[cso >= 2000].index, "Struck out 2,000 batters"),
               (csv_[csv_ >= 300].index, "Saved 300 games"), (csb[csb >= 500].index, "Stole 500 bases"),
               (cab[(cab.AB >= 4000) & (cab.H / cab.AB >= .310)].index, "Had a .310+ career batting average (4,000+ at-bats)")]:
    mlb.add(t, "Career", ids)
for ids, t in [(bat[bat.HR >= 40].playerID, "Hit 40 home runs in a season"), (bat[bat.HR >= 50].playerID, "Hit 50 home runs in a season"),
               (bat[bat.H >= 200].playerID, "Had 200 hits in a season"), (bat[bat.SB >= 50].playerID, "Stole 50 bases in a season"),
               (bat[bat.RBI >= 130].playerID, "Drove in 130 runs in a season"), (bat[(bat.AB >= 400) & (bat.AVG >= .350)].playerID, "Hit .350 in a season"),
               (bat[(bat.HR >= 30) & (bat.SB >= 30)].playerID, "Had a 30-homer, 30-steal season"),
               (pit[pit.W >= 20].playerID, "Won 20 games in a season"), (pit[pit.SV >= 40].playerID, "Saved 40 games in a season"),
               (pit[pit.SO >= 250].playerID, "Struck out 250 batters in a season"),
               (bat[bat.HR >= 30].playerID, "Hit 30 home runs in a season"), (bat[bat.HR >= 45].playerID, "Hit 45 home runs in a season"),
               (bat[(bat.AB >= 400) & (bat.AVG >= .330)].playerID, "Hit .330 in a season"), (bat[bat.R >= 120].playerID, "Scored 120 runs in a season"),
               (bat[bat["X2B"] >= 45].playerID, "Hit 45 doubles in a season"), (bat[bat["X3B"] >= 12].playerID, "Hit 12 triples in a season"),
               (bat[bat.BB >= 110].playerID, "Drew 110 walks in a season"), (bat[bat.RBI >= 100].playerID, "Drove in 100 runs in a season"),
               (bat[bat.SB >= 40].playerID, "Stole 40 bases in a season"), (pit[pit.SO >= 200].playerID, "Struck out 200 batters in a season"),
               (pit[pit.SV >= 30].playerID, "Saved 30 games in a season"), (pit[pit.W >= 18].playerID, "Won 18 games in a season"),
               (pit[(pit.IPouts >= 450) & (pit.ERA < 2.5)].playerID, "Had an ERA under 2.50 in a season (150+ innings)")]:
    mlb.add(t, "Season", ids)
crbi = B.groupby("playerID").RBI.sum(); cw2 = PI.groupby("playerID").W.sum()
for ids, t in [(ch[ch >= 2000].index, "Got 2,000 career hits"), (crbi[crbi >= 1500].index, "Drove in 1,500 career runs"), (chr_[chr_ >= 250].index, "Hit 250 career home runs"),
               (csb[csb >= 300].index, "Stole 300 career bases"), (cw2[cw2 >= 150].index, "Won 150 career games"), (csv_[csv_ >= 200].index, "Saved 200 career games"),
               (cso[cso >= 2500].index, "Struck out 2,500 career batters")]:
    mlb.add(t, "Career", ids)
# single-season feats for one franchise
_bs = fr(B.copy()); _bs = _bs.groupby(["playerID", "yearID", "fr"])[["AB", "H", "HR", "SB"]].sum().reset_index()
_ps = fr(PI.copy()); _ps = _ps.groupby(["playerID", "yearID", "fr"])[["W", "SO"]].sum().reset_index()
for f in active:
    b_, p_ = _bs[_bs.fr == f], _ps[_ps.fr == f]
    mlb.add(f"Hit 30 home runs in a season for {TN[f]}", "Team season", b_[b_.HR >= 30].playerID)
    mlb.add(f"Hit .300 in a season for {TN[f]} (400+ at-bats)", "Team season", b_[(b_.AB >= 400) & (b_.H / b_.AB >= .300)].playerID)
    mlb.add(f"Stole 30 bases in a season for {TN[f]}", "Team season", b_[b_.SB >= 30].playerID)
    mlb.add(f"Won 15 games in a season for {TN[f]}", "Team season", p_[p_.W >= 15].playerID)
    mlb.add(f"Struck out 200 batters in a season for {TN[f]}", "Team season", p_[p_.SO >= 200].playerID)
for c, lab in [("Japan", "Japan"), ("Cuba", "Cuba"), ("CAN", "Canada"), ("P.R.", "Puerto Rico"), ("México", "Mexico"), ("South Korea", "South Korea"),
               ("Panama", "Panama"), ("Australia", "Australia"), ("Curacao", "Curacao"), ("Colombia", "Colombia"), ("Nicaragua", "Nicaragua"),
               ("Venezuela", "Venezuela"), ("D.R.", "the Dominican Republic"), ("Germany", "Germany"), ("Ireland", "Ireland")]:
    mlb.add(f"Was born in {lab}", "Birthplace", P[P.birthCountry == c].playerID)
# nationality combos: country + team, country + All-Star, country in the modern game
CTRY = {"D.R.": "the Dominican Republic", "Venezuela": "Venezuela", "P.R.": "Puerto Rico", "Cuba": "Cuba", "Japan": "Japan", "México": "Mexico", "CAN": "Canada", "Panama": "Panama"}
for c, lab in CTRY.items():
    ids = set(P[P.birthCountry == c].playerID)
    teams_ok = [f for f in active if ap[(ap.fr == f) & ap.playerID.isin(ids)].playerID.nunique() >= 30]
    for k in range(len(teams_ok)):                      # every team with 30+ players from this country
        f = teams_ok[k]; mlb.add(f"Was born in {lab} and played for {TN[f]}", "Country + team", ap[(ap.fr == f) & ap.playerID.isin(ids)].playerID)
    mlb.add(f"Was born in {lab} and made an All-Star team", "Country + All-Star", AS[AS.playerID.isin(ids)].playerID)
    mlb.add(f"Was born in {lab} and played in the majors", "Birthplace", ap[(ap.yearID >= 2000) & ap.playerID.isin(ids)].playerID, era="since 2000")
mlb.add("Was born in Asia", "Birthplace", P[P.birthCountry.isin(["Japan", "South Korea", "Taiwan"])].playerID)
mlb.add("Was born outside the U.S. and made an All-Star team", "Country + All-Star", AS[AS.playerID.isin(set(P[P.birthCountry.notna() & (P.birthCountry != "USA")].playerID))].playerID, era="since 1990")
ST = {"HI": "Hawaii", "AK": "Alaska", "OR": "Oregon", "NV": "Nevada", "AZ": "Arizona", "CO": "Colorado", "UT": "Utah", "NM": "New Mexico",
      "WA": "Washington", "MN": "Minnesota", "WI": "Wisconsin", "IA": "Iowa", "KS": "Kansas", "NE": "Nebraska", "OK": "Oklahoma", "LA": "Louisiana",
      "MS": "Mississippi", "AL": "Alabama", "TN": "Tennessee", "KY": "Kentucky", "IN": "Indiana", "MI": "Michigan", "CT": "Connecticut",
      "NJ": "New Jersey", "MD": "Maryland", "VA": "Virginia", "NC": "North Carolina", "SC": "South Carolina", "GA": "Georgia", "AR": "Arkansas",
      "FL": "Florida", "TX": "Texas", "OH": "Ohio", "MA": "Massachusetts", "MO": "Missouri", "WV": "West Virginia", "ME": "Maine", "DE": "Delaware",
      "RI": "Rhode Island", "NH": "New Hampshire", "VT": "Vermont", "ID": "Idaho", "MT": "Montana", "SD": "South Dakota", "ND": "North Dakota", "WY": "Wyoming"}
for st, lab in ST.items():
    mlb.add(f"Was born in {lab}", "Birthplace", P[(P.birthCountry == "USA") & (P.birthState == st) & (P["last"] >= 1960)].playerID, era="since 1960")
ws = T[T.WSWin == "Y"][["yearID", "teamID", "franchID"]]
wsp = AP.merge(ws, on=["yearID", "teamID"]); wsp = wsp[wsp.G_all >= 10]
for f in active:
    x = wsp[(wsp.franchID == f).values & np.array([FR.get((y, t)) == f for y, t in zip(wsp.yearID, wsp.teamID)])]
    mlb.add(f"Won a World Series with {TN[f]}", "Champion", x.playerID)
seasons = AP.groupby("playerID").yearID.nunique(); mlb.add("Played 20 or more seasons", "Career", seasons[seasons >= 20].index)
nfr = ap.groupby("playerID").fr.nunique(); mlb.add("Played for 9 or more franchises", "Journeyman", nfr[nfr >= 9].index)
apm = ap[ap.fr.notna()]
teammates(mlb, apm, "playerID", "fr", "yearID", 45, 1985)
MG = pd.read_pickle("Managers.pkl"); MG = fr(MG); MG = MG[MG.fr.notna()]
# (manager prompts answer from their own pool now, see "MLB managers" below)
mspan = MG.groupby("playerID").yearID.nunique(); bigm = sorted([m for m in mspan.index if mspan[m] >= 10 and m in mlb.FAME], key=lambda m: -mspan[m])[:30]
mgr_seasons = MG[["playerID", "yearID", "teamID"]].rename(columns={"playerID": "mgr"})
for m in bigm:
    stints = mgr_seasons[mgr_seasons.mgr == m][["yearID", "teamID"]]
    pl = AP.merge(stints, on=["yearID", "teamID"]).playerID
    mlb.add(f"Played for manager {mlb.players[mlb.IDX[m]][0]}", "Played for manager", [x for x in pl if x != m])
team_decades(mlb, apm, "playerID", "fr", "yearID", TN, [1970, 1980, 1990, 2000, 2010])
cps = CP.merge(SC, on="schoolID"); topc = cps.groupby("schoolID").playerID.nunique().sort_values(ascending=False).head(30).index
for sid in topc:
    mlb.add(f"Played college baseball at {SC.set_index('schoolID').name_full[sid]}", "College", cps[cps.schoolID == sid].playerID)

# ----------------------- MLB managers (Lahman, every season; interim managers count) -----------------------
MG = fr(pd.read_pickle("Managers.pkl"))
_am = pyreadr.read_r("raw/Lahman/data/AwardsManagers.RData")["AwardsManagers"]
_moy = _am[_am.awardID == "BBWAA Manager of the Year"]
_wsm = MG.merge(ws[["yearID", "teamID"]], on=["yearID", "teamID"])
_wsm = _wsm.sort_values("G").groupby(["yearID", "teamID"]).tail(1)          # the manager who finished the season gets the ring
_hofm = set(HOF[(HOF.inducted == "Y") & (HOF.category == "Manager")].playerID)
_mg = MG.groupby("playerID").agg(G=("G", "sum"), W=("W", "sum"), y0=("yearID", "min"), y1=("yearID", "max"))
_mf = (np.log1p(_mg.G) + 2.5 * _wsm.playerID.value_counts().reindex(_mg.index).fillna(0) + 1.2 * _moy.playerID.value_counts().reindex(_mg.index).fillna(0)
       + 4 * _mg.index.isin(_hofm) + 3 * np.clip((_mg.y1 - 1950) / 75, 0, 1))
_pn = P.set_index("playerID").name.to_dict()
_pn.update(L["People"].assign(n=(L["People"].nameFirst.fillna("") + " " + L["People"].nameLast.fillna("")).str.strip()).set_index("playerID").n.to_dict())
mlbm = Sport("mlbmgr", "MLB managers")
mlbm.setup({m: _pn.get(m, "") for m in _mg.index}, _mg.y0.to_dict(), _mg.y1.to_dict(), _mf.to_dict())
_mt2 = {m: _wt[b] for m, b in L["People"].set_index("playerID").bbrefID.dropna().to_dict().items() if b in _wt and m in mlbm.IDX}
_mv = coach_views("mlb", {m: mlbm.players[mlbm.IDX[m]][0] for m in mlbm.ids}); _mv2 = WA.views(_mt2)
mlbm.VIEWS = {m: max(_mv.get(m, 0), _mv2.get(m, 0)) for m in set(_mv) | set(_mv2)}; mlbm.blend_views()
MW = dict(pool=mlbm, who="AN MLB MANAGER")
for f in active:
    _x = MG[(MG.fr == f) & (MG.yearID >= 1970)]; _g = _x.groupby("playerID").G.sum()
    mlb.add(f"Managed {TN[f]}", "Coach team", _x.playerID, era="since 1970", floor={m: 5 for m in _g[_g < 20].index}, **MW)
mlb.add("Won a World Series as a manager", "Coach title", _wsm[_wsm.yearID >= 1950].playerID, era="since 1950", **MW)
mlb.add("Won Manager of the Year", "Coach award", _moy.playerID, era="since 1983", **MW)
for d in (1970, 1980, 1990, 2000, 2010, 2020):
    mlb.add(f"Managed in the {d}s", "Coach", MG[(MG.yearID >= d) & (MG.yearID <= d + 9)].playerID, era="through 2025" if d == 2020 else "", **MW)
_mnf = MG[MG.yearID >= 1970].groupby("playerID").fr.nunique()
mlb.add("Managed 3 or more teams", "Coach", _mnf[_mnf >= 3].index, era="since 1970", **MW)
mlb.add("Won at least 1,000 games as a manager", "Coach", _mg[_mg.W >= 1000].index, **MW)
_lp = ap.groupby(["playerID", "fr"]).yearID.max().rename("lastp").reset_index()
_pm = MG[MG.yearID >= 1960].merge(_lp, on=["playerID", "fr"]); _pm = _pm[_pm.yearID > _pm.lastp]
mlb.add("Played for and later managed the same team", "Coach", _pm.playerID, era="since 1960", **MW)

# ======================= NFL =======================
R = pd.read_pickle("nfl_rosters.pkl"); R = R[R.full_name.notna()]
R["nk"] = R.full_name + "|" + R.college.fillna("")
known = R[R.gsis_id.notna()].drop_duplicates("nk").set_index("nk").gsis_id.to_dict()   # link early seasons (no gsis id) to the same player later
R["pid"] = [g if isinstance(g, str) else known.get(k, "n:" + k) for g, k in zip(R.gsis_id, R.nk)]
def nfl_fr(team, y):
    if team in ("ARI", "ARZ", "PHO") or (team == "STL" and y <= 1987): return "ARI"
    if team == "BAL": return "IND" if y <= 1983 else "BAL"
    if team == "BLT": return "BAL"
    if team in ("CLE", "CLV"): return "CLE"
    if team in ("HOU", "HST"): return "TEN" if y <= 1996 else "HOU"
    if team in ("LA", "RAM", "SL") or (team == "STL" and y >= 1995): return "LAR"
    if team in ("OAK", "RAI", "LV"): return "LV"
    if team in ("SD", "LAC"): return "LAC"
    if team == "BOS": return "NE"
    return team
R["fr"] = [nfl_fr(t, y) for t, y in zip(R.team, R.season)]
# "Played for" = appeared in at least one regular-season or postseason game for that team.
#  2012+: snap counts (any offense/defense/special-teams snap, REG or POST)
#  2002-2011: weekly rosters, active (ACT) on game day for at least one REG/POST week
#  1999+: also anyone with a stat line for the team
#  before 2002: season rosters only - keep active/traded players, drop injured reserve, cut, practice squad
import glob as _g
_W = pd.concat([pd.read_csv(f, usecols=["season", "team", "status", "gsis_id", "pfr_id", "full_name"], low_memory=False) for f in sorted(_g.glob("raw/nfl/weekly/roster_weekly_*.csv"))])
_pl = pd.read_csv("raw/nfl/players.csv", low_memory=False)
_pcols = [c for c in _pl.columns if c in ("pfr_id", "gsis_id")]
_pfr = pd.concat([_W[["pfr_id", "gsis_id"]], _pl[_pcols] if len(_pcols) == 2 else _W[["pfr_id", "gsis_id"]],
                  DP[["pfr_player_id", "gsis_id"]].rename(columns={"pfr_player_id": "pfr_id"}) if "DP" in dir() else pd.read_csv("raw/nfl/draft_picks.csv", usecols=["pfr_player_id", "gsis_id"]).rename(columns={"pfr_player_id": "pfr_id"})]
                 ).dropna().drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
_nm = {}                                                                     # fallback: same name on the same franchise that season
for g, n, t, y in zip(_W.gsis_id, _W.full_name if "full_name" in _W else [None]*len(_W), _W.team, _W.season):
    if isinstance(g, str) and isinstance(n, str): _nm[(n, nfl_fr(t, y), y)] = g
APPEAR = set()
_a = _W[(_W.status == "ACT") & (_W.season < 2012) & _W.gsis_id.notna()]
APPEAR |= {(g, nfl_fr(t, y), y) for g, t, y in zip(_a.gsis_id, _a.team, _a.season)}
_S = pd.concat([pd.read_csv(f, usecols=["season", "team", "player", "pfr_player_id", "offense_snaps", "defense_snaps", "st_snaps"]) for f in sorted(_g.glob("raw/nfl/snaps/snap_counts_*.csv"))])
_S = _S[(_S.offense_snaps.fillna(0) + _S.defense_snaps.fillna(0) + _S.st_snaps.fillna(0)) > 0]; _S["g"] = _S.pfr_player_id.map(_pfr)
_S["g"] = [g if isinstance(g, str) else _nm.get((n, nfl_fr(t, y), y)) for g, n, t, y in zip(_S.g, _S.player, _S.team, _S.season)]
print("nfl snaps linked:", round(_S.g.notna().mean() * 100, 1), "%")
APPEAR |= {(g, nfl_fr(t, y), y) for g, t, y in zip(_S.g, _S.team, _S.season) if isinstance(g, str)}
_PSa = pd.read_csv("raw/nfl/player_stats_season.csv", usecols=["season", "player_id", "recent_team"], low_memory=False)
APPEAR |= {(g, nfl_fr(t, y), y) for g, t, y in zip(_PSa.player_id, _PSa.recent_team, _PSa.season) if isinstance(g, str) and isinstance(t, str)}
_old = pd.concat([pd.read_csv(f"raw/nfl/roster_{y}.csv", usecols=["season", "team", "full_name", "status"], low_memory=False) for y in range(1970, 2002) if os.path.exists(f"raw/nfl/roster_{y}.csv")])
_oldok = {(n, t, y) for n, t, y, st in zip(_old.full_name, _old.team, _old.season, _old.status) if not isinstance(st, str) or st in ("ACT", "TRD", "TRC", "TRT")}
_n0 = len(R)
_keep = [((n, t, y) in _oldok) if y < 2002 else ((g, f, y) in APPEAR) for n, t, y, g, f in zip(R.full_name, R.team, R.season, R.gsis_id, R.fr)]
R = R[_keep].copy()
print(f"nfl: kept {len(R)} of {_n0} roster rows as real game appearances")
NFLN = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
        "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers", "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
        "LAR": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
        "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans/Oilers", "WAS": "Commanders"}
NT = {k: "the " + v for k, v in NFLN.items()}   # WAS -> "the Commanders"
DP = pd.read_csv("raw/nfl/draft_picks.csv"); PS = pd.read_csv("raw/nfl/player_stats_season.csv", low_memory=False)
PS = PS[PS.season_type == "REG"]
for y in (2025, 2026):   # newer seasons are published in a separate file format
    f = f"raw/nfl/stats_reg_{y}.csv"
    if os.path.exists(f):
        n = pd.read_csv(f, low_memory=False); PS = pd.concat([PS, n[[c for c in PS.columns if c in n.columns]]], ignore_index=True)
names = R.drop_duplicates("pid", keep="last").set_index("pid").full_name.to_dict()
first = R.groupby("pid").season.min().to_dict(); last = R.groupby("pid").season.max().to_dict()
nseas = R.groupby("pid").season.nunique()
dpk = DP[DP.gsis_id.notna()].drop_duplicates("gsis_id").set_index("gsis_id")
car = PS.groupby("player_id")[["passing_yards", "rushing_yards", "receiving_yards", "passing_tds", "rushing_tds", "receiving_tds"]].sum()
fame = {}
for p in names:
    f = np.log1p(nseas.get(p, 0)) * 1.4 + 2 * np.clip((last.get(p, 1970) - 1975) / 50, 0, 1)
    if p in dpk.index:
        d = dpk.loc[p]; f += .8 * min(d.probowls if pd.notna(d.probowls) else 0, 12) + 1.5 * min(d.allpro if pd.notna(d.allpro) else 0, 8) + 6 * (d.hof == True) + (d.car_av if pd.notna(d.car_av) else 0) / 25
        if d["round"] == 1: f += .8
    if p in car.index:
        c = car.loc[p]; f += c.passing_yards / 9000 + c.rushing_yards / 3500 + c.receiving_yards / 3500 + (c.passing_tds + 3 * (c.rushing_tds + c.receiving_tds)) / 60
    fame[p] = f
nfl = Sport("nfl", "NFL"); nfl.setup(names, first, last, fame)
byp = R.groupby("pid").fr.apply(set)
teams = sorted(NFLN)
for f in teams: nfl.add(f"Played for {NT[f]}", "Team", R[R.fr == f].pid, era="since 1970")
_wt = WA.titles("pfr"); _g2p = {g: p for p, g in _pfr.items()}
_ALIAS = {"WAS": ["Redskins", "Washington_Football_Team"], "TEN": ["Houston_Oilers", "Tennessee_Oilers"], "ARI": ["Phoenix_Cardinals", "St._Louis_Cardinals_(football)"]}
nfl.ASSOC = WA.shares(R[["pid", "fr", "season"]].rename(columns={"fr": "team"}).dropna(), _nt := {g: _wt[p] for g, p in _g2p.items() if p in _wt},
                      {f: [NFLN[f].split("/")[0]] + _ALIAS.get(f, []) for f in teams}, active_since=2025)
nfl.VIEWS = WA.views(_nt); nfl.TEAMTXT = {NT[f]: f for f in teams}; print("nfl association pairs:", len(nfl.ASSOC))
pairs = []
for a, b in itertools.combinations(teams, 2):
    ids = byp[byp.apply(lambda s: a in s and b in s)].index
    if 40 <= len(ids) <= 400: pairs.append((a, b, ids))
for k in rng.permutation(len(pairs))[:120]:
    a, b, ids = pairs[k]; nfl.add(f"Played for both {NT[a]} and {NT[b]}", "Two teams", ids, era="since 1970")
for f in teams: nfl.add(f"Played quarterback for {NT[f]}", "Position", R[(R.fr == f) & (R.position == "QB")].pid, era="since 1970")
for pos, lab in [("RB", "running back"), ("WR", "wide receiver"), ("TE", "tight end"), ("K", "kicker")]:
    for f in teams: nfl.add(f"Played {lab} for {NT[f]}", "Position", R[(R.fr == f) & (R.position == pos)].pid, era="since 1970")
# Super Bowls (keyed by the NFL season the game ended)
SB = {1970: "IND", 1971: "DAL", 1972: "MIA", 1973: "MIA", 1974: "PIT", 1975: "PIT", 1976: "LV", 1977: "DAL", 1978: "PIT", 1979: "PIT", 1980: "LV",
      1981: "SF", 1982: "WAS", 1983: "LV", 1984: "SF", 1985: "CHI", 1986: "NYG", 1987: "WAS", 1988: "SF", 1989: "SF", 1990: "NYG", 1991: "WAS",
      1992: "DAL", 1993: "DAL", 1994: "SF", 1995: "DAL", 1996: "GB", 1997: "DEN", 1998: "DEN", 1999: "LAR", 2000: "BAL", 2001: "NE", 2002: "TB",
      2003: "NE", 2004: "NE", 2005: "PIT", 2006: "IND", 2007: "NYG", 2008: "PIT", 2009: "NO", 2010: "GB", 2011: "NYG", 2012: "BAL", 2013: "SEA",
      2014: "NE", 2015: "DEN", 2016: "NE", 2017: "PHI", 2018: "NE", 2019: "KC", 2020: "TB", 2021: "LAR", 2022: "KC", 2023: "KC", 2024: "PHI", 2025: "SEA"}
_sbw = {}
for y, f in SB.items():
    for p_ in R[(R.season == y) & (R.fr == f)].pid: _sbw.setdefault(f, set()).add(p_)
for f, ids in _sbw.items(): nfl.add(f"Won a Super Bowl with {NT[f]}", "Champion", ids, era="since 1970")
# jersey numbers (season rosters, 2000+, only seasons the player appeared in), league only
_JR = pd.concat([pd.read_csv(f"raw/nfl/roster_{y}.csv", usecols=["season", "team", "gsis_id", "jersey_number"], low_memory=False) for y in range(2000, 2027) if os.path.exists(f"raw/nfl/roster_{y}.csv")])
_JR = _JR[_JR.gsis_id.notna() & (_JR.jersey_number.fillna(0) > 0)]; _JR["fr"] = [nfl_fr(t, y) for t, y in zip(_JR.team, _JR.season)]
_JR = _JR.merge(R[["pid", "fr", "season"]].drop_duplicates(), left_on=["gsis_id", "fr", "season"], right_on=["pid", "fr", "season"])
for n in [1, 3, 4, 7, 9, 10, 11, 12, 13, 15, 18, 19, 21, 22, 24, 26, 28, 32, 34, 52, 54, 55, 56, 58, 80, 81, 84, 85, 87, 88, 89, 90, 92, 93, 99]:
    nfl.add(f"Wore No. {n} in the NFL", "Jersey", _JR[_JR.jersey_number.astype(int) == n].pid, era="since 2000")
# height (season rosters, every season)
_HR = pd.concat([pd.read_csv(f"raw/nfl/roster_{y}.csv", usecols=["season", "team", "full_name", "gsis_id", "height"], low_memory=False) for y in range(1970, 2027) if os.path.exists(f"raw/nfl/roster_{y}.csv")])
_HR["fr"] = [nfl_fr(t, y) for t, y in zip(_HR.team, _HR.season)]
_HR = R[["pid", "full_name", "fr", "season"]].merge(_HR[["full_name", "fr", "season", "height"]].dropna(), on=["full_name", "fr", "season"])
_hh = _HR.groupby("pid").height.median()
nfl.add("Was 6 feet 8 inches or taller", "Height", _hh[_hh >= 80].index, era="since 1970")
nfl.add("Was 5 feet 8 inches or shorter", "Height", _hh[_hh <= 68].index, era="since 1970")
dpg = DP[DP.gsis_id.notna()].copy(); dpg["fr"] = [nfl_fr(t, y) for t, y in zip(dpg.team, dpg.season)]
for f in teams: nfl.add(f"Was a first-round pick of {NT[f]}", "Draft", dpg[(dpg["round"] == 1) & (dpg.fr == f)].gsis_id, era="since 1980")
for f in teams: nfl.add(f"Was drafted by {NT[f]}", "Draft by team", dpg[(dpg.fr == f) & (dpg.season >= 2000)].gsis_id, era="since 2000")
nfl.add("Was the No. 1 overall pick", "Draft", dpg[dpg.pick == 1].gsis_id, era="since 1980")
nfl.add("Was a first-round quarterback", "Draft", dpg[(dpg["round"] == 1) & (dpg.position == "QB")].gsis_id, era="since 1980")
nfl.add("Was drafted in the 7th round or later and made a Pro Bowl", "Draft", dpg[(dpg["round"] >= 7) & (dpg.probowls > 0)].gsis_id, era="since 1980")
for pos, lab in [("QB", "quarterback"), ("RB", "running back"), ("WR", "wide receiver"), ("TE", "tight end"), ("LB", "linebacker"), ("CB", "cornerback"), ("DE", "defensive end"), ("K", "kicker")]:
    nfl.add(f"Made a Pro Bowl as a {lab}", "Pro Bowl", dpg[(dpg.position == pos) & (dpg.probowls > 0)].gsis_id, era="since 1980")
nfl.add("Is in the Hall of Fame", "Hall of Fame", dpg[dpg.hof == True].gsis_id, era="drafted since 1980")
coll = pd.concat([R[["pid", "college"]], dpg[["gsis_id", "college"]].rename(columns={"gsis_id": "pid"})]).dropna()
coll = coll.assign(college=coll.college.str.split(";")).explode("college"); coll["college"] = coll.college.str.strip()   # newer rosters list transfers: "Oklahoma; Texas A&M"
coll = coll[coll.college != ""].drop_duplicates()
for c in coll.college.value_counts().head(45).index:
    nfl.add(f"Played college football at {c}", "College", coll[coll.college == c].pid, era="since 1970")
pss = PS.groupby(["player_id", "season"])[["passing_yards", "passing_tds", "rushing_yards", "rushing_tds", "receiving_yards", "receptions", "receiving_tds"]].sum().reset_index()
for col, v, t in [("passing_yards", 4000, "Threw for 4,000 yards in a season"), ("passing_tds", 30, "Threw 30 touchdown passes in a season"),
                  ("rushing_yards", 1000, "Ran for 1,000 yards in a season"), ("rushing_yards", 1500, "Ran for 1,500 yards in a season"),
                  ("rushing_tds", 12, "Ran for 12 touchdowns in a season"), ("receiving_yards", 1000, "Had 1,000 receiving yards in a season"),
                  ("receptions", 100, "Caught 100 passes in a season"), ("receiving_tds", 10, "Caught 10 touchdown passes in a season")]:
    nfl.add(t, "Season", pss[pss[col] >= v].player_id, era="since 1999")
cps_ = PS.groupby("player_id")[["passing_yards", "rushing_yards", "receiving_yards"]].sum()
for col, v, t in [("passing_yards", 30000, "Threw for 30,000 career yards"), ("rushing_yards", 8000, "Ran for 8,000 career yards"), ("receiving_yards", 8000, "Had 8,000 career receiving yards")]:
    nfl.add(t, "Career", cps_[cps_[col] >= v].index, era="since 1999")
nfr2 = R.groupby("pid").fr.nunique(); nfl.add("Played for 6 or more franchises", "Journeyman", nfr2[nfr2 >= 6].index, era="since 1970")
ns = R.groupby("pid").season.nunique(); nfl.add("Played 17 or more seasons", "Career", ns[ns >= 17].index, era="since 1970")
teammates(nfl, R, "pid", "fr", "season", 40, 1995, era="since 1970")
GM = pd.read_csv("raw/nfl/games.csv"); GM = GM[GM.game_type == "REG"]
cs = pd.concat([GM[["season", "home_team", "home_coach"]].rename(columns={"home_team": "team", "home_coach": "coach"}),
                GM[["season", "away_team", "away_coach"]].rename(columns={"away_team": "team", "away_coach": "coach"})]).dropna().drop_duplicates()
cs["fr"] = [nfl_fr(t, y) for t, y in zip(cs.team, cs.season)]
cn_ = cs.groupby("coach").season.nunique()
GA = pd.read_csv("raw/nfl/games.csv").dropna(subset=["home_score", "away_score"])
GA["wc"] = np.where(GA.home_score > GA.away_score, GA.home_coach, GA.away_coach)
# ---- NFL head coaches, every franchise back to its founding (Wikipedia "List of ... head coaches"), merged with the 1999+ game logs
import nfl_pages as NP
_WFR = {}                                                                            # wiki franchise name -> our code
for full in NP.P["nfl_coaches"]:
    _WFR[full] = next(k for k, v in NFLN.items() if any(full.endswith(" " + w) for w in v.split("/")))
_wk = pd.DataFrame([(fr, *r) for full, fr in _WFR.items() for r in NP.coach_rows(full)],
                   columns=["fr", "name", "art", "y0", "y1", "gc", "interim", "w"])
_wk["key"] = _wk.name.map(NP.norm)
_canon = _wk.sort_values("y1").drop_duplicates("key", keep="last").set_index("key").name.to_dict()   # display name per coach
_art = _wk.drop_duplicates("key", keep="last").set_index("key").art.to_dict()
_c2k = {c: NP.norm(NAMEFIX.get(c, c)) for c in cs.coach.unique()}                  # game-log names -> same key
for c, k in _c2k.items():
    if k not in _canon: _canon[k] = c; print("  coach only in game logs:", c)
cs["key"] = cs.coach.map(_c2k); GA["wk"] = GA.wc.map(_c2k)
_span = pd.concat([_wk[["key", "y0", "y1"]], cs.assign(y0=cs.season, y1=cs.season)[["key", "y0", "y1"]]]).groupby("key").agg(y0=("y0", "min"), y1=("y1", "max"))
_seas = _wk.assign(n=_wk.y1 - _wk.y0 + 1).groupby("key").n.sum()                   # seasons as a head coach, all stints
_gcs = _wk.groupby("key").gc.sum(); _wins = _wk.groupby("key").w.sum()
_cw = GA.groupby("wk").size(); _sbw = GA[GA.game_type == "SB"].wk
_cf = {k: np.log1p(_seas.get(k, 1)) * 3 + 0.02 * max(_wins.get(k, 0), _cw.get(k, 0)) + 2.5 * (_sbw == k).sum() + 2 * min(1, max(0, _span.y1[k] - 2015) / 10) for k in _canon}
nflc = Sport("nflcoach", "NFL coaches")
nflc.setup(_canon, _span.y0.to_dict(), _span.y1.to_dict(), _cf)
_nv = NP.VIEWS; _vs = 365 / max(1, NP.P.get("views_days", 365))
_va = lambda k: _nv.get(str(_art.get(k, _canon[k])).replace(" ", "_"), 0)
nflc.VIEWS = {k: _va(k) * _vs for k in _canon if _va(k)}; nflc.blend_views(0.8)   # legends (Lombardi, Walsh) are read about far more than their win totals suggest
NW = dict(pool=nflc, who="AN NFL HEAD COACH")
for d in range(1960, 2030, 10):
    x = _wk[(_wk.y0 <= d + 9) & (_wk.y1 >= d)].key
    if d >= 2000: x = pd.concat([x, cs[(cs.season >= d) & (cs.season <= d + 9)].key])
    nfl.add(f"Was a head coach in the {d}s", "Coach", x, era="", **NW)
nfl.add("Was a head coach for 10 or more seasons", "Coach", _seas[_seas >= 10].index, era="", **NW)
_nfr = pd.concat([_wk[["key", "fr"]], cs[["key", "fr"]]]).drop_duplicates().groupby("key").fr.nunique()
nfl.add("Was a head coach for 2 or more teams", "Coach", _nfr[_nfr >= 2].index, era="", **NW)
nfl.add("Was a head coach for 3 or more teams", "Coach", _nfr[_nfr >= 3].index, era="", **NW)
for f_ in sorted(_wk.fr.unique()):
    st = _wk[_wk.fr == f_]; g = st.groupby("key").gc.sum(min_count=1)
    brief = {k for k in st.key.unique() if (g.get(k) is not None and not np.isnan(g.get(k)) and g[k] < 8) or (st[st.key == k].interim.all() and not (g.get(k, 0) >= 16))}
    nfl.add(f"Coached {NT[f_]}", "Coach team", st.key, era="", floor={k: 5 for k in brief}, **NW)   # interim and short stints are deep pulls
nfl.add("Won a Super Bowl", "Coach title", _sbw, era="since 1999", **NW)
nfl.add("Coached in a Super Bowl", "Coach title", pd.concat([GA[GA.game_type == "SB"].home_coach, GA[GA.game_type == "SB"].away_coach]).map(_c2k), era="since 1999", **NW)
nfl.add("Won at least 100 games as a head coach", "Coach", _wins[_wins >= 100].index, era="regular season", **NW)
_coy = [NP.norm(n) for _, n, _ in NP.award_rows("coy")]
nfl.add("Won AP Coach of the Year", "Award", [k for k in _coy if k in _canon], era="", **NW)
# ---- player awards (AP MVP, Offensive and Defensive Player of the Year, Super Bowl MVP), matched to our player pool by name and career years
_byname = {}
for pid, nm in names.items(): _byname.setdefault(NP.norm(nm), []).append(pid)
def _award_ids(key, since=1970):
    out = []
    for yr, nm, art in NP.award_rows(key):
        if yr < since: continue
        inyr = lambda p: first.get(p, 0) - 1 <= yr <= last.get(p, 0) + 1
        c = [p for p in _byname.get(NP.norm(nm), []) if inyr(p)]
        if not c:                                    # Pat Surtain II for Patrick Surtain II: same surname, active that year
            sur = NP.norm(re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV)$", "", nm).split()[-1])
            c = [p for k_, ps in _byname.items() if k_.endswith(sur) and k_[0] == NP.norm(nm)[0] for p in ps if inyr(p)]
        if c:
            w_ = max(c, key=lambda p: nfl.FAME.get(p, 0)); out.append(w_)   # two Lamar Jacksons: the famous one won the MVP
            v_ = _nv.get(art.replace(" ", "_"), 0) * _vs                       # winners' own readership (pre-1999 stars lack stat-based fame)
            if v_ > nfl.VIEWS.get(w_, 0): nfl.VIEWS[w_] = v_
        else: print("  award match", key, yr, nm, 0)
    return out
nfl.add("Won AP NFL MVP", "Award", _award_ids("mvp"), era="since 1970")
nfl.add("Won AP Offensive Player of the Year", "Award", _award_ids("opoy"))
nfl.add("Won AP Defensive Player of the Year", "Award", _award_ids("dpoy"))
nfl.add("Won Super Bowl MVP", "Award", _award_ids("sbmvp", 1971))
nfl.add("Won AP Offensive Rookie of the Year", "Award", _award_ids("oroy"), era="since 1970")
nfl.add("Won AP Defensive Rookie of the Year", "Award", _award_ids("droy"), era="since 1970")
for c in cn_[cn_ >= 8].index:
    st = cs[cs.coach == c][["season", "fr"]]
    pl = R.merge(st, on=["season", "fr"]).pid
    nfl.add(f"Played for head coach {c}", "Played for coach", pl, era="since 1999")
team_decades(nfl, R, "pid", "fr", "season", NT, [1980, 1990, 2000, 2010])
for k, t in [(3, "Was a top-3 draft pick"), (5, "Was a top-5 draft pick"), (10, "Was a top-10 draft pick")]:
    nfl.add(t, "Draft", dpg[dpg.pick <= k].gsis_id, era="since 1980")
for pos, lab in [("QB", "quarterback"), ("WR", "wide receiver"), ("RB", "running back"), ("DE", "defensive end"), ("T", "offensive tackle"), ("CB", "cornerback"), ("LB", "linebacker")]:
    nfl.add(f"Was a top-10 pick as a {lab}", "Draft", dpg[(dpg.pick <= 10) & (dpg.position == pos)].gsis_id, era="since 1980")
    nfl.add(f"Was a first-round pick as a {lab}", "Draft", dpg[(dpg["round"] == 1) & (dpg.position == pos)].gsis_id, era="since 1980")

# ======================= NBA (Basketball-Reference, every season since 1947; ESPN box scores since 2002) =======================
import nba_hist as NH
_tot, ONE, _pg, _info, _car, _asg, _dr, _full = NH.load()
D = pd.read_pickle("nba_box.pkl")
ASG = D[D.season_type == 5]
D = D[D.season_type.isin([2, 3])]
D = D[~D.team_name.isin(["All-Stars", "USA", "World"]) & ~D.team_name.fillna("").str.startswith("Team ")]
D["pid"] = D.athlete_id.astype(str)
E2B = NH.espn_map(D, ONE, WA.titles("espn_nba"), WA.titles("bbref_nba"))
D["bid"] = D.pid.map(E2B)
# "played for" = regular season (Basketball-Reference) or postseason (ESPN, 2002+)
D.loc[(D.team_name == "Hornets") & D.team_display_name.fillna("").str.startswith("New Orleans"), "team_name"] = "New Orleans Hornets"   # not the Charlotte Hornets
_po = D[(D.season_type == 3) & D.bid.notna() & ((D.minutes.fillna(0) > 0) | (D.did_not_play == False))][["bid", "team_name", "season"]].drop_duplicates()
PL = pd.concat([ONE[["player_id", "tm", "season"]], _po.rename(columns={"bid": "player_id", "team_name": "tm"})]).drop_duplicates()
PL = PL[PL.tm != "Bobcats"].reset_index(drop=True)
names = ONE.sort_values("season").drop_duplicates("player_id", keep="last").set_index("player_id").player.to_dict()
first = ONE.groupby("player_id").season.min().map(lambda s: s - 1).to_dict(); last = ONE.groupby("player_id").season.max().to_dict()
_c = _tot[_tot.team.str.match(r"^\dTM$|^TOT$") | ~_tot.duplicated(["player_id", "season"], keep=False)]   # one row per player-season
gp = _c.groupby("player_id").g.sum(); pts = _c.groupby("player_id").pts.sum(); seas = _c.groupby("player_id").season.nunique()
astar = _asg.groupby("player_id").season.nunique()
hofb = set(_car[_car.hof.astype(str).str.upper() == "TRUE"].player_id)
_pgc = _pg[_pg.team.str.match(r"^\dTM$|^TOT$") | ~_pg.duplicated(["player_id", "season"], keep=False)]
best = _pgc[_pgc.g >= 20].groupby("player_id").pts_per_game.max().to_dict()
fame = {}
for p in names:
    fame[p] = (np.log1p(gp.get(p, 0)) + pts.get(p, 0) / 4000 + 1.2 * min(astar.get(p, 0), 12) + 5 * (p in hofb)
               + best.get(p, 0) / 2.5 + 1.5 * np.clip((last.get(p, 1980) - 1980) / 46, 0, 1))
nba = Sport("nba", "NBA"); nba.setup(names, first, last, fame)
NBAN = ["76ers", "Bucks", "Bulls", "Cavaliers", "Celtics", "Clippers", "Grizzlies", "Hawks", "Heat", "Hornets", "Jazz", "Kings", "Knicks", "Lakers", "Magic",
        "Mavericks", "Nets", "Nuggets", "Pacers", "Pelicans", "Pistons", "Raptors", "Rockets", "Spurs", "Suns", "Thunder", "Timberwolves", "Trail Blazers",
        "Warriors", "Wizards", "SuperSonics", "Bullets"]
byp = PL.groupby("player_id").tm.apply(set)
for tname in NBAN: nba.add(f"Played for the {tname}", "Team", PL[PL.tm == tname].player_id)
_wt = WA.titles("bbref_nba")
_fulls = {}
for (y, a), f in _full.items(): _fulls.setdefault(NH.tm_of(y, a, f), set()).add(f.replace(" ", "_"))
nba.ASSOC = WA.shares(PL.rename(columns={"player_id": "pid", "tm": "team"}), _bt := {p: _wt[p] for p in names if p in _wt},
                      {t: sorted(fs) for t, fs in _fulls.items()}, active_since=2025)
nba.VIEWS = WA.views(_bt); nba.TEAMTXT = {"the " + t: t for t in NBAN}; print("nba association pairs:", len(nba.ASSOC))
pairs = []
for a, b in itertools.combinations(NBAN, 2):
    ids = byp[byp.apply(lambda s: a in s and b in s)].index
    if 30 <= len(ids) <= 300: pairs.append((a, b, ids))
for k in rng.permutation(len(pairs))[:140]:
    a, b, ids = pairs[k]; nba.add(f"Played for both the {a} and the {b}", "Two teams", ids)
nba.add("Made an All-Star team", "All-Star", astar.index)
_main = ONE.sort_values("g").drop_duplicates(["player_id", "season"], keep="last").set_index(["player_id", "season"]).tm   # team he played most for that season
for tname in NBAN:
    nba.add(f"Made an All-Star team as a member of the {tname}", "All-Star", [p for p, y in zip(_asg.player_id, _asg.season) if _main.get((p, y)) == tname])
nba.add("Is in the Hall of Fame", "Hall of Fame", [p for p in hofb if p in names])
for tname in NBAN: nba.add(f"Is a Hall of Famer and played for the {tname}", "Hall of Fame", [p for p in PL[PL.tm == tname].player_id.unique() if p in hofb])
# NBA titles: on the champion's roster at season's end (or played for them in the playoffs)
_lastteam = ONE.reset_index().sort_values("index", ascending=False).drop_duplicates(["player_id", "season"]).set_index(["player_id", "season"]).team   # rows are listed in order played
_ch = {}
for y, abv in NH.CHAMPS.items():
    tn = NH.tm_of(y, abv, _full[(y, abv)])
    ids = set(ONE[(ONE.season == y) & (ONE.team == abv)].player_id)
    ids = {p for p in ids if _lastteam.get((p, y)) == abv} | set(_po[(_po.season == y) & (_po.team_name == tn)].bid)
    for p in ids: _ch.setdefault(tn, set()).add(p)
for tn, ids in _ch.items(): nba.add(f"Won an NBA title with the {tn}", "Champion", ids)
# box-score feats (ESPN, 2002+)
DB = D[D.bid.notna()]
DB = DB.assign(td=(DB.points >= 10).astype(int) + (DB.rebounds >= 10) + (DB.assists >= 10) + (DB.steals >= 10) + (DB.blocks >= 10))
for cond, t in [(DB.points >= 50, "Scored 50 points in a game"), (DB.points >= 45, "Scored 45 points in a game"), (DB.rebounds >= 20, "Grabbed 20 rebounds in a game"),
                (DB.assists >= 15, "Had 15 assists in a game"), (DB.three_point_field_goals_made >= 9, "Hit 9 threes in a game"),
                (DB.blocks >= 8, "Blocked 8 shots in a game"), (DB.steals >= 7, "Had 7 steals in a game"), (DB.td >= 3, "Had a triple-double")]:
    nba.add(t, "Big game", DB[cond].bid, era="since 2002")
# season averages (50+ games), every season
_s = _pgc[_pgc.g >= 50]
for cond, t in [(_s.pts_per_game >= 30, "Averaged 30 points in a season"), (_s.pts_per_game >= 25, "Averaged 25 points in a season"), (_s.pts_per_game >= 20, "Averaged 20 points in a season"),
                (_s.trb_per_game >= 12, "Averaged 12 rebounds in a season"), (_s.ast_per_game >= 9, "Averaged 9 assists in a season"),
                (_s.blk_per_game >= 2.5, "Averaged 2.5 blocks in a season"), (_s.x3p_per_game * _s.g >= 200, "Made 200 threes in a season")]:
    nba.add(t, "Season", _s[cond].player_id)
for cond, t in [(_s.ast_per_game >= 10, "Averaged 10 assists in a season"), (_s.stl_per_game >= 2, "Averaged 2 steals in a season"),
                (_s.trb_per_game >= 15, "Averaged 15 rebounds in a season"), (_s.blk_per_game >= 3, "Averaged 3 blocks in a season"),
                (_s.x3p_per_game * _s.g >= 250, "Made 250 threes in a season"), ((_s.pts_per_game >= 20) & (_s.trb_per_game >= 10), "Averaged 20 points and 10 rebounds in a season"),
                ((_s.pts_per_game >= 20) & (_s.ast_per_game >= 8), "Averaged 20 points and 8 assists in a season")]:
    nba.add(t, "Season", _s[cond].player_id)
_ct = _c.groupby("player_id")[["trb", "ast", "x3p", "blk", "stl"]].sum()
for col, v, t in [("trb", 10000, "Grabbed 10,000 career rebounds"), ("ast", 5000, "Had 5,000 career assists"), ("x3p", 1500, "Made 1,500 career threes"),
                  ("blk", 1500, "Blocked 1,500 career shots"), ("stl", 1500, "Had 1,500 career steals"), ("trb", 7000, "Grabbed 7,000 career rebounds")]:
    nba.add(t, "Career", _ct[_ct[col] >= v].index)
for cond, t in [(DB.points >= 40, "Scored 40 points in a game"), (DB.rebounds >= 25, "Grabbed 25 rebounds in a game"), (DB.three_point_field_goals_made >= 10, "Hit 10 threes in a game")]:
    nba.add(t, "Big game", DB[cond].bid, era="since 2002")
# single-season averages for one team (40+ games with them)
_ts = _pg[~_pg.team.str.match(r"^\dTM$|^TOT$") & (_pg.g >= 40)].copy(); _ts["tm"] = [NH.tm_of(y, a, _full.get((y, a), "x")) for y, a in zip(_ts.season, _ts.team)]
for tname in NBAN:
    x_ = _ts[_ts.tm == tname]
    nba.add(f"Averaged 15 points in a season for the {tname}", "Team season", x_[x_.pts_per_game >= 15].player_id)
    nba.add(f"Averaged 8 rebounds in a season for the {tname}", "Team season", x_[x_.trb_per_game >= 8].player_id)
    nba.add(f"Averaged 5 assists in a season for the {tname}", "Team season", x_[x_.ast_per_game >= 5].player_id)
for v, t in [(25000, "Scored 25,000 points"), (20000, "Scored 20,000 points"), (15000, "Scored 15,000 points"), (10000, "Scored 10,000 points")]:
    nba.add(t, "Career", pts[pts >= v].index)
nt = PL.groupby("player_id").tm.nunique(); nba.add("Played for 8 or more teams", "Journeyman", nt[nt >= 8].index)
nba.add("Played 15 or more seasons", "Career", seas[seas >= 15].index)
# draft (Basketball-Reference, every draft)
_d = _dr[_dr.player_id.isin(names.keys())]
for k, t in [(1, "Was the No. 1 overall pick"), (3, "Was a top-3 draft pick"), (5, "Was a top-5 draft pick"), (10, "Was a top-10 draft pick")]:
    nba.add(t, "Draft", _d[_d.overall_pick <= k].player_id)
nba.add("Was a lottery pick (top 14)", "Draft", _d[(_d.overall_pick <= 14) & (_d.season >= 1985)].player_id, era="since 1985")
nba.add("Was a second-round pick", "Draft", _d[(_d["round"] == 2) & (_d.season >= 1990)].player_id, era="drafted since 1990")
top10 = set(_d[_d.overall_pick <= 10].player_id)
for tname in NBAN: nba.add(f"Was a top-10 pick and played for the {tname}", "Draft", [p for p in PL[PL.tm == tname].player_id.unique() if p in top10])
# position + team (Basketball-Reference season positions)
_pos = _info[["player_id", "season", "pos"]].dropna().drop_duplicates(["player_id", "season"])
_pos["p1"] = _pos.pos.str.split("-").str[0]
_pt = ONE[["player_id", "season", "tm"]].merge(_pos, on=["player_id", "season"])
for code, lab in [("C", "center"), ("PG", "point guard")]:
    for tname in NBAN: nba.add(f"Played {lab} for the {tname}", "Position", _pt[(_pt.p1 == code) & (_pt.tm == tname)].player_id)
# height
_h = _car.set_index("player_id").ht_in_in
nba.add("Was 7 feet or taller", "Height", _h[_h >= 84].index)
nba.add("Was 6 feet tall or shorter", "Height", _h[_h <= 72].index)
nba.add("Was 7 feet 2 inches or taller", "Height", _h[_h >= 86].index)
# college (Basketball-Reference career info, every era)
_col = _car[["player_id", "colleges"]].dropna()
_col = _col.assign(c=_col.colleges.str.split(",")).explode("c"); _col["c"] = _col.c.str.strip()
for t in ["Kentucky", "Duke", "UNC", "Kansas", "UCLA", "Arizona", "Texas", "Florida", "Michigan State", "Gonzaga", "Villanova", "UConn", "Syracuse",
          "Louisville", "Michigan", "Indiana", "Ohio State", "USC", "Wake Forest", "Memphis", "LSU", "Georgetown", "Oregon", "Tennessee", "Alabama", "Arkansas",
          "Notre Dame", "Maryland", "Purdue", "Illinois", "Georgia Tech", "St. John's", "Cincinnati", "Oklahoma", "Houston", "Marquette", "Virginia"]:
    lab = {"UNC": "North Carolina", "UConn": "Connecticut"}.get(t, t)
    nba.add(f"Played college basketball at {lab}", "College", _col[_col.c == t].player_id)
# birthplaces (ESPN player info, 2002+)
CORE = pd.read_pickle("nba_core.pkl"); CORE["pid"] = CORE.athlete_id.astype(str); CORE["bid"] = CORE.pid.map(E2B); CORE = CORE[CORE.bid.notna()]
nba.add("Was born outside the U.S.", "Birthplace", CORE[CORE.birth_country.notna() & (CORE.birth_country != "USA")].bid, era="since 2002")
for c in CORE.birth_country.value_counts().index:
    if c != "USA": nba.add(f"Was born in {c}", "Birthplace", CORE[CORE.birth_country == c].bid, era="since 2002")
REG = {"Europe": ["Austria", "Belgium", "Bosnia & Herzegovina", "Croatia", "Cyprus", "Czech Republic", "England", "Estonia", "Finland", "France", "Georgia", "Germany",
        "Greece", "Iceland", "Ireland", "Italy", "Latvia", "Lithuania", "Macedonia", "Montenegro", "Netherlands", "Poland", "Portugal", "Russia", "Scotland", "Serbia",
        "Slovenia", "Spain", "Sweden", "Switzerland", "Türkiye", "Ukraine", "West Germany", "Yugoslavia"],
       "Africa": ["Angola", "Cameroon", "Cape Verde", "Congo", "Democratic Republic of Congo", "Egypt", "Gabon", "Ghana", "Guinea", "Mali", "Nigeria", "Senegal",
        "South Africa", "South Sudan", "Sudan", "Zaire"],
       "the former Yugoslavia": ["Yugoslavia", "Serbia", "Croatia", "Slovenia", "Bosnia & Herzegovina", "Montenegro", "Macedonia"],
       "South America": ["Argentina", "Brazil", "Colombia", "Guyana", "Uruguay", "Venezuela"]}
for reg, cs in REG.items(): nba.add(f"Was born in {reg}", "Birthplace", CORE[CORE.birth_country.isin(cs)].bid, era="since 2002")
intl = set(CORE[CORE.birth_country.notna() & (CORE.birth_country != "USA")].bid)
_pl02 = PL[PL.season >= 2002]
for tname in NBAN: nba.add(f"Was born outside the U.S. and played for the {tname}", "Country + team", [p for p in _pl02[_pl02.tm == tname].player_id.unique() if p in intl], era="since 2002")
nba.add("Was born outside the U.S. and made an All-Star team", "Country + All-Star", [p for p in _asg[_asg.season >= 2002].player_id.unique() if p in intl], era="since 2002")
# jersey numbers (ESPN box scores, 2002+), league only
_j = pd.concat([pd.read_parquet(f, columns=["athlete_id", "athlete_jersey", "season_type"]) for f in sorted(glob.glob("raw/nba/pb_*.parquet"))])
_j = _j[_j.season_type.isin([2, 3])]; _j = _j[_j.athlete_id.notna()]; _j["bid"] = _j.athlete_id.astype("int64").astype(str).map(E2B); _j = _j[_j.bid.notna() & _j.athlete_jersey.notna()].drop_duplicates(["bid", "athlete_jersey"])
for n in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "20", "21", "22", "23", "24", "25", "30", "32", "33", "34", "35", "41", "44", "55"]:
    nba.add(f"Wore No. {n} in the NBA", "Jersey", _j[_j.athlete_jersey.astype(str) == n].bid, era="since 2002")
teammates(nba, ONE.rename(columns={"player_id": "pid"}), "pid", "tm", "season", 40, 1985)
team_decades(nba, PL, "player_id", "tm", "season", {t: "the " + t for t in NBAN}, [1980, 1990, 2000, 2010, 2020])

# ----------------------- NBA awards (Basketball-Reference voting, NBA/BAA only) -----------------------
_aw = pd.read_csv(NH.BB + "Player Award Shares.csv"); _aw = _aw[_aw.award.str.startswith(("nba ", "baa "))]
_win = _aw[_aw.winner.astype(str).str.upper() == "TRUE"]
for a_, t_ in [("mvp", "Won MVP"), ("roy", "Won Rookie of the Year"), ("dpoy", "Won Defensive Player of the Year"), ("smoy", "Won Sixth Man of the Year"),
               ("mip", "Won Most Improved Player")]:
    nba.add(t_, "Award", _win[_win.award.str.endswith(" " + a_)].player_id)
nba.add("Received MVP votes", "Award", _aw[(_aw.award == "nba mvp") & (_aw.pts_won > 0)].player_id)

# ----------------------- NBA head coaches (Basketball-Reference team pages via Colab; interim coaches count) -----------------------
_rows = []
for _fr, _rs in CO["nba"]["franchises"].items():
    for r in _rs:
        if r.get("lg_id") not in ("NBA", "BAA") or not re.match(r"^\d{4}-\d{2}$", r.get("season", "")): continue
        y = int(r["season"][:4]) + 1; full = r["team_name"].rstrip(" *"); tm = NH.tm_of(y, _fr, full)
        won = r.get("rank_team_playoffs", "") == "Won Finals"
        for cid, w, l in re.findall(r'href="/coaches/([a-z0-9]+)\.html">[^<]+</a>\s*\((\d+)-(\d+)\)', r.get("_coaches_html", "")):
            _rows.append((cid, y, tm, int(w), int(l), won))
NC = pd.DataFrame(_rows, columns=["cid", "season", "tm", "w", "l", "won"])
NC["g"] = NC.w + NC.l
_last_c = NC.sort_values("g").groupby(["season", "tm"]).tail(1)                         # the coach who finished a title season gets the ring
_cn = CO["nba"]["coach_names"]; _ncs = NC.groupby("cid").agg(G=("g", "sum"), W=("w", "sum"), y0=("season", "min"), y1=("season", "max"))
_ring = _last_c[_last_c.won].cid.value_counts()
_pid_by_name = {}
for _p, (_n, _a, _b) in zip(nba.ids, nba.players): _pid_by_name.setdefault(NH.norm(_n), _p)
_asp = {c: _pid_by_name.get(NH.norm(_cn.get(c, ""))) for c in _ncs.index}                 # coaches who also played in the NBA
_cf = {c: np.log1p(_ncs.G[c]) + _ncs.W[c] / 300 + 2.5 * _ring.get(c, 0) + 2 * np.clip((_ncs.y1[c] - 1980) / 46, 0, 1)
          + (0.25 * nba.FAME.get(_asp[c], 0) if _asp[c] else 0) for c in _ncs.index}
nbac = Sport("nbacoach", "NBA coaches"); nbac.setup({c: _cn.get(c, c) for c in _ncs.index}, _ncs.y0.to_dict(), _ncs.y1.to_dict(), _cf)
nbac.VIEWS = coach_views("nba", {c: _cn.get(c) for c in _ncs.index}); nbac.blend_views()
BW = dict(pool=nbac, who="AN NBA HEAD COACH")
for tname in NBAN:
    _x = NC[NC.tm == tname]; _g = _x.groupby("cid").g.sum()
    _note = NH.TEAM_NOTE.get(tname, "")
    nba.add(f"Coached the {tname}", "Coach team", _x.cid, era=_note, floor={c: 5 for c in _g[_g < 20].index}, **BW)
nba.add("Won an NBA title", "Coach title", _last_c[_last_c.won].cid, **BW)
for d in (1970, 1980, 1990, 2000, 2010, 2020):
    nba.add(f"Coached in the {d}s", "Coach", NC[(NC.season > d) & (NC.season <= d + 10)].cid, **BW)
_nct = NC.groupby("cid").tm.nunique(); nba.add("Coached 3 or more teams", "Coach", _nct[_nct >= 3].index, **BW)
nba.add("Won at least 500 games as a head coach", "Coach", _ncs[_ncs.W >= 500].index, **BW)
_pl_last = PL.groupby(["player_id", "tm"]).season.max().to_dict()
_pc = [c for c, s_, t_ in zip(NC.cid, NC.season, NC.tm) if _asp.get(c) and _pl_last.get((_asp[c], t_), 9999) < s_]
nba.add("Played for and later coached the same team", "Coach", _pc, **BW)

# ======================= SOCCER (Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, MLS, Champions League) =======================
SP = pd.read_csv("raw/soc/player_performances.csv", usecols=["player_id", "season_name", "competition_id", "team_id", "team_name", "nb_on_pitch", "goals", "assists", "clean_sheets", "minutes_played"])
# players the source dataset is missing entirely, added by hand: club seasons only (no goal/assist counts, so they never enter stat prompts)
HAND_SOC = [  # (id, name, citizenship, main position, position, [(season, competition, team id, team name)])
    (9000001, "Álex Baena", "Spain", "Midfield", "Midfield - Attacking Midfield",
     [("22/23", "ES1", 1050, "Villarreal CF"), ("23/24", "ES1", 1050, "Villarreal CF"), ("24/25", "ES1", 1050, "Villarreal CF"), ("25/26", "ES1", 13, "Atlético de Madrid")]),
]
SP = pd.concat([SP, pd.DataFrame([{"player_id": i, "season_name": se, "competition_id": c, "team_id": t, "team_name": tn, "nb_on_pitch": 1}
                                  for i, _, _, _, _, rows in HAND_SOC for se, c, t, tn in rows])], ignore_index=True)
SOCL = {"epl": ("GB1", "Premier League", "England"), "liga": ("ES1", "LaLiga", "Spain"), "seriea": ("IT1", "Serie A", "Italy"), "bund": ("L1", "Bundesliga", "Germany"),
        "ligue1": ("FR1", "Ligue 1", "France"), "mls": ("MLS1", "MLS", "United States"), "ucl": ("CL", "Champions League", None)}
SP = SP[SP.competition_id.isin([v[0] for v in SOCL.values()]) & (SP.nb_on_pitch > 0)].copy()
_sn = SP.season_name.astype(str)
SP["y"] = np.where(_sn.str.len() == 4, pd.to_numeric(_sn, errors="coerce"),   # MLS seasons are calendar years ("2024")
                   np.where(_sn.str[:2].astype(int) > 50, 1900 + _sn.str[:2].astype(int), 2000 + _sn.str[:2].astype(int)))
SP = SP[SP.y >= 2005]   # the source is only complete from 2005-06 on
def club(n):
    n = re.sub(r"\s*\(.*\)$", "", str(n))
    for pre in ("FC ", "AFC ", "CF ", "RCD ", "RC ", "CD ", "UD ", "SD ", "CA ", "SC "):
        if n.startswith(pre) and n not in ("FC Barcelona",): n = n[len(pre):]
    for suf in (" FC", " AFC", " CF", " SAD", " Balompié"):
        if n.endswith(suf): n = n[: -len(suf)]
    n = n.strip()
    return NICE.get(n, n)
NICE = {"Toronto": "Toronto FC", "Los Angeles Galaxy": "LA Galaxy", "Seattle Sounders": "Seattle Sounders", "Bayer 04 Leverkusen": "Bayer Leverkusen",
        "FC Schalke 04": "Schalke 04", "Schalke 04": "Schalke 04", "SV Werder Bremen": "Werder Bremen", "SSC Napoli": "Napoli", "LOSC Lille": "Lille",
        "Olympique Lyon": "Lyon", "Olympique Marseille": "Marseille", "Stade Rennais": "Rennes", "Los Angeles": "LAFC", "Inter Miami": "Inter Miami",
        "Atlanta United": "Atlanta United", "New York City": "New York City FC", "Girondins Bordeaux": "Bordeaux", "AS Saint-Étienne": "Saint-Étienne", "Porto": "FC Porto"}
SP["club"] = SP.team_name.map(club)
_cur = pd.read_csv("raw/soc/player_profiles.csv", usecols=["player_id", "current_club_id", "current_club_name"], low_memory=False).dropna()
for cid in ("GB1", "ES1", "IT1", "L1", "FR1"):   # the snapshot only has the first weeks of 2025-26, so count current squad members too
    cur_season = SP[(SP.competition_id == cid) & (SP.y == 2025)]
    lc = set(cur_season.team_id); have = set(zip(cur_season.player_id, cur_season.team_id))   # match by club id ("Arsenal FC" also exists in Argentina)
    tname = cur_season.drop_duplicates("team_id").set_index("team_id").team_name
    add = _cur[_cur.current_club_id.isin(lc)]
    add = add[[(p, c) not in have for p, c in zip(add.player_id, add.current_club_id)]]
    SP = pd.concat([SP, pd.DataFrame({"player_id": add.player_id, "season_name": "25/26", "competition_id": cid, "team_id": add.current_club_id, "team_name": add.current_club_id.map(tname),
                                      "nb_on_pitch": 1, "goals": 0, "assists": 0, "clean_sheets": 0, "minutes_played": 0, "y": 2025,
                                      "club": add.current_club_id.map(tname).map(club)})], ignore_index=True)
PP = pd.read_csv("raw/soc/player_profiles.csv", usecols=["player_id", "player_name", "citizenship", "main_position", "position"], low_memory=False)
PP = pd.concat([PP, pd.DataFrame([{"player_id": i, "player_name": n, "citizenship": c, "main_position": mp, "position": po} for i, n, c, mp, po, _ in HAND_SOC])], ignore_index=True)
PP = PP[PP.player_id.isin(SP.player_id)].drop_duplicates("player_id")
PP["name"] = PP.player_name.str.replace(r"\s*\(\d+\)$", "", regex=True)
PP = PP[PP.name.notna() & (PP.name.str.strip() != "")]
NAT = pd.read_csv("raw/soc/player_national_performances.csv", usecols=["player_id", "matches"]).groupby("player_id").matches.sum()
apps = SP.groupby("player_id").nb_on_pitch.sum(); gls = SP.groupby("player_id").goals.sum(); seas_s = SP.groupby(["player_id"]).y.nunique()
lasty = SP.groupby("player_id").y.max(); firsty = SP.groupby("player_id").y.min()
MV = pd.read_csv("raw/soc/player_market_value.csv", usecols=["player_id", "value"]).groupby("player_id").value.max()   # peak market value = fame
fame = {}
for p in PP.player_id:
    mv = MV.get(p, 0) or 0
    fame[p] = (np.log1p(apps.get(p, 0)) + gls.get(p, 0) / 25 + np.log1p(NAT.get(p, 0)) * 1.3 + 1.5 * np.clip((lasty.get(p, 1992) - 1992) / 33, 0, 1)
               + 3.6 * max(0.0, np.log10(mv + 1) - 5))
soc = Sport("soc", "Soccer")
soc.setup(PP.set_index("player_id").name.to_dict(), firsty.to_dict(), lasty.to_dict(), fame)
soc.VIEWS = WA.football_views(PP.set_index("player_id").name.to_dict()); soc.blend_views()   # Wikipedia readers arriving from football pages
leagues = {k: (v[0], v[1]) for k, v in SOCL.items()}
NATN = {"Netherlands": "the Netherlands", "United States": "the USA", "Cote d'Ivoire": "Ivory Coast", "Ireland": "the Republic of Ireland", "Korea, South": "South Korea", "Czech Republic": "the Czech Republic"}
# only clubs a casual fan knows get their own prompts (nobody knows who played for Wigan)
BIG = {"GB1": ["Arsenal", "Chelsea", "Liverpool", "Manchester City", "Manchester United", "Tottenham Hotspur", "Newcastle United", "Everton", "Aston Villa", "West Ham United"],
       "ES1": ["Real Madrid", "FC Barcelona", "Atlético de Madrid", "Sevilla", "Valencia", "Villarreal", "Athletic Bilbao", "Real Sociedad", "Real Betis"],
       "IT1": ["Juventus", "Inter Milan", "AC Milan", "AS Roma", "SS Lazio", "Napoli", "ACF Fiorentina", "Atalanta BC"],
       "L1": ["Bayern Munich", "Borussia Dortmund", "Bayer Leverkusen", "Schalke 04", "Werder Bremen", "VfB Stuttgart", "Eintracht Frankfurt", "VfL Wolfsburg"],
       "FR1": ["Paris Saint-Germain", "Marseille", "Lyon", "AS Monaco", "Lille", "Bordeaux"],
       "MLS1": ["LA Galaxy", "Seattle Sounders", "Toronto FC", "New York Red Bulls", "D.C. United", "Inter Miami", "Atlanta United", "LAFC", "Portland Timbers", "Chicago Fire"],
       "CL": ["Real Madrid", "FC Barcelona", "Bayern Munich", "Manchester United", "Liverpool", "Chelsea", "Juventus", "AC Milan", "Inter Milan", "Arsenal",
              "Paris Saint-Germain", "Borussia Dortmund", "Manchester City", "Atlético de Madrid", "Ajax Amsterdam", "SL Benfica", "FC Porto"]}
socbanks = {}
for key, (cid, lname) in leagues.items():
    lg = Sport(key, lname); lg.ids, lg.IDX, lg.players, lg.FAME, lg.GQ = soc.ids, soc.IDX, soc.players, soc.FAME, soc.GQ
    _add = lg.add; lg.add = (lambda t, k, ids, era="2005-2025", _a=_add: _a(t, k, ids, era))
    x = SP[SP.competition_id == cid]
    _lf = pd.Series({p_: soc.FAME[p_] for p_ in set(x.player_id) if p_ in soc.FAME})   # fame rank among this competition's players
    lg.VIEWS = soc.VIEWS; lg.GQ = dict.fromkeys(soc.ids, 1.0); lg.GQ.update(_lf.rank(ascending=False, pct=True).to_dict()); lg.NPOOL = len(_lf)
    era = f"{lname}, {int(x.y.min())}-{str(int(x.y.max()) + 1)[2:]} on" if False else ""
    clubs = [c for c in BIG[cid] if c in set(x.club)]; assert len(clubs) == len(BIG[cid]), (cid, set(BIG[cid]) - set(x.club))
    for c in clubs: lg.add(f"Played for {c}", "Club", x[x.club == c].player_id)
    byp_ = x.groupby("player_id").club.apply(set); prs = []
    for a, b in itertools.combinations(clubs, 2):
        ids = byp_[byp_.apply(lambda s: a in s and b in s)].index
        if 30 <= len(ids) <= 250: prs.append((a, b, ids))
    for k in rng.permutation(len(prs))[:40]:
        a, b, ids = prs[k]; lg.add(f"Played for both {a} and {b}", "Two clubs", ids)
    W = "Champions League" if cid == "CL" else "league"
    ps_ = x.groupby(["player_id", "y"])[["goals", "assists", "clean_sheets"]].sum().reset_index()
    for col, v, t in [("goals", 20, "Scored 20 league goals in a season"), ("goals", 15, "Scored 15 league goals in a season"), ("goals", 10, "Scored 10 league goals in a season"),
                      ("assists", 10, "Had 10 league assists in a season"), ("clean_sheets", 15, "Kept 15 clean sheets in a season")]:
        if cid != "CL": lg.add(t, "Season", ps_[ps_[col] >= v].player_id)
    cg = x.groupby("player_id").goals.sum(); ca = x.groupby("player_id").nb_on_pitch.sum()
    for ids, t in [(cg[cg >= 100].index, "Scored 100 league goals"), (cg[cg >= 50].index, "Scored 50 league goals"), (ca[ca >= 300].index, "Played 300 league games")]:
        if cid != "CL": lg.add(t, "Career", ids)
    ca2 = x.groupby("player_id").assists.sum()
    if cid != "CL":
        for ids, t in [(cg[cg >= 150].index, "Scored 150 league goals"), (cg[cg >= 75].index, "Scored 75 league goals"), (ca[ca >= 200].index, "Played 200 league games"),
                       (ca[ca >= 400].index, "Played 400 league games"), (ca2[ca2 >= 50].index, "Had 50 league assists"), (cg[cg >= 25].index, "Scored 25 league goals")]:
            lg.add(t, "Career", ids)
        for col, v, t in [("goals", 25, "Scored 25 league goals in a season"), ("assists", 12, "Had 12 league assists in a season"), ("goals", 12, "Scored 12 league goals in a season"),
                          ("assists", 8, "Had 8 league assists in a season"), ("clean_sheets", 12, "Kept 12 clean sheets in a season")]:
            lg.add(t, "Season", ps_[ps_[col] >= v].player_id)
        pcs = x.groupby(["player_id", "y", "club"])[["goals", "assists"]].sum().reset_index()
        for c in clubs:
            lg.add(f"Scored 10 league goals in a season for {c}", "Team season", pcs[(pcs.club == c) & (pcs.goals >= 10)].player_id)
            lg.add(f"Scored 5 league goals in a season for {c}", "Team season", pcs[(pcs.club == c) & (pcs.goals >= 5)].player_id)
            lg.add(f"Had 5 league assists in a season for {c}", "Team season", pcs[(pcs.club == c) & (pcs.assists >= 5)].player_id)
    else:
        pcs = x.groupby(["player_id", "club"])[["goals"]].sum().reset_index()
        for ids, t in [(cg[cg >= 5].index, "Scored 5 Champions League goals"), (cg[cg >= 20].index, "Scored 20 Champions League goals"), (ca[ca >= 75].index, "Played 75 Champions League games")]:
            lg.add(t, "Career", ids)
    if cid == "CL":
        for ids, t in [(cg[cg >= 10].index, "Scored 10 Champions League goals"), (ca[ca >= 50].index, "Played 50 Champions League games"), (ca[ca >= 25].index, "Played 25 Champions League games")]:
            lg.add(t, "Career", ids)
    natp = PP.set_index("player_id").citizenship.reindex(x.player_id.unique()).dropna().str.split(r"\s{2,}").str[0]   # first citizenship only
    for nat in natp.value_counts().head(22).index:
        if nat == SOCL[key][2]: continue
        lg.add(f"Is from {NATN.get(nat, nat)}", "Nationality", natp[natp == nat].index)
    nc = x.groupby("player_id").club.nunique()
    if cid != "CL": lg.add("Played for 5 or more clubs in the league", "Journeyman", nc[nc >= 5].index)
    gk = PP[PP.main_position.fillna("").str.contains("Goalkeeper")].player_id
    for c in clubs: lg.add(f"Played goalkeeper for {c}", "Position", x[(x.club == c) & x.player_id.isin(gk)].player_id)
    st = PP[PP.position.fillna("").str.contains("Centre-Forward")].player_id
    for c in clubs: lg.add(f"Played striker for {c}", "Position", x[(x.club == c) & x.player_id.isin(st)].player_id)
    pc = x.groupby(["player_id", "club"])[["nb_on_pitch", "goals"]].sum().reset_index()
    for c in clubs:
        lg.add(f"Scored a {W} goal for {c}", "Club goals", pc[(pc.club == c) & (pc.goals > 0)].player_id)
        if cid != "CL": lg.add(f"Played 100 league games for {c}", "Club stalwart", pc[(pc.club == c) & (pc.nb_on_pitch >= 100)].player_id)
    mainclub = x.groupby(["player_id", "club"]).nb_on_pitch.sum().reset_index().sort_values("nb_on_pitch").drop_duplicates("player_id", keep="last").set_index("player_id").club
    _n0 = len(lg.prompts)
    teammates(lg, SP if cid == "CL" else x, "player_id", "team_id", "y", 22, 2012, era="2005-2025", min_seasons=4, label=lambda n: f"Was a club teammate of {n}", ok=lambda p: mainclub.get(p) in clubs)
    if cid == "CL":   # a club teammate is a club teammate in any competition, so the question is about "a player"
        for q_ in lg.prompts[_n0:]: q_["who"] = "A PLAYER"
    clubname = x.drop_duplicates("team_id").set_index("team_id").club.to_dict()
    for tid, cnm in clubname.items():
        if cnm in clubs:
            for d in (2010, 2020):
                xx = x[(x.team_id == tid) & (x.y >= d) & (x.y <= d + 9)]
                lg.add(f"Played for {cnm} in the {d}s", "Team decade", xx.player_id, era="")
    socbanks[key] = lg
both = set(SP[SP.competition_id == "GB1"].player_id) & set(SP[SP.competition_id == "ES1"].player_id)
socbanks["liga"].add("Also played in the Premier League", "Cross-league", both)
socbanks["epl"].add("Also played in LaLiga", "Cross-league", both)
for k in leagues: socbanks[k].lab = leagues[k][1]

# ----------------------- soccer managers of the big clubs (Wikidata via Colab; caretakers count) -----------------------
_TM = {"11": "Arsenal", "631": "Chelsea", "31": "Liverpool", "281": "Manchester City", "985": "Manchester United", "148": "Tottenham Hotspur",
       "762": "Newcastle United", "29": "Everton", "405": "Aston Villa", "379": "West Ham United", "418": "Real Madrid", "131": "FC Barcelona",
       "13": "Atlético de Madrid", "368": "Sevilla", "1049": "Valencia", "1050": "Villarreal", "621": "Athletic Bilbao", "681": "Real Sociedad",
       "150": "Real Betis", "506": "Juventus", "46": "Inter Milan", "5": "AC Milan", "12": "AS Roma", "398": "SS Lazio", "6195": "Napoli",
       "430": "ACF Fiorentina", "800": "Atalanta BC", "27": "Bayern Munich", "16": "Borussia Dortmund", "15": "Bayer Leverkusen", "33": "Schalke 04",
       "86": "Werder Bremen", "79": "VfB Stuttgart", "24": "Eintracht Frankfurt", "82": "VfL Wolfsburg", "583": "Paris Saint-Germain", "244": "Marseille",
       "1041": "Lyon", "162": "AS Monaco", "1082": "Lille", "40": "Bordeaux", "1061": "LA Galaxy", "9636": "Seattle Sounders", "11141": "Toronto FC",
       "623": "New York Red Bulls", "2440": "D.C. United", "69261": "Inter Miami", "51663": "Atlanta United", "51828": "LAFC", "4291": "Portland Timbers",
       "432": "Chicago Fire", "610": "Ajax Amsterdam", "294": "SL Benfica", "720": "FC Porto"}
_BADPOS = re.compile(r"assistant|goalkeeper|executive|officer|U\d|youth|^Q\d", re.I)
_st = []
for r in CO["soc_club_side"]:   # the club's own head-coach list; the per-person list mixes in B teams, women's teams and assistants
    if r["tm"] not in _TM or not re.match(r"\d{4}", r.get("start", "")) or _BADPOS.search(r.get("posLabel") or ""): continue
    if r.get("end") and not re.match(r"\d{4}", r["end"]): continue                         # "unknown" end date
    y0 = int(r["start"][:4]); y1 = int(r["end"][:4]) if r.get("end") else 2026
    _st.append((r["coach"].rsplit("/", 1)[-1], r["coachLabel"], r.get("title"), _TM[r["tm"]], y0, y1, r["start"][:10], (r.get("end") or "2026-12-31")[:10]))
SM = pd.DataFrame(_st, columns=["qid", "name", "title", "club", "y0", "y1", "d0", "d1"]).drop_duplicates(["qid", "club", "y0"])
SM = SM[~SM.name.str.match(r"^Q\d+$")]
_sw = []   # league / Champions League winners since 1993 -> the manager in charge when the season ended
_COMP = {"Q15804": "Serie A", "Q82595": "Bundesliga", "La Liga": "LaLiga", "Ligue 1": "Ligue 1", "Premier League": "Premier League",
         "Major League Soccer": "MLS", "UEFA Champions League": "Champions League"}
for r in CO["soc_winners"]:
    comp = _COMP.get(r["compLabel"]); club = _TM.get(r.get("wtm", ""))
    endd = (r.get("end") or r.get("pt") or "")[:10]
    if not comp or not club or not endd or int(endd[:4]) < 1993: continue
    m = SM[(SM.club == club) & (SM.d0 <= endd) & (SM.d1 >= endd)]
    for q in m.qid: _sw.append((comp, q))
SW_ = pd.DataFrame(_sw, columns=["comp", "qid"]).drop_duplicates()
_sname = SM.drop_duplicates("qid").set_index("qid")
_sv = {q: CO["views"].get(str(t).replace(" ", "_"), 0) * CO_VSCALE for q, t in _sname.title.items() if t}
_sf = {q: np.log1p(len(SM[SM.qid == q])) + 1.5 * (SW_.qid == q).sum() + np.log1p(_sv.get(q, 0)) * .6 + 1.5 * np.clip((_sname.y1[q] - 1990) / 36, 0, 1) for q in _sname.index}
socc = Sport("soccoach", "Soccer managers"); socc.setup(_sname.name.to_dict(), _sname.y0.to_dict(), _sname.y1.to_dict(), _sf)
socc.VIEWS = {q: v for q, v in _sv.items() if v}; socc.blend_views()
_home = {}
for cid_, cl_ in BIG.items():
    for c in cl_:
        if cid_ != "CL" or c not in _home: _home[c] = cid_
_bank_of = {v[0]: k for k, v in SOCL.items()}
for club in sorted(set(SM.club)):
    lg_ = socbanks[_bank_of[_home[club]]]; mls_ = _home[club] == "MLS1"; since = 1996 if mls_ else 1992
    _x = SM[SM.y1 >= since + 1]
    Sport.add(lg_, f"Managed {club}" if not mls_ else f"Coached {club}", "Coach team", _x[_x.club == club].qid,
              era="" if mls_ else f"since {since}", pool=socc, who="A MANAGER" if not mls_ else "A HEAD COACH")
for comp, key in [("Premier League", "epl"), ("LaLiga", "liga"), ("Serie A", "seriea"), ("Bundesliga", "bund"), ("Ligue 1", "ligue1"), ("Champions League", "ucl"), ("MLS", "mls")]:
    Sport.add(socbanks[key], f"Won {'the ' if comp in ('Premier League', 'Champions League', 'Bundesliga') else ''}{comp if comp != 'MLS' else 'an MLS title'}",
              "Coach title", SW_[SW_.comp == comp].qid, era="since 1993", pool=socc, who="A MANAGER" if comp != "MLS" else "A HEAD COACH")

# ======================= F1 =======================
FD = pd.read_csv("raw/f1/f1db-drivers.csv"); RR = pd.read_csv("raw/f1/f1db-races-race-results.csv", low_memory=False)
SE = pd.read_csv("raw/f1/f1db-seasons-entrants-drivers.csv"); CO = pd.read_csv("raw/f1/f1db-constructors.csv")
SE = SE[SE.testDriver != True]
cn = CO.set_index("id").name.to_dict()
starts = RR.groupby("driverId").size()
FD = FD[FD.id.isin(SE.driverId)]
fame = {r.id: (np.log1p(r.totalRaceStarts) + 1.2 * np.log1p(r.totalRaceWins) * 2 + 4 * r.totalChampionshipWins + np.log1p(r.totalPodiums) + np.log1p(r.totalPolePositions)
               + 1.5 * np.clip((SE[SE.driverId == r.id].year.max() - 1950) / 76, 0, 1)) for r in FD.itertuples()}
f1 = Sport("f1", "F1")
f1.setup(FD.set_index("id").name.to_dict(), SE.groupby("driverId").year.min().to_dict(), SE.groupby("driverId").year.max().to_dict(), fame)
races = RR[RR.positionNumber.notna()]
ST = RR[~RR.positionText.astype(str).isin(["DNQ", "DNPQ", "DNP", "EX", "DNS"])]              # actually started the race
for c, n in ST.groupby("constructorId").driverId.nunique().items():
    if n >= 15: f1.add(f"Has raced for {cn.get(c, c)}", "Team", ST[ST.constructorId == c].driverId)
win = RR[RR.positionNumber == 1]
for c in win.constructorId.value_counts().head(12).index: f1.add(f"Has won a race for {cn.get(c, c)}", "Team win", win[win.constructorId == c].driverId)
bypf = ST.groupby("driverId").constructorId.apply(set); topc = [c for c, n in ST.groupby("constructorId").driverId.nunique().items() if n >= 25]
prs = []
for a, b in itertools.combinations(topc, 2):
    ids = bypf[bypf.apply(lambda s: a in s and b in s)].index
    if 15 <= len(ids) <= 120: prs.append((a, b, ids))
for k in rng.permutation(len(prs))[:30]:
    a, b, ids = prs[k]; f1.add(f"Has raced for both {cn.get(a, a)} and {cn.get(b, b)}", "Two teams", ids)
f1.add("Has won a Grand Prix", "Career", win.driverId)
f1.add("Has won the World Championship", "Career", FD[FD.totalChampionshipWins > 0].id)
f1.add("Has taken a pole position", "Career", FD[FD.totalPolePositions > 0].id)
f1.add("Has finished on the podium", "Career", FD[FD.totalPodiums > 0].id)
f1.add("Has started 150 Grands Prix", "Career", FD[FD.totalRaceStarts >= 150].id)
f1.add("Has started 100 Grands Prix", "Career", FD[FD.totalRaceStarts >= 100].id)
f1.add("Has set a fastest lap", "Career", FD[FD.totalFastestLaps > 0].id)
f1.add("Has scored points in F1", "Career", FD[FD.totalPoints > 0].id, era="since 1990")
COU = pd.read_csv("raw/f1/f1db-countries.csv").set_index("id").name.to_dict()
for nat, n in FD.nationalityCountryId.value_counts().items():
    if n >= 15: f1.add(f"Is from {({'United States of America': 'the USA', 'United Kingdom': 'the UK'}).get(COU.get(nat, nat), COU.get(nat, nat))}", "Nationality", FD[FD.nationalityCountryId == nat].id)
for dec in (1980, 1990, 2000, 2010, 2020):
    d = SE[(SE.year >= dec) & (SE.year <= dec + 9)]
    f1.add(f"Raced in the {dec}s", "Era", d.driverId)
    w = win[(win.year >= dec) & (win.year <= dec + 9)]; f1.add(f"Won a race in the {dec}s", "Era", w.driverId)


# ======================= COLLEGE BASKETBALL (ESPN, since 2003) =======================
MB = pd.read_pickle("mbb_box.pkl"); MB = MB[MB.minutes.fillna(0) > 0].copy()
MB["pid"] = "b" + MB.athlete_id.astype(str)
SCH = MB.drop_duplicates("team_id").set_index("team_id").team_location.to_dict()
NCm = pd.read_pickle("nba_core.pkl"); NCm["school"] = NCm.college_id.map(SCH)
nba_names = set(zip(NCm.display_name, NCm.school))
mbs = MB.groupby(["pid", "season"]).agg(team=("team_location", lambda x: x.value_counts().index[0]), g=("points", "size"), p=("points", "mean"), r=("rebounds", "mean"), a=("assists", "mean")).reset_index()
names = MB.sort_values("season").drop_duplicates("pid", keep="last").set_index("pid").athlete_display_name.to_dict()
first = MB.groupby("pid").season.min().map(lambda y: y - 1).to_dict(); last = MB.groupby("pid").season.max().to_dict()
pts_c = MB.groupby("pid").points.sum(); g_c = MB.groupby("pid").size(); tm_last = mbs.sort_values("season").drop_duplicates("pid", keep="last").set_index("pid").team.to_dict()
nba_fame_by_name = {nba.players[nba.IDX[q]][0]: nba.FAME[q] for q in nba.ids}   # pro fame carries over to their college careers
fame = {p: np.log1p(g_c.get(p, 0)) + pts_c.get(p, 0) / 800 + ((4 + 1.5 * nba_fame_by_name.get(names[p], 0)) if (names[p], tm_last.get(p)) in nba_names else 0) + 1.2 * np.clip((last.get(p, 2003) - 2003) / 24, 0, 1) for p in names}
mbb = Sport("mbb", "College basketball"); mbb.setup(names, first, last, fame)
topS = mbs.groupby("team").pid.nunique().sort_values(ascending=False)
majors = [t for t in ["Duke", "Kentucky", "North Carolina", "Kansas", "UCLA", "Villanova", "Gonzaga", "Michigan State", "Arizona", "Louisville", "Syracuse", "Connecticut", "UConn",
          "Indiana", "Florida", "Ohio State", "Michigan", "Texas", "Baylor", "Virginia", "Wisconsin", "Purdue", "Oregon", "Tennessee", "Auburn", "Alabama", "Houston",
          "Marquette", "Creighton", "Xavier", "Georgetown", "Memphis", "Illinois", "Iowa State", "Maryland", "Arkansas", "LSU", "USC", "Texas Tech", "Notre Dame", "Wake Forest",
          "NC State", "Miami", "Oklahoma", "Iowa", "Pittsburgh", "Cincinnati", "West Virginia", "Butler", "San Diego State", "St. John's", "Seton Hall", "Providence", "Saint Mary's"] if t in topS.index]
for t in majors: mbb.add(f"Played for {t}", "School", mbs[mbs.team == t].pid, era="since 2003")
byp_m = mbs.groupby("pid").team.apply(set); prs = []
for a, b in itertools.combinations(majors, 2):
    ids = byp_m[byp_m.apply(lambda s: a in s and b in s)].index
    if len(ids) >= 30: prs.append((a, b, ids))
for a, b, ids in prs[:40]: mbb.add(f"Played for both {a} and {b}", "Two schools", ids, era="since 2003")
mbb.add("Scored 40 points in a game", "Big game", MB[MB.points >= 40].pid, era="since 2003")
mbb.add("Scored 35 points in a game", "Big game", MB[MB.points >= 35].pid, era="since 2003")
mbb.add("Grabbed 20 rebounds in a game", "Big game", MB[MB.rebounds >= 20].pid, era="since 2003")
mbb.add("Had 15 assists in a game", "Big game", MB[MB.assists >= 15].pid, era="since 2003")
q = mbs[mbs.g >= 20]
mbb.add("Averaged 20 points in a season", "Season", q[q.p >= 20].pid, era="since 2003")
mbb.add("Averaged 10 rebounds in a season", "Season", q[q.r >= 10].pid, era="since 2003")
for t in majors[:25]: mbb.add(f"Played for {t} and made the NBA", "Pros", [p for p in mbs[mbs.team == t].pid.unique() if (names[p], tm_last.get(p)) in nba_names], era="since 2003")
teammates(mbb, mbs.rename(columns={"team": "tm"}), "pid", "tm", "season", 30, 2008, era="since 2003", min_seasons=1, label=lambda n: f"Was a college teammate of {n}", ok=lambda p: (names[p], tm_last.get(p)) in nba_names and tm_last.get(p) in majors)   # big programs only: their teammates are knowable
# NBA players by college (uses the same ESPN school ids)

# Final Four and national titles: the title game is the season's last postseason game, the semifinals two days earlier
_pb = pd.concat([pd.read_parquet(f, columns=["game_id", "season", "season_type", "game_date", "athlete_id", "minutes", "team_location", "team_winner"])
                 for f in sorted(glob.glob("raw/mbb/pb_*.parquet"))])
_pb = _pb[(_pb.season_type == 3) & (_pb.minutes.fillna(0) > 0)].copy(); _pb["d"] = pd.to_datetime(_pb.game_date).dt.normalize(); _pb["pid"] = "b" + _pb.athlete_id.astype(str)
_ff, _ch = [], []
for y_, g_ in _pb.groupby("season"):
    D = g_.d.max(); fin = g_[g_.d == D]; semi = g_[g_.d == D - pd.Timedelta(days=2)]
    if fin.game_id.nunique() != 1 or semi.game_id.nunique() != 2: continue        # no tournament (2020) or odd dates
    _ff += list(fin.pid) + list(semi.pid); _ch += list(fin[fin.team_winner.astype(str).str.lower() == "true"].pid)
mbb.add("Played in a Final Four", "Champion", _ff, era="since 2003")
mbb.add("Won a national championship", "Champion", _ch, era="since 2003")

# ----------------------- college basketball head coaches (Sports-Reference school pages via Colab; interims count) -----------------------
_CB = json.load(_gz.open("raw/coaches/cbb.json.gz"))
_SLUGNAME = {"connecticut": "UConn", "louisiana-state": "LSU", "north-carolina-state": "NC State", "southern-california": "USC", "nevada-las-vegas": "UNLV",
             "saint-marys-ca": "Saint Mary's", "st-johns-ny": "St. John's", "miami-fl": "Miami", "brigham-young": "BYU", "mississippi": "Ole Miss",
             "virginia-commonwealth": "VCU", "loyola-il": "Loyola Chicago", "ucla": "UCLA"}
_cr = []
for sl, rows in _CB["cbb"].items():
    sch = _SLUGNAME.get(sl, " ".join(w.capitalize() for w in sl.split("-")))
    for r in rows:
        se = r["cells"].get("season", "")
        if not re.match(r"^\d{4}-\d{2}$", se): continue
        y = int(se[:4]) + 1; rnd = r["cells"].get("round_max", "")
        ff = "National Semifinal" in rnd or "National Final" in rnd; won = rnd.startswith("Won") and "National Final" in rnd
        for cid, nm, wl in r["coaches"]: _cr.append((cid, nm, sch, y, ff, won, sum(wl[:2]) if wl else 0))
BC = pd.DataFrame(_cr, columns=["cid", "name", "school", "season", "ff", "won", "g"])
# a Final Four / title season belongs to the coach who finished it (most games that season), not a mid-season fill-in
_main = BC.sort_values("g").groupby(["school", "season"]).tail(1)
_bcs = BC.groupby("cid").agg(n=("season", "nunique"), y0=("season", "min"), y1=("season", "max"))
_bname = BC.drop_duplicates("cid").set_index("cid").name.to_dict()
_bv = {c: _CB["views"].get(_CB["titles"]["cbb"].get(n), 0) * 365 / _CB.get("views_days", 365) for c, n in _bname.items()}
_bff = _main[_main.ff].cid.value_counts(); _bwon = _main[_main.won].cid.value_counts()
cbbc = Sport("cbbcoach", "College basketball coaches")
cbbc.setup(_bname, _bcs.y0.to_dict(), _bcs.y1.to_dict(),
           {c: np.log1p(_bcs.n[c]) * 2 + 1.2 * _bff.get(c, 0) + 2.5 * _bwon.get(c, 0) + 1.5 * np.clip((_bcs.y1[c] - 1970) / 56, 0, 1) for c in _bcs.index})
cbbc.VIEWS = {c: v for c, v in _bv.items() if v}; cbbc.blend_views()
BW2 = dict(pool=cbbc, who="A COLLEGE BASKETBALL HEAD COACH")
for sc in sorted(BC.school.unique()):
    since = 1970 if BC[(BC.school == sc) & (BC.season >= 1970)].cid.nunique() >= 10 else 1950   # programs with long tenures reach further back
    _x = BC[(BC.school == sc) & (BC.season >= since)]; _g = _x.groupby("cid").g.sum()
    mbb.add(f"Coached {sc}", "Coach team", _x.cid, era=f"since {since}", floor={c: 5 for c in _g[_g < 10].index}, **BW2)
mbb.add("Coached in a Final Four", "Coach title", _main[_main.ff & (_main.season >= 1985)].cid, era="since 1985", **BW2)
mbb.add("Won a national championship", "Coach title", _main[_main.won & (_main.season >= 1985)].cid, era="since 1985", **BW2)
_bns = BC[BC.season >= 1970].groupby("cid").school.nunique()

# ======================= COLLEGE FOOTBALL (ESPN, since 2004) =======================
CF = pd.read_pickle("cfb_box.pkl"); CF["school"] = CF.team_id.map(SCH); CF = CF[CF.school.notna()].copy()
CF["pid"] = "f" + CF.athlete_id.astype(str)
for c in ["passingYards", "passingTouchdowns", "rushingYards", "rushingTouchdowns", "receptions", "receivingYards", "receivingTouchdowns", "totalTackles", "sacks", "interceptions"]:
    if c in CF.columns: CF[c] = pd.to_numeric(CF[c], errors="coerce")
CF.loc[CF.category != "interceptions", "interceptions"] = np.nan; CF.loc[CF.category != "passing", "passingTouchdowns"] = CF.loc[CF.category != "passing", "passingTouchdowns"]
cfs = CF.groupby(["pid", "season"]).agg(school=("school", lambda x: x.value_counts().index[0]), py=("passingYards", "sum"), ptd=("passingTouchdowns", "sum"), ry=("rushingYards", "sum"),
      rtd=("rushingTouchdowns", "sum"), rec=("receptions", "sum"), recy=("receivingYards", "sum"), rectd=("receivingTouchdowns", "sum"), sk=("sacks", "sum"), it=("interceptions", "sum")).reset_index()
names = CF.sort_values("season").drop_duplicates("pid", keep="last").set_index("pid").athlete_name.to_dict()
first = CF.groupby("pid").season.min().to_dict(); last = CF.groupby("pid").season.max().to_dict()
CALIAS = {"Southern California": "USC", "Mississippi": "Ole Miss", "North Carolina State": "NC State", "Brigham Young": "BYU", "Louisiana State": "LSU",
          "Texas Christian": "TCU", "Miami (FL)": "Miami", "Pitt": "Pittsburgh", "Central Florida": "UCF"}     # nflverse spells schools differently across years
R["college_n"] = R.college.fillna("").str.split(";").str[0].str.strip().replace(CALIAS)
_rc = R[["full_name", "college"]].dropna(); _rc = _rc.assign(c=_rc.college.str.split(";")).explode("c")
nfl_names = set(zip(R.full_name, R.college_n.fillna(""))) | {(n, CALIAS.get(c.strip(), c.strip())) for n, c in zip(_rc.full_name, _rc.c)}
nfl_fame_by_name = {nfl.players[nfl.IDX[q]][0]: nfl.FAME[q] for q in nfl.ids}
# NFL players who never show up in college box scores (offensive linemen, most special teamers, low-stat defenders):
# add them from the NFL rosters' college field so "Played for USC (and made the NFL)" accepts e.g. Austin Jackson.
CMAJ_ALL = ["Alabama", "Georgia", "Ohio State", "Clemson", "LSU", "Michigan", "Oklahoma", "Texas", "USC", "Notre Dame", "Florida", "Florida State", "Oregon", "Penn State",
        "Auburn", "Tennessee", "Miami", "Texas A&M", "Wisconsin", "Iowa", "Nebraska", "Michigan State", "Washington", "Stanford", "UCLA", "TCU", "Baylor", "Ole Miss",
        "Mississippi State", "Arkansas", "South Carolina", "Kentucky", "Missouri", "Utah", "Oklahoma State", "Virginia Tech", "West Virginia", "Louisville", "Boise State",
        "Kansas State", "Arizona State", "Pittsburgh", "North Carolina", "NC State", "Minnesota", "Purdue", "Iowa State", "Colorado", "Texas Tech", "BYU"]
_rk = R[R.gsis_id.notna()].groupby("gsis_id").agg(name=("full_name", "last"), college=("college_n", "last"), rookie=("season", "min"))
_sl = cfs.sort_values("season").drop_duplicates("pid", keep="last").set_index("pid").school.to_dict()
_have = {(names[q], _sl.get(q, "")) for q in names}
extra_school = {}
for g, row in _rk.iterrows():
    if row.college in CMAJ_ALL and row.rookie >= 2007 and (row["name"], row.college) not in _have:
        q = "n" + str(g); names[q] = row["name"]; first[q] = int(row.rookie) - 4; last[q] = int(row.rookie) - 1
        extra_school[q] = row.college
print("cfb: added", len(extra_school), "NFL players with no college box-score stats")
car_ = cfs.groupby("pid")[["py", "ry", "recy", "sk"]].sum(); sch_last = cfs.sort_values("season").drop_duplicates("pid", keep="last").set_index("pid").school.to_dict()
fame = {}
for p in names:
    c = car_.loc[p] if p in car_.index else None
    if p in extra_school: fame[p] = 4 + 1.5 * nfl_fame_by_name.get(names[p], 0) + 1.2 * np.clip((last.get(p, 2004) - 2004) / 22, 0, 1); continue
    fame[p] = (np.log1p(cfs[cfs.pid == p].shape[0]) if False else 0) + (0 if c is None else c.py / 3000 + c.ry / 1500 + c.recy / 1500 + c.sk / 10) + ((4 + 1.5 * nfl_fame_by_name.get(names[p], 0)) if (names[p], sch_last.get(p, "")) in nfl_names else 0) + 1.2 * np.clip((last.get(p, 2004) - 2004) / 22, 0, 1)
cfb = Sport("cfb", "College football"); cfb.setup(names, first, last, fame)
cmaj = [t for t in ["Alabama", "Georgia", "Ohio State", "Clemson", "LSU", "Michigan", "Oklahoma", "Texas", "USC", "Notre Dame", "Florida", "Florida State", "Oregon", "Penn State",
        "Auburn", "Tennessee", "Miami", "Texas A&M", "Wisconsin", "Iowa", "Nebraska", "Michigan State", "Washington", "Stanford", "UCLA", "TCU", "Baylor", "Ole Miss",
        "Mississippi State", "Arkansas", "South Carolina", "Kentucky", "Missouri", "Utah", "Oklahoma State", "Virginia Tech", "West Virginia", "Louisville", "Boise State",
        "Kansas State", "Arizona State", "Pittsburgh", "North Carolina", "NC State", "Minnesota", "Purdue", "Iowa State", "Colorado", "Texas Tech", "BYU"] if t in set(cfs.school)]
for t in cmaj: cfb.add(f"Played for {t}", "School", list(cfs[cfs.school == t].pid) + [q for q, sc in extra_school.items() if sc == t], era="since 2004")
for t in cmaj[:30]: cfb.add(f"Played for {t} and made the NFL", "Pros", [p for p in cfs[cfs.school == t].pid.unique() if (names[p], t) in nfl_names or (names[p], sch_last.get(p, "")) in nfl_names] + [q for q, sc in extra_school.items() if sc == t], era="since 2004")
for col, v, t in [("py", 4000, "Threw for 4,000 yards in a season"), ("py", 3500, "Threw for 3,500 yards in a season"), ("ptd", 35, "Threw 35 touchdown passes in a season"),
                  ("ry", 1500, "Ran for 1,500 yards in a season"), ("ry", 1200, "Ran for 1,200 yards in a season"), ("rtd", 18, "Ran for 18 touchdowns in a season"),
                  ("recy", 1300, "Had 1,300 receiving yards in a season"), ("rec", 90, "Caught 90 passes in a season"), ("rectd", 13, "Caught 13 touchdown passes in a season"),
                  ("sk", 11, "Had 11 sacks in a season"), ("it", 6, "Had 6 interceptions in a season")]:
    cfb.add(t, "Season", cfs[cfs[col] >= v].pid, era="since 2004")
teammates(cfb, cfs, "pid", "school", "season", 30, 2008, era="since 2004", min_seasons=2, label=lambda n: f"Was a college teammate of {n}", ok=lambda p: (names[p], sch_last.get(p, "")) in nfl_names and sch_last.get(p, "") in cmaj)
# NFL "Played college football at X" uses the roster's last college only; add every school a transfer played for (Kyler Murray: Texas A&M, then Oklahoma),
# matched by name when that same college player's schools include the roster college
_cfsch = cfs.groupby("pid").school.apply(set); _cfby = {}
for q, ss in _cfsch.items(): _cfby.setdefault(names[q], []).append(ss)
_nlast = R.sort_values("season").drop_duplicates("pid", keep="last").set_index("pid")[["full_name", "college_n"]]
_nsch = {}
for q, row in _nlast.iterrows():
    c = [ss for ss in _cfby.get(row.full_name, []) if row.college_n in ss]
    if len(c) == 1 and len(c[0]) > 1: _nsch[q] = c[0]
_added = 0
for pr in nfl.prompts:
    if pr["k"] == "College":
        lab = pr["t"][len("Played college football at "):]; ln = CALIAS.get(lab, lab)
        extra = [q for q, ss in _nsch.items() if ln in ss and q in nfl.IDX and q not in set(pr["ids"])]
        pr["ids"] = list(pr["ids"]) + extra; _added += len(extra)
        _fin = {q for q in pr["ids"] if q in _nlast.index and CALIAS.get(_nlast.at[q, "college_n"], _nlast.at[q, "college_n"]) != ln}
        pr["_xfer"] = {q for q in _fin if q in _nsch}   # an earlier school, not the one he's known for
print("nfl: transfer colleges added", _added, "answers across", len(_nsch), "players")

# national champions (BCS / College Football Playoff) and Heisman winners, seasons in our data (2004 title vacated; skipped)
CFB_CHAMP = {2005: "Texas", 2006: "Florida", 2007: "LSU", 2008: "Florida", 2009: "Alabama", 2010: "Auburn", 2011: "Alabama", 2012: "Alabama",
             2013: "Florida State", 2014: "Ohio State", 2015: "Alabama", 2016: "Clemson", 2017: "Alabama", 2018: "Clemson", 2019: "LSU", 2020: "Alabama",
             2021: "Georgia", 2022: "Georgia", 2023: "Michigan", 2024: "Ohio State", 2025: "Indiana"}
_cc = cfs[[CFB_CHAMP.get(y_) == sc for y_, sc in zip(cfs.season, cfs.school)]]
cfb.add("Won a national championship", "Champion", _cc.pid, era="since 2005")
HEISMAN = ["Matt Leinart", "Reggie Bush", "Troy Smith", "Tim Tebow", "Sam Bradford", "Mark Ingram", "Cam Newton", "Robert Griffin III", "Johnny Manziel",
           "Jameis Winston", "Marcus Mariota", "Derrick Henry", "Lamar Jackson", "Baker Mayfield", "Kyler Murray", "Joe Burrow", "DeVonta Smith", "Bryce Young",
           "Caleb Williams", "Jayden Daniels", "Travis Hunter", "Fernando Mendoza"]
_byname = {}
for p_, (n_, a_, b_) in zip(cfb.ids, cfb.players): _byname.setdefault(n_, []).append(p_)
_hz = [max(_byname[n], key=lambda q: cfb.FAME[q]) for n in HEISMAN if n in _byname]
print("heisman matched", len(_hz), "of", len(HEISMAN), [n for n in HEISMAN if n not in _byname])
cfb.add("Won the Heisman Trophy", "Award", _hz, era="since 2004")

# ----------------------- college football head coaches (each program's Wikipedia coach list; interims count) -----------------------
import io as _io
def _cfb_coach_rows():
    pages = json.load(_gz.open("raw/coaches/cfb_pages.json.gz")); out = []
    for school, pg in pages.items():
        if not pg.get("html"): continue
        best = None
        for t in pd.read_html(_io.StringIO(pg["html"])):
            cols = [str(c) if not isinstance(c, tuple) else str(c[-1]) for c in t.columns]; t.columns = cols
            nc = next((c for c in cols if re.match(r"^(Name|Coach|Head coach)", c, re.I)), None)
            yc = next((c for c in cols if re.match(r"^(Term|Year|Season|Tenure)", c, re.I) and not re.match(r"^Seasons?$", c, re.I)), None) \
                 or next((c for c in cols if re.match(r"^Seasons?", c, re.I)), None)
            if nc and yc and len(t) > (len(best[0]) if best else 5): best = (t, nc, yc, next((c for c in cols if c.upper() in ("GC", "G", "GAMES")), None))
        if not best: print("cfb coaches: no table for", school); continue
        t, nc, yc, gc = best
        for _, r in t.iterrows():
            nm = re.sub(r"\[.*?\]|[†‡*§#^]", "", str(r[nc])).strip()
            if not nm or nm.lower() in ("nan", "name", "vacant") or re.search(r"no coach|none", nm, re.I): continue
            if len(nm.split()) > 6 or re.search(r"\b(served|after|was|were|fired|game|season)\b", nm): continue   # footnote sentences, not names
            if gc and str(r[gc]).strip() in ("—", "-", "0", "nan"): continue           # hired but never coached a game
            yrs = set()
            for a_, b_ in re.findall(r"(\d{4})\s*(?:[–\-]\s*(\d{4}|present))?", str(r[yc])):
                a_ = int(a_); b_ = 2026 if b_ == "present" else int(b_) if b_ else a_
                if 1869 <= a_ <= b_ <= 2026: yrs |= set(range(a_, b_ + 1))
            for one in re.split(r"\s*(?:&| and |/)\s*", nm):
                one = re.sub(r"\s*\(.*?\)", "", one).strip()
                if one: out += [(one, school, y) for y in yrs]
    # programs whose coach list lives in the main football article (Michigan State, Minnesota, Boise State, UCF): the table that lists
    # each coach once, read from the column that actually holds years ("Years" is a range on one page and a count on another)
    if os.path.exists("raw/nflpages/extra.json.gz"):
        for school, pg in json.load(_gz.open("raw/nflpages/extra.json.gz"))["cfb_extra"].items():
            best = None
            for t in pd.read_html(_io.StringIO(pg.get("html") or "<table></table>")):
                cols = [str(c) if not isinstance(c, tuple) else str(c[-1]) for c in t.columns]; t.columns = cols
                nc = next((c for c in cols if re.match(r"^(Name|Coach|Head coach)", c, re.I)), None)
                if not nc or len(t) < 5 or t[nc].nunique() < 0.7 * len(t): continue      # bowl and season tables repeat the coach
                if not any(re.search(r"record|pct|^(gc|ow|w|wins)$", c, re.I) for c in cols): continue   # staff lists have no record column
                for c in cols:
                    if c == nc: continue
                    sc = t[c].astype(str).str.contains(r"\b(?:18|19|20)\d\d\b").mean()
                    if sc > 0.8 and (best is None or len(t) > len(best[0])): best = (t, nc, c)
            if not best: print("cfb coaches: no table for", school); continue
            t, nc, yc = best
            for _, r in t.iterrows():
                nm = re.sub(r"\[.*?\]|[†‡*§#^]", "", str(r[nc])).strip()
                if not nm or nm.lower() in ("nan", "name", "vacant") or re.search(r"no coach|none|^totals?$", nm, re.I): continue
                yrs = set()
                for a_, b_ in re.findall(r"(\d{4})\s*(?:[–\-]\s*(\d{4}|present))?", str(r[yc])):
                    a_ = int(a_); b_ = 2026 if b_ == "present" else int(b_) if b_ else a_
                    if 1869 <= a_ <= b_ <= 2026: yrs |= set(range(a_, b_ + 1))
                for one in re.split(r"\s*(?:&| and |/)\s*", nm):
                    one = re.sub(r"\s*\(.*?\)", "", one).strip()
                    if one: out += [(one, school, y) for y in yrs]
    return pd.DataFrame(out, columns=["coach", "school", "season"]).drop_duplicates()
FC = _cfb_coach_rows(); print("cfb coach rows", len(FC), FC.school.nunique(), "schools")
_CF = json.load(_gz.open("raw/coaches/cfb.json.gz"))
_fv = {n: _CF["views"].get(t, 0) * 365 / _CF.get("views_days", 365) for n, t in _CF["titles"].items()}
if os.path.exists("raw/nflpages/extra.json.gz"):                                   # coaches of the 4 programs added later: readership by link
    from bs4 import BeautifulSoup as _BS
    _X = json.load(_gz.open("raw/nflpages/extra.json.gz")); _xs = 365 / _X.get("views_days", 365)
    for _pg in _X["cfb_extra"].values():
        for _a in _BS(_pg.get("html") or "", "html.parser").find_all("a", href=True):
            _h = _a["href"]
            if _h.startswith("/wiki/") and ":" not in _h:
                _n = _a.get_text(" ", strip=True); _v = _X["views"].get(urllib.parse.unquote(_h[6:]).split("#")[0], 0) * _xs
                if _n and _v > _fv.get(_n, 0): _fv[_n] = _v
_fcs = FC.groupby("coach").agg(n=("season", "nunique"), y0=("season", "min"), y1=("season", "max"))
_ten = FC.groupby(["coach", "school"]).season.nunique().to_dict()          # a title season goes to the program's main coach, not interims
_ftitle = FC[[CFB_CHAMP.get(y_) == sc for y_, sc in zip(FC.season, FC.school)]]
_ftitle = _ftitle.assign(t=[_ten[(c_, s_)] for c_, s_ in zip(_ftitle.coach, _ftitle.school)]).sort_values("t").groupby(["school", "season"]).tail(1)
cfbc = Sport("cfbcoach", "College football coaches")
cfbc.setup({c: c for c in _fcs.index}, _fcs.y0.to_dict(), _fcs.y1.to_dict(),
           {c: np.log1p(_fcs.n[c]) * 2 + 2.5 * (_ftitle.coach == c).sum() + 1.5 * np.clip((_fcs.y1[c] - 1970) / 56, 0, 1) for c in _fcs.index})
cfbc.VIEWS = {c: _fv[c] for c in _fcs.index if _fv.get(c)}; cfbc.blend_views()
FW = dict(pool=cfbc, who="A COLLEGE FOOTBALL HEAD COACH")
for sc in sorted(FC.school.unique()):
    cfb.add(f"Coached {sc}", "Coach team", FC[(FC.school == sc) & (FC.season >= 1970)].coach, era="since 1970", **FW)
cfb.add("Won a national championship", "Coach title", _ftitle.coach, era="since 2005", **FW)
_nsch = FC[FC.season >= 1970].groupby("coach").school.nunique()

# ======================= INTERNATIONAL SOCCER =======================
NP = pd.read_csv("raw/soc/player_national_performances.csv", usecols=["player_id", "team_id", "matches", "goals"])
PF = pd.read_csv("raw/soc/player_profiles.csv", usecols=["player_id", "player_name", "citizenship"], low_memory=False)
PF["name"] = PF.player_name.str.replace(r"\s*\(\d+\)$", "", regex=True); PF = PF[PF.name.notna()]
PF["nat"] = PF.citizenship.fillna("").str.split(r"\s{2,}").str[0]
NP = NP.merge(PF[["player_id", "nat"]], on="player_id")
# the senior team for a country is its national-team id with the most-capped players
tnat = NP.groupby("team_id").nat.agg(lambda x: x.value_counts().index[0]); tmax = NP.groupby("team_id").matches.max()
senior = {}
for t in tnat.index:
    c = tnat[t]
    if c and (c not in senior or tmax[t] > tmax[senior[c]]): senior[c] = t
SN = NP[NP.team_id.isin(set(senior.values()))].copy(); SN["country"] = SN.team_id.map({v: k for k, v in senior.items()})
SN = SN[SN.matches > 0]
# Transfermarkt's national-team table is missing many current stars (Hakimi, Bellingham, Wirtz, Palmer...). Fill in from the
# martj42 international results data: anyone who scored or assisted for a country since 2005 certainly played for it.
import unicodedata
def _norm(x): return "".join(ch for ch in unicodedata.normalize("NFKD", str(x)) if not unicodedata.combining(ch)).lower().strip()
GS = pd.read_csv("raw/intl_results/goalscorers.csv"); GS = GS[GS.date >= "2005"]
TEAM2TM = {"Bosnia and Herzegovina": "Bosnia-Herzegovina", "Curaçao": "Curacao", "Gambia": "The Gambia", "Ivory Coast": "Cote d'Ivoire",
           "Republic of Ireland": "Ireland", "South Korea": "Korea, South", "North Korea": "Korea, North", "Turkey": "Türkiye", "Taiwan": "Chinese Taipei", "Hong Kong": "Hongkong"}
GS["tm"] = GS.team.map(lambda t: TEAM2TM.get(t, t))
ev = pd.concat([GS.loc[~GS.own_goal.astype(bool), ["date", "tm", "scorer"]].rename(columns={"scorer": "who"}).assign(g=1),
                GS.loc[GS.assist.notna(), ["date", "tm", "assist"]].rename(columns={"assist": "who"}).assign(g=0)])
ev["key"] = ev.who.map(_norm)
PFc = PF[["player_id", "name", "citizenship"]].copy(); PFc["key"] = PFc.name.map(_norm)
PFc["cits"] = PFc.citizenship.fillna("").str.split(r"\s{2,}")
PFc = PFc.explode("cits"); PFc["mv"] = PFc.player_id.map(lambda q: MV.get(q, 0) or 0)
best = PFc.sort_values("mv", ascending=False).drop_duplicates(["key", "cits"])            # same name + same country: take the best-known player
ev = ev.merge(best[["key", "cits", "player_id"]], left_on=["key", "tm"], right_on=["key", "cits"])
ev = ev[ev.tm.isin(senior)]
have = set(zip(SN.player_id, SN.country))
add_rows = []
for (pid_, c), x in ev.groupby(["player_id", "tm"]):
    if (pid_, c) in have: continue
    add_rows.append({"player_id": pid_, "team_id": senior[c], "matches": x.date.nunique(), "goals": int(x.g.sum()), "nat": c, "country": c})
print("intl: added", len(add_rows), "player-country records from goalscorers/assists")
SN = pd.concat([SN, pd.DataFrame(add_rows)], ignore_index=True)
caps = SN.groupby("player_id").matches.sum(); igoals = SN.groupby("player_id").goals.sum()
nm_ = PF.set_index("player_id").name.to_dict()
ip = [p for p in caps.index if p in nm_]
fame = {p: np.log1p(caps.get(p, 0)) * 1.6 + igoals.get(p, 0) / 10 + 3.6 * max(0.0, np.log10((MV.get(p, 0) or 0) + 1) - 5) for p in ip}
intl_pool = Sport("intl", "International"); intl_pool.setup({p: nm_[p] for p in ip}, {}, {}, fame)
intl = intl_pool
SN["country"] = SN.country.replace({"Korea, South": "South Korea", "Cote d'Ivoire": "Ivory Coast", "Ireland": "the Republic of Ireland", "United States": "the USA", "Netherlands": "the Netherlands"})
KNOWN = ["Argentina", "Brazil", "England", "France", "Germany", "Spain", "Italy", "Portugal", "the Netherlands", "Belgium", "Croatia", "Uruguay", "Colombia", "Mexico",
         "the USA", "Canada", "Japan", "South Korea", "Denmark", "Sweden", "Switzerland", "Poland", "Wales", "Scotland", "the Republic of Ireland", "Nigeria", "Senegal",
         "Morocco", "Ghana", "Ivory Coast", "Egypt", "Australia", "Türkiye", "Norway", "Serbia", "Chile", "Cameroon"]   # well-known national teams only
cc = SN[SN.country.isin(KNOWN)].groupby("country").player_id.nunique().sort_values(ascending=False)
for c in cc.index[:45]:
    x = SN[SN.country == c]
    intl.add(f"Played for {c}", "Country", x.player_id, era="since 2005")
    intl.add(f"Scored for {c}", "Country goals", x[x.goals > 0].player_id, era="since 2005")
    intl.add(f"Won 30 caps for {c}", "Caps", x[x.matches >= 30].player_id, era="since 2005")
for v, t in [(100, "Won 100 international caps"), (50, "Won 50 international caps")]:
    intl.add(t, "Caps", caps[caps >= v].index, era="since 2005")
for v, t in [(30, "Scored 30 international goals"), (15, "Scored 15 international goals")]:
    intl.add(t, "Goals", igoals[igoals >= v].index, era="since 2005")
epl_ids = set(SP[SP.competition_id == "GB1"].player_id); liga_ids = set(SP[SP.competition_id == "ES1"].player_id)
for c in cc.index[:25]:
    x = set(SN[SN.country == c].player_id)
    intl.add(f"Played for {c} and in the Premier League", "Country + league", x & epl_ids, era="since 2005")
    intl.add(f"Played for {c} and in LaLiga", "Country + league", x & liga_ids, era="since 2005")

# ======================= bank + calendar =======================
from has_form import has_form   # career facts read "who has won...", decade-pinned ones stay in plain past
MIN_ANSWERS = 30   # a prompt needs at least this many valid answers to be fair
SPORTS = {"mlb": mlb, "nfl": nfl, "nba": nba, **{k: socbanks[k] for k in SOCL}, "f1": f1, "cfb": cfb, "mbb": mbb, "intl": intl}
for _s in (mlb, nfl, nba): _s.blend_views()
banks = {k: s.bank(lo=(25 if k == "f1" else 20 if k == "mbb" else MIN_ANSWERS), hi=2600) for k, s in SPORTS.items()}   # F1 grids and college hoops rosters are small   # F1 has a much smaller field of drivers
# days already played (and tomorrow, for time zones ahead) are frozen: same prompts and answers, indices remapped to the new player lists
import datetime as _dt
FREEZE = int(os.environ.get("FREEZE", (_dt.date.today() - _dt.date(2026, 11, 8)).days + 2))
_POOLOF = {"mlb": "mlb", "nfl": "nfl", "nba": "nba", "f1": "f1", "cfb": "cfb", "mbb": "mbb", "intl": "intl"}
_oldpl = {}; _frozen = []
for d in range(1, FREEZE + 1):
    f = f"{OUT}/days/{d}.json"
    if os.path.exists(f): _frozen.append(json.load(open(f)))
for f in glob.glob(f"{OUT}/players_*.json"): _oldpl[f.split("players_")[1][:-5]] = json.load(open(f))
for s in (mlb, nfl, nba, soc, f1, nflc, mlbm, nbac, socc, cfbc, cbbc, cfb, mbb, intl_pool):
    json.dump(s.players, open(f"{OUT}/players_{s.key}.json", "w"), separators=(",", ":"), ensure_ascii=False, allow_nan=False)
queues = {}
for k, bank in banks.items():
    by = {}
    for i, p in enumerate(bank): by.setdefault(p["k"], []).append(i)
    order = []
    for kind, ids in by.items():
        ids = list(rng.permutation(ids)); n = len(ids)
        w = STAT_WEIGHT if kind in STATKINDS else 1.0   # stat prompts are spread over a shorter stretch, so they come up more often
        order += [((j + rng.random()) / n / w, i) for j, i in enumerate(ids)]
    queues[k] = [i for _, i in sorted(order)]
# each day: one prompt from each sport (6) plus one extra from whichever sport has the most left
_newpl = {s.key: s.players for s in (mlb, nfl, nba, soc, f1, nflc, mlbm, nbac, socc, cfbc, cbbc, cfb, mbb, intl_pool)}
def _remap(pool, i):
    o = _oldpl[pool][i]; nw = _newpl[pool]
    if not hasattr(_remap, "ix"): _remap.ix = {}
    if pool not in _remap.ix:
        full, byn = {}, {}
        for j, e in enumerate(nw): full[tuple(e)] = j; byn.setdefault(e[0], []).append(j)
        _remap.ix[pool] = (full, byn)
    full, byn = _remap.ix[pool]
    if tuple(o) in full: return full[tuple(o)]
    c = byn.get(o[0], [])
    if len(c) == 1: return c[0]
    c = [j for j in c if nw[j][1] == o[1]]
    return c[0] if len(c) == 1 else None
_used = set()
for D_ in _frozen:
    for q in D_["prompts"]:
        pool = q.get("p") or _POOLOF.get(q["s"], "soc"); _used.add((q["s"], q["t"]))
        a = [[_remap(pool, i), t] for i, t in q["a"]]; lost = [x for x in a if x[0] is None]
        if lost: print("  frozen day: lost", len(lost), "answers in", q["t"])
        q["a"] = sorted(x for x in a if x[0] is not None); q["h"] = [j for j in (_remap(pool, i) for i in q["h"]) if j is not None]
for k in queues: queues[k] = [i for i in queues[k] if (k, has_form(banks[k][i]["t"])) not in _used]
for f in glob.glob(f"{OUT}/days/*.json"): os.remove(f)
for d, D_ in enumerate(_frozen): json.dump(D_, open(f"{OUT}/days/{d + 1}.json", "w"), separators=(",", ":"))
day = len(_frozen)
ORDER = list(banks)
while True:
    avail = [k for k in ORDER if queues[k]]
    if len(avail) < 5: break
    # rotate which leagues appear so each gets a fair share, favoring ones with more prompts left
    rot = sorted(avail, key=lambda k: (-(len(queues[k]) / max(1, len(banks[k]))), (ORDER.index(k) - day) % len(ORDER)))
    core = [k for k in ("mlb", "nfl", "nba") if k in avail]          # the big three every day
    plan = list(core); nsoc = 0
    for k in rot:
        if len(plan) >= 7: break
        if k in plan: continue
        if k in SOCL:                                                   # at most two soccer competitions a day
            if nsoc >= 2: continue
            nsoc += 1
        plan.append(k)
    while len(plan) < 7: plan.append(max(avail, key=lambda k: len(queues[k])))
    picks = []; need = list(DAY_MIX)
    for sp in sorted(plan, key=lambda k: min((banks[k][i]["_d"] for i in queues[k][:40]), default=0), reverse=True):   # sports that hold harder prompts pick first
        q = queues[sp]
        if not q: continue
        fresh = [i for i in q if not any(p["s"] == sp and p["k"] == banks[sp][i]["k"] for p in picks)] or q
        want = max(need) if need else 0
        # take the first prompt in queue order whose difficulty is still needed, the hardest slot first; otherwise the closest
        i = min(fresh[:60], key=lambda i: (abs(banks[sp][i]["_d"] - want), fresh.index(i)))
        q.remove(i); picks.append(banks[sp][i])
        d = banks[sp][i]["_d"]; need.remove(min(need, key=lambda x: abs(x - d)))
    if len(picks) < 7: break
    picks = sorted([picks[i] for i in rng.permutation(len(picks))], key=lambda p: p["_d"])
    json.dump({"prompts": [{k: (has_form(v) if k == "t" else v) for k, v in p.items() if not k.startswith("_")} for p in picks]}, open(f"{OUT}/days/{day + 1}.json", "w"), separators=(",", ":"))
    day += 1
json.dump({"start": "2026-11-08", "days": day}, open(f"{OUT}/calendar.json", "w"))
print(day, "days written")
for f in glob.glob(f"{OUT}/players_*.json"): print(f, os.path.getsize(f) // 1024, "KB")
sz = [os.path.getsize(f) for f in glob.glob(f"{OUT}/days/*.json")]; print("day files avg", sum(sz) // len(sz) // 1024, "KB, max", max(sz) // 1024, "KB")
pd.to_pickle(banks, "banks.pkl"); pd.to_pickle(STARLOG, "starlog.pkl")
pd.to_pickle({sp_.key: (sp_.VIEWS, sp_.GQ, sp_.NPOOL or len(sp_.ids), [e[0] for e in sp_.players], sp_.IDX) for sp_ in (mlb, nfl, nba)}, "fame.pkl")
