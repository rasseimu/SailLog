#!/usr/bin/env python3
"""Rename coaching videos in コーチング(beta) to  YYYY-MM-DD_<label>_NN.<ext>.

- The folder-name date is the authoritative coaching date (month/day; year filled
  from video metadata when the folder omits it).
- Each video's real capture date is read from its internal metadata via ffprobe
  (creation_time, UTC) and converted to JST for comparison + a mismatch report.
- Videos are sequenced by capture time ascending within each folder.
- Renames go through safe_rename.apply_plan (overwrite-proof, count-verified,
  undo CSV) — never a raw mount rename.  Dry-run by default; pass --apply.

Only *video* files are touched (.mov/.mp4/.m4v). Audio (.m4a) / images / docs are
left as-is.  Person folders (高木/市野/土居) are excluded.
"""
from __future__ import annotations
import concurrent.futures as cf
import csv
import datetime as dt
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from safe_rename import plan_unique_targets, apply_plan

ROOT = Path(
    "/Users/reimurase/Library/CloudStorage/"
    "GoogleDrive-cy23247@shibaura-it.ac.jp/マイドライブ/練習動画/コーチング(beta)"
)
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
JST = dt.timezone(dt.timedelta(hours=9))

# folder name on the mount -> (year|None, month, day, label)
FOLDER_META = {
    "2025 7 4 優吾さんコーチング": (2025, 7, 4, "優吾さんコーチング"),
    "250323 吉岡美帆クルーワーク講座・パリ艤装": (2025, 3, 23, "吉岡美帆クルーワーク講座・パリ艤装"),
    "3 24": (None, 3, 24, ""),
    "2025 3 18 駿水さんコーチング": (2025, 3, 18, "駿水さんコーチング"),
    "2025 3 17 駿水さんコーチング": (2025, 3, 17, "駿水さんコーチング"),
    "2025.3.11 駿水さんコーチング": (2025, 3, 11, "駿水さんコーチング"),
    "2025 3 9": (2025, 3, 9, ""),
    "2025 3 8": (2025, 3, 8, ""),
    "2025 03 04": (2025, 3, 4, ""),          # Drive name "2025/03/04"
    "2025 2月22日": (2025, 2, 22, ""),
    "3,11": (None, 3, 11, ""),
    "1214": (None, 12, 14, ""),              # empty folder in practice
    "12 7": (None, 12, 7, ""),
    "8月28日": (None, 8, 28, ""),
    "1228": (None, 12, 28, ""),
}


def probe_creation(path: Path):
    """Return capture datetime (UTC, tz-aware) or None."""
    for args in (
        ["-show_entries", "format_tags=creation_time"],
        ["-select_streams", "v:0", "-show_entries", "stream_tags=creation_time"],
    ):
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", *args, "-of", "json", str(path)],
                capture_output=True, text=True, timeout=120,
            ).stdout
            data = json.loads(out or "{}")
            tags = {}
            if data.get("format", {}).get("tags"):
                tags = data["format"]["tags"]
            elif data.get("streams"):
                tags = data["streams"][0].get("tags", {})
            ct = tags.get("creation_time")
            if ct:
                return dt.datetime.fromisoformat(ct.replace("Z", "+00:00"))
        except Exception:
            continue
    return None


def main(apply: bool):
    folders = [f for f in FOLDER_META if (ROOT / f).is_dir()]
    # 1. gather video files
    jobs = []  # (folder, path)
    for f in folders:
        for p in sorted((ROOT / f).iterdir()):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                jobs.append((f, p))

    print(f"probing {len(jobs)} video files via ffprobe ...", flush=True)
    caps = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(probe_creation, p): (f, p) for f, p in jobs}
        for fut in cf.as_completed(futs):
            f, p = futs[fut]
            caps[p] = fut.result()

    all_plans = []          # (folder_root, [(src, stem)])
    report_rows = []        # for CSV
    mismatches = []
    no_meta = []

    for f in folders:
        y, mo, d, label = FOLDER_META[f]
        vids = [p for (ff, p) in jobs if ff == f]
        if not vids:
            continue
        # resolve year from metadata if folder omits it
        if y is None:
            years = [caps[p].astimezone(JST).year for p in vids if caps[p]]
            y = Counter(years).most_common(1)[0][0] if years else dt.date.today().year
        coaching = dt.date(y, mo, d)
        iso = coaching.isoformat()

        # order by capture time (missing -> end, by name)
        def key(p):
            c = caps[p]
            return (0, c.astimezone(JST)) if c else (1, dt.datetime.max.replace(tzinfo=JST))
        vids_sorted = sorted(vids, key=lambda p: (key(p), p.name.lower()))

        desired = []
        for i, p in enumerate(vids_sorted, 1):
            nn = f"{i:02d}"
            stem = f"{iso}_{label}_{nn}" if label else f"{iso}_{nn}"
            desired.append((p, stem))
            c = caps[p]
            cap_jst = c.astimezone(JST).date().isoformat() if c else ""
            match = "" if not c else ("OK" if c.astimezone(JST).date() == coaching else "MISMATCH")
            report_rows.append([f, coaching.isoformat(), p.name, f"{stem}{p.suffix}", cap_jst, match])
            if not c:
                no_meta.append((f, p.name))
            elif match == "MISMATCH":
                mismatches.append((f, p.name, cap_jst, coaching.isoformat()))

        plans = plan_unique_targets(ROOT / f, desired)
        all_plans.append((ROOT / f, plans))

    # write report CSV
    rep = Path(__file__).with_name("coaching_rename_plan.csv")
    with open(rep, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["folder", "coaching_date", "old_name", "new_name", "capture_jst", "match"])
        w.writerows(report_rows)

    total = sum(len(pl) for _, pl in all_plans)
    print(f"\nplanned renames: {total} videos across {len(all_plans)} folders")
    print(f"mismatches (capture date != folder date): {len(mismatches)}")
    for f, n, cap, co in mismatches:
        print(f"  [{f}] {n}: capture {cap} vs coaching {co}")
    if no_meta:
        print(f"no creation_time metadata: {len(no_meta)}")
        for f, n in no_meta:
            print(f"  [{f}] {n}")
    print(f"\nfull plan CSV: {rep}")

    if not apply:
        print("\n--- DRY RUN sample (per folder) ---")
        for root, plans in all_plans:
            if plans:
                s, d = plans[0]
                print(f"  {root.name}:  {s.name}  ->  {d.name}   (+{len(plans)-1} more)")
        print("\n(dry run — pass --apply to execute via safe_rename)")
        return

    undo = Path(__file__).with_name("coaching_rename_undo.csv")
    for root, plans in all_plans:
        print(f"\n### {root.name}")
        apply_plan(plans, undo, root=root, exts=tuple(VIDEO_EXTS), dry_run=False)
    print(f"\nundo CSV: {undo}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
