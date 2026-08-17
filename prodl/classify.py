#!/usr/bin/env python3
"""Phase 1a: classify channel videos into race vs non-race, parse date/event/day."""
import re, csv, sys

rows = []
with open("raw_list.tsv", encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        vid, _, title = line.partition("\\t")  # yt-dlp emitted a literal backslash-t
        rows.append((vid, title))

# --- exclusion filter the user requested: winners / NADINE ---
def excluded_by_user(t):
    return bool(re.search(r"winners|nadine", t, re.I))

# --- non-race (drop) signals ---
DROP_PAT = re.compile(
    r"\b(interview|promo|promotional|the movie|opening ceremony|closing ceremony|"
    r"medal ceremony|prize ?giving|anniversary|racer.?s choice|wishing our|"
    r"discuss|reflects|talks 470|getting ready|rigging|preparation|morning prep|"
    r"back from|champion wall|sailing club|excitement from|downwind with|"
    r"start line tactics|bibs|measurements|winter series|master.?s cup - promo|"
    r"in port race)\b", re.I)

# technique/raw clip filename-style titles (mpg/flv or french technique words)
TECH_PAT = re.compile(
    r"\.(mpg|flv)$|conduite|largue|empannage|auloffee|abattee|affalage|"
    r"lignedepart|470test|conduiteclapot|conduitepres|envoispi", re.I)

# --- race (keep) signals ---
KEEP_PAT = re.compile(
    r"\b(day\s*\d+|race\s*day|gold fleet race|race\s+\d+|medal race|medalrace|"
    r"finals day|highlights)\b", re.I)

# explicit date in title, e.g. "9 August - 2019", "29 Jun 2015", "27th June 2015",
# "10 October 2015", "5 December 2011", "13 March - 2021"
MONTHS = ("January February March April May June July August September October "
          "November December Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec").split()
MONTH_RE = "|".join(MONTHS)
DATE_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_RE})\b(?:.*?\b(\d{{4}})\b)?", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DAY_RE = re.compile(r"\b(?:race\s*day|day)\s*(\d+)\b", re.I)

# athlete-profile / interview clips: "Name/Name (CTY)", "Name Name ENG", "470: Name",
# "Name - 470", "... win", "Gold Medal", "discusses", "interviewing", "Talks 470"
PROFILE_PAT = re.compile(
    r"\bwin\b|gold medal|discuss|interview|talks 470|\(SLO\)|\(FRA\)|\(ESP\)|\(GBR\)|"
    r"\(RSA\)|\(SWE\)|\(GER\)|\(NZL\)|\(USA\)|\(AUS\)|\(IND\)|\(ITA\)|\(AUT\)|\(CRO\)|"
    r"\(HUN\)|\(NED\)|\(ARG\)|^470:\s|(?:ENG|ESP|GRE|FRA)$|-\s*470$|Bibs", re.I)
# extra race signals that slipped past KEEP_PAT
KEEP2_PAT = re.compile(r"medalrace|medal races|_day\s*\d+|opening day|sprint cup|"
                       r"drone footage|^\d{8}$", re.I)

def classify(title):
    if TECH_PAT.search(title):
        return "drop", "technique/raw clip"
    if DROP_PAT.search(title):
        return "drop", "non-race (interview/promo/ceremony)"
    if KEEP_PAT.search(title):
        return "keep", "race footage"
    if DATE_RE.search(title):
        return "keep", "dated race footage"
    if KEEP2_PAT.search(title):
        return "keep", "race footage (secondary rule)"
    if PROFILE_PAT.search(title):
        return "drop", "athlete profile/interview clip"
    # leftover -> flag uncertain
    return "review", "uncertain (no race/day/date signal)"

out = []
events = {}
for vid, title in rows:
    if excluded_by_user(title):
        cat, reason = "excluded", "winners/NADINE (user filter)"
    else:
        cat, reason = classify(title)
    ym = YEAR_RE.search(title)
    year = ym.group(0) if ym else ""
    dm = DAY_RE.search(title)
    day = dm.group(1) if dm else ""
    datem = DATE_RE.search(title)
    expl_date = ""
    if datem:
        d, mon, yr = datem.group(1), datem.group(2), datem.group(3)
        yr = yr or year
        expl_date = f"{d} {mon} {yr}".strip()
    out.append(dict(id=vid, title=title, category=cat, reason=reason,
                    year=year, day=day, explicit_date=expl_date))

with open("classified.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id","title","category","reason","year","day","explicit_date"])
    w.writeheader()
    w.writerows(out)

from collections import Counter
c = Counter(r["category"] for r in out)
print("category counts:", dict(c))
print("\n--- REVIEW (uncertain) titles ---")
for r in out:
    if r["category"] == "review":
        print(" ", r["title"])
