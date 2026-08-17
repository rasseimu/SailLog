#!/usr/bin/env python3
"""Merge upload_date into classified rows; fill year; list distinct events for research."""
import csv, re
from collections import defaultdict

meta = {}
with open("meta.tsv", encoding="utf-8") as f:
    for line in f:
        p = line.rstrip("\n").split("|")
        if len(p) >= 3:
            meta[p[0]] = {"upload": p[1], "dur": p[2]}

def event_type(t):
    tl = t.lower()
    jr = "junior" in tl or "420" in tl or "juniors" in tl
    if "master" in tl: return "Masters Cup"
    if "sprint cup" in tl: return "Sprint Cup"
    if "allianz" in tl or "the hague" in tl: return "Allianz Worlds"
    if "world" in tl: return "Junior Worlds" if jr else "Worlds"
    if "europe" in tl: return "Junior Europeans" if jr else "Europeans"
    return "?"

VENUE_RE = re.compile(
    r"enoshima|vilamoura|nida|split|thessaloniki|the hague|hague|çe[sş]me|cesme|"
    r"tihany|la rochelle|athens|haifa|san isidro|argentina|aarhus|barcelona|"
    r"formia|monaco|burgas", re.I)

rows = []
with open("classified.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["category"] not in ("keep", "review"):
            continue
        up = meta.get(r["id"], {}).get("upload", "")
        r["upload"] = up
        r["dur"] = meta.get(r["id"], {}).get("dur", "")
        # fill year from upload_date if title lacked it
        if not r["year"] and up and up != "NA":
            r["year"] = up[:4]
        rows.append(r)

# group by (year, type); propagate a venue from any member title
groups = defaultdict(list)
for r in rows:
    groups[(r["year"], event_type(r["title"]))].append(r)

print(f"{'YEAR':5} {'TYPE':17} {'VENUE(title)':16} {'N':>3}  UPLOAD-RANGE")
event_list = []
for key in sorted(groups):
    yr, et = key
    members = groups[key]
    venue = ""
    for m in members:
        vm = VENUE_RE.search(m["title"])
        if vm:
            venue = vm.group(0).title(); break
    ups = sorted(set(m["upload"] for m in members if m["upload"] and m["upload"] != "NA"))
    urange = f"{ups[0]}..{ups[-1]}" if ups else "?"
    print(f"{yr:5} {et:17} {venue:16} {len(members):>3}  {urange}")
    event_list.append((yr, et, venue, len(members), urange))

print(f"\nDISTINCT EVENTS: {len(event_list)}   VIDEOS: {sum(e[3] for e in event_list)}")

# persist merged rows for later
with open("keep_meta.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id","title","category","reason","year","day","explicit_date","upload","dur"])
    w.writeheader(); w.writerows(rows)
