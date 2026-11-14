import re
# past-tense lead verb -> "has" + past participle, for career facts ("who has won an NBA title")
PP = {"Caught":"caught","Coached":"coached","Had":"had","Played":"played","Ran":"run","Threw":"thrown","Won":"won",
      "Averaged":"averaged","Grabbed":"grabbed","Scored":"scored","Drew":"drawn","Drove":"driven","Got":"collected",
      "Hit":"hit","Made":"made","Managed":"managed","Saved":"saved","Stole":"stolen","Struck":"struck","Blocked":"blocked",
      "Received":"received","Kept":"kept","Raced":"raced","Took":"taken","Finished":"finished","Started":"started",
      "Set":"set","Wore":"worn","Recorded":"recorded","Appeared":"appeared","Led":"led","Posted":"posted","Pitched":"pitched",
      "Rushed":"rushed","Passed":"passed","Sacked":"sacked","Intercepted":"intercepted","Earned":"earned","Reached":"reached"}
DECADE = re.compile(r"\bin the (\d{4})s\b")
def has_form(t):
    if t.startswith(("Has ", "Was ", "Is ", "Were ", "Also ")) and not t.startswith("Also played"): return t
    if DECADE.search(t): return t                          # pinned to a finished decade: plain past reads right
    if t.startswith("Also played"): return "Has also played" + t[len("Also played"):]
    w = t.split(" ", 1)
    if w[0] in PP: return "Has " + PP[w[0]] + ("" if len(w) == 1 else " " + w[1])
    return t
