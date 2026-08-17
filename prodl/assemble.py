#!/usr/bin/env python3
"""Phase 1c: join videos + event table, resolve date, fetch wind, build filenames -> manifest."""
import csv, re, datetime, sys
from wind import fetch_wind

MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
MONTHS.update({m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August",
     "September","October","November","December"], 1)})
MONTHS["sept"] = 9

def event_type(t):
    tl = t.lower(); jr = "junior" in tl or "420" in tl
    if "master" in tl: return "masters"
    if "sprint" in tl: return "sprint"
    if "allianz" in tl or "the hague" in tl: return "allianz"
    if "world" in tl: return "jrworlds" if jr else "worlds"
    if "europe" in tl: return "jreuropeans" if jr else "europeans"
    return "?"

# resolve '?' type by year
Q_MAP = {"2019": "europeans", "2015": "europeans", "2013": "europeans",
         "2011": "perth", "2010": "worlds_finals"}

def event_key(year, title):
    et = event_type(title)
    if et == "?":
        et = Q_MAP.get(year, "worlds")
    if year == "2011" and et == "perth":
        return "2011_perth"
    if year == "2010" and et == "worlds_finals":
        return "2009_worlds_finals"
    return f"{year}_{et}"

def parse_explicit(expl, title, year):
    # "9 August 2019", "29 Jun 2015", "8 December 2011"
    if expl:
        m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", expl)
        if m:
            d, mon, yr = int(m.group(1)), m.group(2).lower(), int(m.group(3))
            if mon in MONTHS:
                try: return datetime.date(yr, MONTHS[mon], d)
                except ValueError: pass
    # 8-digit YYYYMMDD title, e.g. "20090829"
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", title.strip())
    if m:
        try: return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: pass
    return None

def parse_upload(up):
    if up and len(up) == 8 and up.isdigit():
        try: return datetime.date(int(up[:4]), int(up[4:6]), int(up[6:8]))
        except ValueError: return None
    return None

def sanitize(name):
    name = re.sub(r"[\\/:*?\"<>|]", " ", name)   # illegal fs chars
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120]

def load_events(path):
    ev = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ev[r["key"].strip()] = r
    return ev

def main():
    events = load_events("events.csv")
    rows = list(csv.DictReader(open("keep_meta.csv", encoding="utf-8")))
    out = []
    for r in rows:
        title, year = r["title"], r["year"]
        key = event_key(year, title)
        ev = events.get(key)
        rec = dict(id=r["id"], category=r["category"], reason=r["reason"],
                   title=title, event_key=key, dur=r["dur"])
        if not ev:
            rec.update(venue="", date="", wind="", date_src="NO_EVENT_MATCH",
                       proposed_filename="", confidence="")
            out.append(rec); continue
        try:
            start = datetime.datetime.strptime(ev["start_date"], "%Y-%m-%d").date()
            end = datetime.datetime.strptime(ev["end_date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            start = end = None
        # --- date resolution ---
        date = parse_explicit(r["explicit_date"], title, year)
        src = "title-date"
        up = parse_upload(r["upload"])
        if not date and up and start and (start - datetime.timedelta(days=1)) <= up <= (end + datetime.timedelta(days=1)):
            date, src = up, "upload(in-window)"
        if not date and r["day"] and start:
            off = int(r["day"])
            cand = start + datetime.timedelta(days=max(0, off - 1))
            date = min(max(cand, start), end); src = f"day{off}+start"
        # prefer the real event window over an out-of-window (often batch) upload date
        if not date and start:
            date = start + (end - start) // 2; src = "event-midpoint"
        if not date and up:
            date, src = up, "upload(fallback)"
        # --- wind ---
        wind = ""
        if date and ev.get("lat") and ev.get("lon"):
            try:
                w = fetch_wind(float(ev["lat"]), float(ev["lon"]),
                               ev.get("tz") or "UTC", date.isoformat())
            except Exception:
                w = None
            if w:
                wind = f"{w['speed_ms']}ms {w['compass']} {w['dir_deg']}deg"
                windtag = f"風速{w['speed_ms']}ms_風向{w['compass']}{w['dir_deg']}度"
            else:
                windtag = "風速NA_風向NA"
        else:
            windtag = "風速NA_風向NA"
        datestr = date.isoformat() if date else "DATE-UNKNOWN"
        fname = f"{datestr}_{windtag}_{sanitize(title)}.mp4"
        rec.update(venue=f'{ev["venue_city"]},{ev["country"]}', date=datestr,
                   wind=wind, date_src=src, confidence=ev.get("confidence",""),
                   proposed_filename=fname)
        out.append(rec)
        print(f"{datestr}  {wind or 'no-wind':22}  {title[:55]}")

    cols = ["id","category","reason","event_key","venue","confidence","date",
            "date_src","wind","dur","title","proposed_filename"]
    with open("プロ動画_manifest.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for rec in out: w.writerow({k: rec.get(k,"") for k in cols})
    n_wind = sum(1 for r in out if r["wind"])
    print(f"\nMANIFEST: {len(out)} videos, {n_wind} with wind, "
          f"{sum(1 for r in out if r['date_src']=='NO_EVENT_MATCH')} unmatched")

if __name__ == "__main__":
    main()
