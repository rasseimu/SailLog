#!/usr/bin/env python3
"""Phase 1b: derive a distinct-event key per kept video, list events + counts."""
import re, csv
from collections import defaultdict

def event_type(t):
    tl = t.lower()
    jr = "junior" in tl or "420" in tl or " jr " in tl or "juniors" in tl
    if "master" in tl: return "Masters Cup"
    if "sprint cup" in tl: return "Sprint Cup"
    if "allianz" in tl or "the hague" in tl: return "Allianz Worlds"
    if "world" in tl: return ("Junior Worlds" if jr else "Worlds")
    if "europe" in tl: return ("Junior Europeans" if jr else "Europeans")
    return "?"

# venue tokens seen in titles
VENUE_RE = re.compile(
    r"enoshima|vilamoura|nida|split|thessaloniki|the hague|hague|çe[sş]me|cesme|"
    r"tihany|la rochelle|athens|haifa|san isidro|argentina|aarhus|barcelona|"
    r"formia|monaco|burgas|balaton|lanzarote", re.I)

rows = []
with open("classified.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        rows.append(r)

events = defaultdict(list)
for r in rows:
    if r["category"] not in ("keep", "review"):
        continue
    t = r["title"]
    yr = r["year"]
    et = event_type(t)
    vm = VENUE_RE.search(t)
    venue = vm.group(0).title() if vm else ""
    key = (yr, et, venue)
    events[key].append(r["title"])

print(f"{'YEAR':5} {'TYPE':17} {'VENUE(from title)':20} COUNT")
for key in sorted(events, key=lambda k: (k[0], k[1])):
    yr, et, venue = key
    print(f"{yr:5} {et:17} {venue:20} {len(events[key])}")
print(f"\nDISTINCT EVENTS: {len(events)}   VIDEOS(keep+review): {sum(len(v) for v in events.values())}")
