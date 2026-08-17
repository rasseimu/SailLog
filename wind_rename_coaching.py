#!/usr/bin/env python3
"""Insert wind (dir 16-point JP + speed m/s) after the date in coaching filenames.

Current names look like  YYYY-MM-DD_[label_]NN.ext  (from date_rename_coaching.py).
This inserts  _HHMM-<風向>-<風速>  right after the date:

    2025-03-17_駿水さんコーチング_02.MOV
      -> 2025-03-17_1200-西南西-5.3_駿水さんコーチング_02.MOV
    2025-03-09_01.MOV
      -> 2025-03-09_1042-西-3.1_01.MOV

- HHMM and the wind time come from each video's ACTUAL capture time (ffprobe
  creation_time, JST), not the folder date — so mismatched files use their real
  filming-time wind.
- Wind from Open-Meteo historical archive (ERA5) at the Enoshima / Sagami-Bay
  venue (35.30, 139.48), hourly, nearest hour, m/s.
- Idempotent: files that already have a wind token after the date are skipped.
- Renames via safe_rename (overwrite-proof, count-verified, undo CSV). Dry-run
  by default; pass --apply.
"""
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from safe_rename import plan_unique_targets, apply_plan

ROOT = Path(
    "/Users/reimurase/Library/CloudStorage/"
    "GoogleDrive-cy23247@shibaura-it.ac.jp/マイドライブ/練習動画/コーチング(beta)"
)
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
JST = dt.timezone(dt.timedelta(hours=9))
LAT, LON = 35.30, 139.48  # 江の島 / 相模湾

DATED = [
    "2025 7 4 優吾さんコーチング", "3 24", "2025 3 18 駿水さんコーチング",
    "2025 3 17 駿水さんコーチング", "2025.3.11 駿水さんコーチング", "2025 3 9",
    "2025 3 8", "2025 03 04", "2025 2月22日", "3,11", "12 7", "8月28日", "1228",
]
DIRS16 = ['北', '北北東', '北東', '東北東', '東', '東南東', '南東', '南南東',
          '南', '南南西', '南西', '西南西', '西', '西北西', '北西', '北北西']
WIND_TOKEN = re.compile(r'^\d{4}-[北東南西]')   # already-has-wind guard


def deg_to_jp(deg: float) -> str:
    return DIRS16[round(deg / 22.5) % 16]


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


_wind_cache: dict[str, dict[str, tuple]] = {}


def wind_for(date_str: str) -> dict[str, tuple]:
    if date_str in _wind_cache:
        return _wind_cache[date_str]
    q = urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON,
        "start_date": date_str, "end_date": date_str,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "windspeed_unit": "ms", "timezone": "Asia/Tokyo",
    })
    url = f"https://archive-api.open-meteo.com/v1/archive?{q}"
    with urllib.request.urlopen(url, timeout=30) as r:
        h = json.load(r).get("hourly", {})
    m = {t: (s, d) for t, s, d in
         zip(h.get("time", []), h.get("wind_speed_10m", []), h.get("wind_direction_10m", []))}
    _wind_cache[date_str] = m
    return m


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
    skipped_existing = 0
    no_meta = []
    for f, p in jobs:
        stem = p.stem
        rest = stem[11:] if len(stem) > 11 and stem[10] == "_" else stem
        if WIND_TOKEN.match(rest):          # already has wind -> idempotent skip
            skipped_existing += 1
            continue
        c = caps[p]
        if c is None:
            no_meta.append((f, p.name))
            continue
        rounded = (c + dt.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        key = rounded.strftime("%Y-%m-%dT%H:00")
        wm = wind_for(rounded.strftime("%Y-%m-%d"))
        if key not in wm or wm[key][0] is None:
            no_meta.append((f, p.name + " (no wind)"))
            continue
        spd, deg = wm[key]
        token = f"{c.strftime('%H%M')}-{deg_to_jp(deg)}-{spd:.1f}"
        new_stem = f"{stem[:10]}_{token}_{rest}"
        by_folder.setdefault(f, []).append((p, new_stem))

    total = sum(len(v) for v in by_folder.values())
    print(f"\nplanned: {total} renames  | already-had-wind (skipped): {skipped_existing}"
          f"  | no data: {len(no_meta)}")
    for f, n in no_meta:
        print(f"  NO-DATA [{f}] {n}")

    if not apply:
        print("\n--- DRY RUN sample ---")
        for f in folders:
            v = by_folder.get(f, [])
            if v:
                s, st = v[0]
                print(f"  {s.name}\n    -> {st}{s.suffix}   (+{len(v)-1} more in {f})")
        print("\n(dry run — pass --apply)")
        return

    undo = Path(__file__).with_name("wind_rename_undo.csv")
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
