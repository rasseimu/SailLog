#!/usr/bin/env python3
"""Idempotent, Drive-safe correction of practice-video names.

Reads CURRENT on-disk names of the form YYYYMMDD_HHMM-... (the HHMM already equals
the original recording time-of-day for every source type). Anchors the DATE to the
folder name, keeps times within 08:00-18:00, and replaces out-of-range times with the
folder's median in-range time (fallback noon), then re-derives 辻堂 wind.

Safe to run repeatedly: converged files produce no change. Files that error (e.g. a
Google Drive placeholder not yet materialized) are skipped and reported, so a re-run
picks them up. --apply to execute; default dry run.
"""
import csv
import datetime as dt
import re
import statistics
import sys
from pathlib import Path

ROOT = Path.home() / "Google Drive/マイドライブ/練習動画"
CSV_PATH = Path("/Users/reimurase/Documents/sailing/data/data.csv")
UNDO_OUT = Path("/Users/reimurase/Documents/sailing/correct_times2_undo.csv")
DAY_START, DAY_END = 8, 18
DEFAULT_MIN = 12 * 60
NAME_RE = re.compile(r"^(\d{8})_(\d{2})(\d{2})-")


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


def folder_date(folder):
    year = 2025 if "2025練習" in str(folder) else 2026
    nums = re.findall(r"\d+", folder.name)
    if len(nums) < 2:
        return None
    m, d = int(nums[0]), int(nums[1])
    return (year, m, d) if 1 <= m <= 12 and 1 <= d <= 31 else None


def in_range(mins):
    return DAY_START * 60 <= mins < DAY_END * 60


def main():
    apply = "--apply" in sys.argv
    weather = load_weather(CSV_PATH)

    files = [
        p for r in ("2025練習", "2026練習") for p in (ROOT / r).rglob("*")
        if p.is_file() and p.suffix.lower() in (".mov", ".mp4")
    ]
    all_names = {str(p) for p in files}

    # Pass 1: folder medians from in-range renamed files.
    ft = {}
    parsed = []
    for p in files:
        m = NAME_RE.match(p.name)
        fd = folder_date(p.parent)
        tod = int(m.group(2)) * 60 + int(m.group(3)) if m else None
        parsed.append((p, fd, tod, m is not None))
        if m and fd and in_range(tod):
            ft.setdefault(str(p.parent), []).append(tod)
    median = {k: int(statistics.median(v)) for k, v in ft.items()}

    # Pass 2: compute targets for renamed files with a parseable folder date.
    prelim = []
    for p, fd, tod, is_renamed in parsed:
        if not is_renamed or fd is None:
            continue
        if in_range(tod):
            mins = tod
        else:
            mins = median.get(str(p.parent), DEFAULT_MIN)
        hh, mm = divmod(mins, 60)
        t = dt.datetime(fd[0], fd[1], fd[2], hh, mm)
        rh = t.replace(minute=0, second=0, microsecond=0) + (
            dt.timedelta(hours=1) if t.minute >= 30 else dt.timedelta()
        )
        wx = weather.get((rh.year, rh.month, rh.day, rh.hour))
        if not wx or not wx[0] or not wx[1]:
            continue
        prelim.append((p, f"{t:%Y%m%d_%H%M}-{wx[0]}-{wx[1]}", p.suffix))

    movers = {str(p) for p, _, _ in prelim}
    claimed = set(all_names - movers)
    # Keep files that already bear the correct stem (base or any _N suffix); only the
    # date/wind/time stem matters, not the specific suffix number. This makes suffix
    # assignment stable and the whole pass convergent (no _N renumbering churn).
    pending = []
    for p, stem, suf in prelim:
        if p.stem == stem or re.fullmatch(re.escape(stem) + r"_\d+", p.stem):
            claimed.add(str(p))
        else:
            pending.append((p, stem, suf))
    plans = []
    for p, stem, suf in pending:
        cand = p.with_name(f"{stem}{suf}")
        i = 2
        while str(cand) in claimed:
            cand = p.with_name(f"{stem}_{i}{suf}")
            i += 1
        claimed.add(str(cand))
        plans.append((p, cand))

    print(f"renamed files scanned : {len(movers)}")
    print(f"names needing change   : {len(plans)}")
    if not apply:
        for p, t in plans[:12]:
            print(f"  {p.parent.name}/ {p.name} -> {t.name}")
        print("\n(dry run — pass --apply to execute)")
        return

    # Resilient two-phase rename. Skip (log) any file that can't be accessed.
    temps, skipped = [], []
    for idx, (p, target) in enumerate(plans):
        tmp = p.with_name(f".fixtmp2_{idx}{p.suffix}")
        try:
            p.rename(tmp)
            temps.append((tmp, target, p))
        except (FileNotFoundError, OSError) as e:
            skipped.append((str(p), repr(e)))
    done = 0
    with open(UNDO_OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for tmp, target, p in temps:
            if target.exists():  # a survivor still holds the name; park uniquely
                i = 2
                stem = target.stem
                base = re.sub(r"_\d+$", "", stem)
                while target.exists():
                    target = target.with_name(f"{base}_{i}{target.suffix}")
                    i += 1
            try:
                tmp.rename(target)
                w.writerow([str(target), str(p)])
                done += 1
            except (FileNotFoundError, OSError) as e:
                skipped.append((str(tmp), repr(e)))
    print(f"renamed: {done}   skipped(retry next run): {len(skipped)}")
    for s, e in skipped[:10]:
        print(f"  SKIP {s} :: {e}")


if __name__ == "__main__":
    main()
