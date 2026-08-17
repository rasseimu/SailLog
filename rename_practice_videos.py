#!/usr/bin/env python3
"""Rename sailing practice videos in Google Drive to `YYYYMMDD_HHMM-風向-風速.ext`.

Datetime source (JST):
  - PXL_YYYYMMDD_HHMMSS...  -> filename is UTC, +9h -> JST
  - YYYYMMDD_HHMMSS...      -> filename is JST as-is
  - otherwise (IMG_ etc.)   -> macOS creation metadata (JST wall-clock); skip if absent

Wind comes from the 辻堂 hourly JMA CSV (data/data.csv, Shift-JIS), matched to the
nearest hour. Files with no usable time or no weather match are SKIPPED and reported.

Run with --apply to actually rename. Default is a dry run.
Every rename is logged to rename_undo.csv (new_path,old_path) for reversal.
"""
import csv
import datetime as dt
import plistlib
import re
import subprocess
import sys
from pathlib import Path

VIDEO_ROOT = Path.home() / "Google Drive/マイドライブ/練習動画"
CSV_PATH = Path("/Users/reimurase/Documents/sailing/data/data.csv")
UNDO_LOG = Path("/Users/reimurase/Documents/sailing/rename_undo.csv")

JST = dt.timezone(dt.timedelta(hours=9))
UTC = dt.timezone.utc

PXL_RE = re.compile(r"^PXL_(\d{8})_(\d{6})\d*", re.IGNORECASE)
YMD_RE = re.compile(r"^(\d{8})_(\d{6})")
# Files that are already renamed by us: YYYYMMDD_HHMM-...
DONE_RE = re.compile(r"^\d{8}_\d{4}-")


def load_weather(csv_path):
    """Return {(y,m,d,h): (wind_dir, wind_speed)} from the 辻堂 CSV."""
    table = {}
    with open(csv_path, "r", encoding="shift_jis", errors="replace") as f:
        for row in csv.reader(f):
            if not row or not re.match(r"^\d{4}/\d{1,2}/\d{1,2}", row[0].strip()):
                continue
            try:
                t = dt.datetime.strptime(row[0].strip(), "%Y/%m/%d %H:%M:%S")
            except ValueError:
                continue
            speed = row[1].strip() if len(row) > 1 else ""
            wdir = row[3].strip() if len(row) > 3 else ""
            table[(t.year, t.month, t.day, t.hour)] = (wdir, speed)
    return table


def mdls_creation(path):
    """Creation datetime from Spotlight metadata (JST wall-clock), or None."""
    try:
        out = subprocess.run(
            ["mdls", "-name", "kMDItemContentCreationDate", "-plist", "-", str(path)],
            capture_output=True, timeout=30,
        ).stdout
        val = plistlib.loads(out).get("kMDItemContentCreationDate")
    except Exception:
        return None
    if not isinstance(val, dt.datetime):
        return None
    # mdls tags the value +0000, but the stored wall-clock is local JST. Strip tz,
    # keep the wall-clock numbers as JST.
    return val.replace(tzinfo=None)


def resolve_datetime(path):
    """Return (jst_naive_datetime, source) or (None, reason)."""
    name = path.name
    m = PXL_RE.match(name)
    if m:
        try:
            base = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            return None, "pxl-parse-fail"
        return (base.replace(tzinfo=UTC).astimezone(JST).replace(tzinfo=None), "pxl")
    m = YMD_RE.match(name)
    if m:
        try:
            return (dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"), "fname")
        except ValueError:
            return None, "ymd-parse-fail"
    meta = mdls_creation(path)
    if meta is None:
        return None, "no-time"
    return (meta, "meta")


def nearest_hour(t):
    t = t.replace(minute=0, second=0, microsecond=0) + (
        dt.timedelta(hours=1) if t.minute >= 30 else dt.timedelta()
    )
    return t


def unique_target(path, stem, ext):
    cand = path.with_name(f"{stem}{ext}")
    if not cand.exists() or cand == path:
        return cand
    i = 2
    while True:
        cand = path.with_name(f"{stem}_{i}{ext}")
        if not cand.exists():
            return cand
        i += 1


def main():
    apply = "--apply" in sys.argv
    weather = load_weather(CSV_PATH)
    print(f"weather rows: {len(weather)}", file=sys.stderr)

    roots = [VIDEO_ROOT / "2025練習", VIDEO_ROOT / "2026練習"]
    videos = sorted(
        p for root in roots for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in (".mov", ".mp4")
    )
    print(f"videos found: {len(videos)}", file=sys.stderr)

    plans, skips = [], {}
    src_counts = {}
    for p in videos:
        if DONE_RE.match(p.name):
            skips.setdefault("already-renamed", []).append(p)
            continue
        t, src = resolve_datetime(p)
        if t is None:
            skips.setdefault(src, []).append(p)
            continue
        h = nearest_hour(t)
        wx = weather.get((h.year, h.month, h.day, h.hour))
        if wx is None:
            skips.setdefault("no-weather", []).append(p)
            continue
        wdir, speed = wx
        if not wdir or not speed:
            skips.setdefault("empty-weather", []).append(p)
            continue
        stem = f"{t:%Y%m%d_%H%M}-{wdir}-{speed}"
        target = unique_target(p, stem, p.suffix)
        if target == p:
            skips.setdefault("already-renamed", []).append(p)
            continue
        plans.append((p, target))
        src_counts[src] = src_counts.get(src, 0) + 1

    print("\n=== PLAN SUMMARY ===")
    print(f"to rename : {len(plans)}  (by source: {src_counts})")
    for reason, items in sorted(skips.items()):
        print(f"skip [{reason}] : {len(items)}")

    print("\n=== SAMPLE (first 25 renames) ===")
    for p, t in plans[:25]:
        print(f"{p.parent.name}/  {p.name}\n   -> {t.name}")

    if not apply:
        print("\n(dry run — pass --apply to execute)")
        return

    with open(UNDO_LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["new_path", "old_path"])
        done = 0
        for p, target in plans:
            p.rename(target)
            w.writerow([str(target), str(p)])
            done += 1
            if done % 100 == 0:
                print(f"  renamed {done}/{len(plans)}", file=sys.stderr)
    print(f"\nDONE: renamed {len(plans)} files. Undo log: {UNDO_LOG}")


if __name__ == "__main__":
    main()
