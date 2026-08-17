#!/usr/bin/env python3
"""TEST: rename the local sample videos in gdrive/ via the safe_rename guardrail.

Datetime = mdls creation (JST wall-clock). Times in 08:00-18:00 kept; out-of-range
(copy-time garbage) replaced by the median in-range time. Wind from 辻堂 CSV at the
nearest hour. Renaming goes ONLY through safe_rename.plan_unique_targets/apply_plan.
"""
import csv
import datetime as dt
import plistlib
import re
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/Users/reimurase/Documents/sailing")
from safe_rename import plan_unique_targets, apply_plan

ROOT = Path("/Users/reimurase/Documents/sailing/gdrive")
CSV_PATH = Path("/Users/reimurase/Documents/sailing/data/data.csv")
UNDO = Path("/Users/reimurase/Documents/sailing/gdrive_rename_undo.csv")
DAY_START, DAY_END = 8, 18
DEFAULT_MIN = 12 * 60


def load_weather(path):
    table = {}
    with open(path, encoding="shift_jis", errors="replace") as f:
        for row in csv.reader(f):
            if not row or not re.match(r"^\d{4}/\d{1,2}/\d{1,2}", row[0].strip()):
                continue
            try:
                t = dt.datetime.strptime(row[0].strip(), "%Y/%m/%d %H:%M:%S")
            except ValueError:
                continue
            table[(t.year, t.month, t.day, t.hour)] = (
                row[3].strip() if len(row) > 3 else "",
                row[1].strip() if len(row) > 1 else "",
            )
    return table


def mdls_creation(path):
    out = subprocess.run(
        ["mdls", "-name", "kMDItemContentCreationDate", "-plist", "-", str(path)],
        capture_output=True, timeout=30,
    ).stdout
    val = plistlib.loads(out).get("kMDItemContentCreationDate")
    # mdls tags +0000 but the wall-clock is local JST -> strip tz, keep numbers.
    return val.replace(tzinfo=None) if isinstance(val, dt.datetime) else None


def nearest_hour(t):
    return t.replace(minute=0, second=0, microsecond=0) + (
        dt.timedelta(hours=1) if t.minute >= 30 else dt.timedelta()
    )


def main():
    apply = "--apply" in sys.argv
    weather = load_weather(CSV_PATH)
    vids = sorted(p for p in ROOT.iterdir()
                  if p.is_file() and p.suffix.lower() in (".mov", ".mp4"))

    # Pass 1: creation datetime per file + median of in-range times.
    meta, in_range_mins = {}, []
    for p in vids:
        c = mdls_creation(p)
        meta[p] = c
        if c and DAY_START * 60 <= c.hour * 60 + c.minute < DAY_END * 60:
            in_range_mins.append(c.hour * 60 + c.minute)
    median = int(statistics.median(in_range_mins)) if in_range_mins else DEFAULT_MIN

    # Pass 2: build desired stems.
    desired, preview = [], []
    for p in vids:
        c = meta[p]
        if c is None:
            preview.append((p.name, "SKIP (no creation metadata)"))
            continue
        mins = c.hour * 60 + c.minute
        if DAY_START * 60 <= mins < DAY_END * 60:
            src, note = mins, "kept"
        else:
            src, note = median, f"borrowed<-{c:%H:%M}"
        hh, mm = divmod(src, 60)
        t = dt.datetime(c.year, c.month, c.day, hh, mm)
        h = nearest_hour(t)
        wx = weather.get((h.year, h.month, h.day, h.hour))
        if not wx or not wx[0] or not wx[1]:
            preview.append((p.name, "SKIP (no weather)"))
            continue
        stem = f"{t:%Y%m%d_%H%M}-{wx[0]}-{wx[1]}"
        desired.append((p, stem))
        preview.append((p.name, f"{stem}{p.suffix}  [{note}]"))

    print(f"videos: {len(vids)}   to rename: {len(desired)}   "
          f"(median in-range time = {median // 60:02d}:{median % 60:02d})\n")
    for old, new in preview:
        print(f"  {old:16s} -> {new}")

    plans = plan_unique_targets(ROOT, desired)
    print(f"\nunique targets planned: {len(plans)}")
    apply_plan(plans, UNDO, root=ROOT, dry_run=not apply)


if __name__ == "__main__":
    main()
