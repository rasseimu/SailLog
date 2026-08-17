#!/usr/bin/env python3
"""Replace the wind token in coaching filenames with 辻堂 AMeDAS observed wind.

Current names:  YYYY-MM-DD_HHMM-<風向>-<風速>_[label_]NN.ext
This swaps the  HHMM-<風向>-<風速>  token's wind for the real 辻堂 (Tsujido) AMeDAS
value at the video's actual capture hour.  HHMM (capture time) is unchanged.

    2025-03-17_1117-西南西-5.2_駿水さんコーチング_02.MOV   (old: Open-Meteo)
      -> 2025-03-17_1117-南西-4.7_駿水さんコーチング_02.MOV   (辻堂 AMeDAS)

Source: JMA past data, 辻堂 = prec_no=46 block_no=1443, hourly_a1.php. 風向 is
already Japanese 16-point and 風速 is m/s, used verbatim. Wind is looked up by the
video's ACTUAL capture date+hour (ffprobe creation_time, JST, nearest hour).

Renames via safe_rename (overwrite-proof, count-verified, undo CSV). Dry-run by
default; pass --apply.  Idempotent (unchanged value -> no rename).
"""
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import html
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from safe_rename import plan_unique_targets, apply_plan

ROOT = Path(
    "/Users/reimurase/Library/CloudStorage/"
    "GoogleDrive-cy23247@shibaura-it.ac.jp/マイドライブ/練習動画/コーチング(beta)"
)
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
JST = dt.timezone(dt.timedelta(hours=9))
DATED = [
    "2025 7 4 優吾さんコーチング", "3 24", "2025 3 18 駿水さんコーチング",
    "2025 3 17 駿水さんコーチング", "2025.3.11 駿水さんコーチング", "2025 3 9",
    "2025 3 8", "2025 03 04", "2025 2月22日", "3,11", "12 7", "8月28日", "1228",
]
DIRS = {'北', '北北東', '北東', '東北東', '東', '東南東', '南東', '南南東', '南',
        '南南西', '南西', '西南西', '西', '西北西', '北西', '北北西', '静穏'}
# split date_  from  HHMM-<風向>-<風速>  from  _rest
NAME_RE = re.compile(r'^(\d{4}-\d\d-\d\d)_(\d{4})-[^-_]+-[\d.]+_(.*)$')


def probe_dt(path: Path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=120).stdout
        ct = json.loads(out or "{}").get("format", {}).get("tags", {}).get("creation_time")
        if ct:
            return dt.datetime.fromisoformat(ct.replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        pass
    return None


def _cells(row):
    return [html.unescape(re.sub(r'<[^>]+>', '', c)).strip()
            for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]


_amedas_cache: dict[str, dict[int, tuple]] = {}


def tsujido(date: dt.date) -> dict[int, tuple]:
    """{ hour(1..24) -> (風向str, 風速str) } for 辻堂 on `date`."""
    key = date.isoformat()
    if key in _amedas_cache:
        return _amedas_cache[key]
    url = ("https://www.data.jma.go.jp/stats/etrn/view/hourly_a1.php"
           f"?prec_no=46&block_no=1443&year={date.year}&month={date.month}&day={date.day}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'<table[^>]*id="tablefix1".*?</table>', raw, re.S)
    tbl = m.group(0) if m else raw
    out: dict[int, tuple] = {}
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', tbl, re.S):
        c = _cells(row)
        if not c or not c[0].isdigit():
            continue
        hour = int(c[0])
        # find the 風向 cell (a known direction) and the 風速 just before it
        di = next((i for i, v in enumerate(c) if v in DIRS), None)
        if di is None or di == 0:
            continue
        wd = c[di]
        ws = c[di - 1]
        out[hour] = (wd, ws)
    _amedas_cache[key] = out
    return out


def main(apply: bool):
    folders = [f for f in DATED if (ROOT / f).is_dir()]
    jobs = [(f, p) for f in folders for p in sorted((ROOT / f).iterdir())
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    print(f"probing {len(jobs)} videos ...", flush=True)
    caps = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(probe_dt, p): p for _, p in jobs}
        for fut in cf.as_completed(futs):
            caps[futs[fut]] = fut.result()

    by_folder: dict[str, list] = {}
    changes = []       # (folder, old_token, new_token)
    problems = []
    for f, p in jobs:
        mt = NAME_RE.match(p.stem)
        if not mt:
            problems.append((f, p.name, "name has no wind token"))
            continue
        date_s, hhmm, rest = mt.group(1), mt.group(2), mt.group(3)
        c = caps[p]
        if c is None:
            problems.append((f, p.name, "no creation_time"))
            continue
        rounded = (c + dt.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        h = rounded.hour
        lookup_date = rounded.date()
        table_hour = h if h != 0 else 24
        if h == 0:
            lookup_date = lookup_date - dt.timedelta(days=1)
        try:
            wm = tsujido(lookup_date)
        except Exception as e:
            problems.append((f, p.name, f"fetch failed: {e!r}"))
            continue
        rec = wm.get(table_hour)
        if not rec or not rec[1] or rec[1] in ("×", "///", ""):
            problems.append((f, p.name, f"no 辻堂 wind at {lookup_date} {table_hour}h"))
            continue
        wd, ws = rec
        try:
            spd = f"{float(ws):.1f}"
        except ValueError:
            problems.append((f, p.name, f"bad speed {ws!r}"))
            continue
        old_token = p.stem[11:p.stem.index('_', 11 + 5)] if False else None  # unused
        new_token = f"{hhmm}-{wd}-{spd}"
        new_stem = f"{date_s}_{new_token}_{rest}"
        if new_stem != p.stem:
            by_folder.setdefault(f, []).append((p, new_stem))
        # record old vs new for the report
        old_m = re.match(r'^\d{4}-\d\d-\d\d_(\d{4}-[^_]+)_', p.stem)
        changes.append((f, old_m.group(1) if old_m else "?", new_token,
                        "same" if new_stem == p.stem else "change"))

    total = sum(len(v) for v in by_folder.values())
    unchanged = sum(1 for *_ , s in changes if s == "same")
    print(f"\nplanned renames: {total}   unchanged: {unchanged}   problems: {len(problems)}")
    for f, n, why in problems:
        print(f"  PROBLEM [{f}] {n}: {why}")

    if not apply:
        print("\n--- DRY RUN sample (old wind -> 辻堂 wind) ---")
        shown = 0
        for f in folders:
            v = by_folder.get(f, [])
            if v:
                s, st = v[0]
                oldm = re.match(r'^\d{4}-\d\d-\d\d_(\d{4}-[^_]+)_', s.stem)
                newm = re.match(r'^\d{4}-\d\d-\d\d_(\d{4}-[^_]+)_', st)
                print(f"  [{f}] {oldm.group(1)}  ->  {newm.group(1)}   (+{len(v)-1} more)")
                shown += 1
        print("\n(dry run — pass --apply)")
        return

    undo = Path(__file__).with_name("wind_tsujido_undo.csv")
    for f in folders:
        v = by_folder.get(f, [])
        if not v:
            continue
        plans = plan_unique_targets(ROOT / f, v)
        print(f"\n### {f}")
        apply_plan(plans, undo, root=ROOT / f, exts=tuple(VIDEO_EXTS), dry_run=False)
    print(f"\nundo CSV: {undo}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
