#!/usr/bin/env python3
"""Correct practice-video datetimes: anchor DATE to the folder name (ground-truth
practice day), keep file times already within 08:00-18:00, and replace out-of-range
/ copy-time-garbage times with the median in-range time of sibling videos in the same
folder (fallback 12:00). Then re-derive 辻堂 wind and rename.

Works from rename_undo.csv (original basename -> current path), so it can still tell
PXL/filename sources apart and read intact creation metadata from the current file.

Dry run by default; --apply to execute. Writes rename_undo2.csv (current->new... i.e.
new_path,prev_path) for reversal.
"""
import csv
import datetime as dt
import plistlib
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path.home() / "Google Drive/マイドライブ/練習動画"
CSV_PATH = Path("/Users/reimurase/Documents/sailing/data/data.csv")
UNDO_IN = Path("/Users/reimurase/Documents/sailing/rename_undo.csv")
UNDO_OUT = Path("/Users/reimurase/Documents/sailing/rename_undo2.csv")

JST = dt.timezone(dt.timedelta(hours=9))
UTC = dt.timezone.utc
DAY_START, DAY_END = 8, 18  # inclusive-exclusive practice window
DEFAULT_MIN = 12 * 60       # noon fallback

PXL_RE = re.compile(r"^PXL_(\d{8})_(\d{6})\d*", re.IGNORECASE)
YMD_RE = re.compile(r"^(\d{8})_(\d{6})")


def load_weather(path):
    table = {}
    with open(path, "r", encoding="shift_jis", errors="replace") as f:
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


def folder_date(folder_path):
    """(year, month, day) from folder like '10 25(土)', '12月13日'; None if unparseable."""
    year = 2025 if "2025練習" in str(folder_path) else 2026
    nums = re.findall(r"\d+", folder_path.name)
    if len(nums) < 2:
        return None
    m, d = int(nums[0]), int(nums[1])
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    return (year, m, d)


def mdls_creation(path):
    try:
        out = subprocess.run(
            ["mdls", "-name", "kMDItemContentCreationDate", "-plist", "-", str(path)],
            capture_output=True, timeout=30,
        ).stdout
        val = plistlib.loads(out).get("kMDItemContentCreationDate")
    except Exception:
        return None
    return val.replace(tzinfo=None) if isinstance(val, dt.datetime) else None


def raw_time_of_day(orig_name, cur_path):
    """Minutes-since-midnight from the best source, or None."""
    m = PXL_RE.match(orig_name)
    if m:
        base = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        j = base.replace(tzinfo=UTC).astimezone(JST)
        return j.hour * 60 + j.minute
    m = YMD_RE.match(orig_name)
    if m:
        t = dt.datetime.strptime(m.group(2), "%H%M%S")
        return t.hour * 60 + t.minute
    meta = mdls_creation(cur_path)
    if meta is None:
        return None
    return meta.hour * 60 + meta.minute


def in_range(mins):
    return mins is not None and DAY_START * 60 <= mins < DAY_END * 60


def main():
    apply = "--apply" in sys.argv
    weather = load_weather(CSV_PATH)
    rows = list(csv.reader(open(UNDO_IN, encoding="utf-8")))[1:]

    # Pass 1: gather per-file folder-date + raw time, and per-folder in-range times.
    recs = []
    folder_times = {}
    for cur_path, orig_path in rows:
        cur = Path(cur_path)
        orig_name = Path(orig_path).name
        folder = cur.parent
        fd = folder_date(folder)
        tod = raw_time_of_day(orig_name, cur)
        recs.append((cur, orig_name, folder, fd, tod))
        if fd and in_range(tod):
            folder_times.setdefault(str(folder), []).append(tod)
    folder_median = {
        k: int(statistics.median(v)) for k, v in folder_times.items()
    }

    # Files that will NOT move (skipped originals + any we leave alone): their names
    # must not be clobbered. Start with every video on disk, remove movers later.
    all_on_disk = {
        str(p) for root in (ROOT / "2025練習", ROOT / "2026練習")
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in (".mov", ".mp4")
    }

    # Pass 2: choose base stem per file.
    prelim = []  # (cur, base_stem, suffix)
    borrowed = noon_fallback = kept = nodate = 0
    for cur, orig_name, folder, fd, tod in recs:
        if fd is None:
            nodate += 1
            continue  # e.g. ファミリーデイ — leave as-is
        if in_range(tod):
            mins = tod
            kept += 1
        else:
            med = folder_median.get(str(folder))
            if med is not None:
                mins = med
                borrowed += 1
            else:
                mins = DEFAULT_MIN
                noon_fallback += 1
        hh, mm = divmod(mins, 60)
        t = dt.datetime(fd[0], fd[1], fd[2], hh, mm)
        rh = t.replace(minute=0, second=0, microsecond=0) + (
            dt.timedelta(hours=1) if t.minute >= 30 else dt.timedelta()
        )
        wx = weather.get((rh.year, rh.month, rh.day, rh.hour))
        if not wx or not wx[0] or not wx[1]:
            continue  # no weather -> leave current name
        prelim.append((cur, f"{t:%Y%m%d_%H%M}-{wx[0]}-{wx[1]}", cur.suffix))

    # Assign collision-free unique targets. A name is taken if already claimed here
    # or if it belongs to a file that will stay put.
    movers = {str(c) for c, _, _ in prelim}
    staying = all_on_disk - movers
    claimed = set(staying)
    plans = []
    for cur, stem, suffix in prelim:
        cand = cur.with_name(f"{stem}{suffix}")
        i = 2
        while str(cand) in claimed:
            cand = cur.with_name(f"{stem}_{i}{suffix}")
            i += 1
        claimed.add(str(cand))
        if cand.name != cur.name:
            plans.append((cur, cand))

    print(f"total tracked      : {len(rows)}")
    print(f"time kept (in-range): {kept}")
    print(f"time borrowed(median): {borrowed}")
    print(f"noon fallback       : {noon_fallback}")
    print(f"no folder date      : {nodate}")
    print(f"=> names to change  : {len(plans)}")

    print("\n=== SAMPLE corrections (previously out-of-daylight) ===")
    shown = 0
    for cur, target in plans:
        if not (8 <= int(cur.name[9:11]) < 18) if re.match(r"\d{8}_\d{4}-", cur.name) else True:
            print(f"{cur.parent.name}/\n  {cur.name}\n   -> {target.name}")
            shown += 1
            if shown >= 20:
                break

    if not apply:
        print("\n(dry run — pass --apply to execute)")
        return
    # Two-phase rename: cur -> unique temp -> final. Prevents any A->B overwrite when
    # B is itself another mover (date/time swaps, shared medians).
    temps = []
    for idx, (cur, target) in enumerate(plans):
        tmp = cur.with_name(f".fixtmp_{idx}{cur.suffix}")
        cur.rename(tmp)
        temps.append((tmp, target, cur))
    with open(UNDO_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["new_path", "prev_path"])
        for tmp, target, cur in temps:
            if target.exists():
                raise SystemExit(f"UNEXPECTED collision at final: {target}")
            tmp.rename(target)
            w.writerow([str(target), str(cur)])
    print(f"\nDONE: corrected {len(plans)} names. Undo log: {UNDO_OUT}")


if __name__ == "__main__":
    main()
