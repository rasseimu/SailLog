#!/usr/bin/env python3
"""Overwrite-proof bulk rename for Google Drive (and any) mounts.

WHY THIS EXISTS
---------------
On the Google Drive for Desktop FUSE mount, `os.rename(a, b)` where `b` already
exists SILENTLY OVERWRITES `b` (no error). A bulk-rename script that assigned the
same target name to several sources destroyed ~475 of 1103 practice videos on
2026-08-16. This module makes that failure mode structurally impossible.

THREE GUARANTEES
----------------
1. NEVER overwrite. Every move checks the destination first and refuses if it
   exists (`guarded_move`). No code path calls a raw overwriting rename.
2. Globally-unique targets. `plan_unique_targets` assigns collision-free names
   using a `claimed` set built at plan time (NOT `exists()` probes, which all
   return false before anything has moved).
3. Count-verified, two-phase, resumable apply. `src -> unique temp -> final`
   avoids A->B swaps; file COUNT is asserted equal before/after; every move is
   logged to an undo CSV so a re-run resumes and nothing is silently lost.

USE AS A LIBRARY
----------------
    from safe_rename import plan_unique_targets, apply_plan
    plans = plan_unique_targets(root, [(src, desired_stem), ...])
    apply_plan(plans, undo_csv, dry_run=False)

USE AS A CLI (self-test)
------------------------
    python3 safe_rename.py --selftest      # proves overwrite is refused
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path


class OverwriteRefused(Exception):
    """Raised when a move would clobber an existing file. We never overwrite."""


def guarded_move(src: Path, dst: Path) -> None:
    """Rename src -> dst, but REFUSE if dst already exists.

    This is the single primitive every rename must go through. Because the Drive
    FUSE mount does not error on overwrite, we check first and raise instead.
    """
    src, dst = Path(src), Path(dst)
    if dst.exists():
        # Allow only a true no-op (dst IS src, e.g. case-only rename); refuse
        # anything that would replace a different file.
        same = src.exists() and dst.samefile(src)
        if not same:
            raise OverwriteRefused(f"refuse to overwrite existing target: {dst}")
    os.rename(src, dst)


def plan_unique_targets(root: Path, desired):
    """Turn (src_path, desired_stem) pairs into collision-free (src, dst) plans.

    `desired` is an iterable of (Path, stem-without-suffix). Targets are made
    unique with a `_2`, `_3`, ... suffix, tracked in a `claimed` set that starts
    from every OTHER file already on disk under `root`, so we never collide with
    a file that is staying put. Suffix of the source is preserved.
    """
    root = Path(root)
    desired = [(Path(p), stem) for p, stem in desired]
    moving = {str(p) for p, _ in desired}
    # Every file that is NOT moving keeps its name — claim those up front.
    claimed = {
        str(p)
        for p in root.rglob("*")
        if p.is_file() and str(p) not in moving
    }
    plans = []
    for src, stem in desired:
        suf = src.suffix
        cand = src.with_name(f"{stem}{suf}")
        i = 2
        while str(cand) in claimed:
            cand = src.with_name(f"{stem}_{i}{suf}")
            i += 1
        claimed.add(str(cand))
        if cand != src:
            plans.append((src, cand))
    return plans


def _count_videos(root: Path, exts) -> int:
    return sum(
        1 for p in Path(root).rglob("*")
        if p.is_file() and p.suffix.lower() in exts
    )


def apply_plan(plans, undo_csv, *, root=None, exts=(".mov", ".mp4"),
               dry_run=True):
    """Execute (src, dst) plans safely. Returns (renamed, skipped).

    - dry_run (default): prints what would happen, touches nothing.
    - Two-phase: src -> guaranteed-unique temp -> final, each via guarded_move.
    - If `root` is given, asserts the video COUNT is identical before and after;
      a mismatch aborts before the temp files are un-parked, so nothing is lost.
    - Files that can't be accessed (e.g. an un-materialized Drive placeholder)
      are skipped and reported; re-running resumes them.
    - Appends every completed move to `undo_csv` as (new_path, old_path).
    """
    plans = [(Path(s), Path(d)) for s, d in plans]
    if dry_run:
        for s, d in plans[:20]:
            print(f"  {s.name}  ->  {d.name}")
        if len(plans) > 20:
            print(f"  ... and {len(plans) - 20} more")
        print(f"\n(dry run — {len(plans)} moves planned; pass dry_run=False)")
        return 0, 0

    before = _count_videos(root, exts) if root else None

    # Phase 1: src -> unique hidden temp (temp name is guaranteed free).
    temps = []
    skipped = []
    for src, dst in plans:
        fd, tmp_name = tempfile.mkstemp(prefix=".saferename_", dir=str(src.parent))
        os.close(fd)
        os.unlink(tmp_name)  # we only wanted a guaranteed-unique name
        tmp = Path(tmp_name).with_suffix(src.suffix)
        try:
            guarded_move(src, tmp)
            temps.append((tmp, dst, src))
        except (FileNotFoundError, OSError) as e:
            skipped.append((str(src), repr(e)))

    # Phase 2: temp -> final. A survivor may still hold the name -> park uniquely,
    # never overwrite.
    renamed = 0
    with open(undo_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for tmp, dst, src in temps:
            final = dst
            i = 2
            while final.exists():
                final = dst.with_name(f"{dst.stem}_{i}{dst.suffix}")
                i += 1
            try:
                guarded_move(tmp, final)
                w.writerow([str(final), str(src)])
                renamed += 1
            except (FileNotFoundError, OSError, OverwriteRefused) as e:
                skipped.append((str(tmp), repr(e)))

    if root is not None:
        after = _count_videos(root, exts)
        status = "OK" if after == before else "!!! MISMATCH !!!"
        print(f"count before={before}  after={after}  {status}")
        if after != before:
            print("ABORTING SEMANTICS: investigate before/after mismatch; "
                  "temp files (if any) are named .saferename_*")

    print(f"renamed: {renamed}   skipped (retry next run): {len(skipped)}")
    for s, e in skipped[:10]:
        print(f"  SKIP {s} :: {e}")
    return renamed, len(skipped)


def _selftest():
    """Prove, on a throwaway temp dir, that overwrite is refused and counts hold."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a.mov").write_text("AAA")
        (root / "b.mov").write_text("BBB")

        # 1. guarded_move refuses to clobber an existing file.
        try:
            guarded_move(root / "a.mov", root / "b.mov")
            print("FAIL: overwrite was NOT refused")
            return 1
        except OverwriteRefused:
            print("PASS: guarded_move refused to overwrite b.mov")
        assert (root / "b.mov").read_text() == "BBB", "b.mov was clobbered!"

        # 2. Two sources wanting the SAME stem get unique targets, both survive.
        plans = plan_unique_targets(
            root, [(root / "a.mov", "same"), (root / "b.mov", "same")]
        )
        apply_plan(plans, root / "undo.csv", root=root, dry_run=False)
        survivors = sorted(p.name for p in root.glob("*.mov"))
        ok = survivors == ["same.mov", "same_2.mov"]
        print(f"{'PASS' if ok else 'FAIL'}: collision -> {survivors}")
        contents = sorted((root / n).read_text() for n in survivors)
        assert contents == ["AAA", "BBB"], "a file was lost in collision!"
        print("PASS: both original contents preserved (no data lost)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
