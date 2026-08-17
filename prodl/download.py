#!/usr/bin/env python3
"""Phase 2: download the 204 keep videos at <=1080p, then move each finished .mp4 into プロ動画
with a wind-labeled name. Downloads+merges in a LOCAL temp dir (fast, no partial litter on the
Drive mount), moves only completed files, never overwrites existing files."""
import csv, os, sys, subprocess, shutil, glob, time, random

DEST = os.path.expanduser(
    "~/Library/CloudStorage/GoogleDrive-cy23247@shibaura-it.ac.jp/マイドライブ/練習動画/プロ動画")
STAGE = os.path.expanduser("~/Documents/sailing/prodl/staging")
ARCHIVE = os.path.expanduser("~/Documents/sailing/prodl/downloaded_archive.txt")
MANIFEST = os.path.expanduser("~/Documents/sailing/prodl/プロ動画_manifest.csv")

def jobs():
    for r in csv.DictReader(open(MANIFEST, encoding="utf-8")):
        if r["category"] == "keep":
            yield r["id"], r["proposed_filename"]

def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    os.makedirs(DEST, exist_ok=True)
    os.makedirs(STAGE, exist_ok=True)
    todo = list(jobs())
    if only:
        todo = [(i, n) for i, n in todo if i == only]
    total = len(todo)
    done = skipped = failed = 0
    fails = []
    for idx, (vid, fname) in enumerate(todo, 1):
        final = os.path.join(DEST, fname)
        if os.path.exists(final) and os.path.getsize(final) > 0:
            skipped += 1
            print(f"[{idx}/{total}] SKIP exists: {fname}", flush=True)
            continue
        def attempt():
            # clean any stale staging fragments for this id
            for f in glob.glob(os.path.join(STAGE, vid + ".*")):
                os.remove(f)
            stage_out = os.path.join(STAGE, vid + ".%(ext)s")
            cmd = [
                "yt-dlp",
                "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "--extractor-args", "youtube:player_client=default,android",
                "--merge-output-format", "mp4",
                "--limit-rate", "6M",             # gentle rate → avoids the volume throttle
                "--retries", "5", "--fragment-retries", "10",
                "--retry-sleep", "http:exp=2:60",
                "--no-overwrites", "--no-playlist",
                "--download-archive", ARCHIVE,
                "-o", stage_out,
                f"https://www.youtube.com/watch?v={vid}",
            ]
            return subprocess.run(cmd, capture_output=True, text=True)

        print(f"[{idx}/{total}] GET {vid} -> {fname}", flush=True)
        r = attempt()
        merged = os.path.join(STAGE, vid + ".mp4")
        # 403 throttle → cooldown and one retry with fresh extraction
        if r.returncode != 0 and "403" in (r.stderr or "") and not os.path.exists(merged):
            print(f"[{idx}/{total}] 403 throttle — cooling down 90s then retrying", flush=True)
            time.sleep(90)
            r = attempt()
        if r.returncode == 0 and os.path.exists(merged):
            # move completed file into Drive only if the unique dest name is free
            if os.path.exists(final):
                print(f"[{idx}/{total}] WARN dest exists, not overwriting: {fname}", flush=True)
                os.remove(merged); skipped += 1; continue
            shutil.move(merged, final)
            done += 1
            print(f"[{idx}/{total}] OK  {os.path.getsize(final)//1_000_000} MB -> Drive", flush=True)
        elif r.returncode == 0:
            skipped += 1
            print(f"[{idx}/{total}] SKIP archived (already downloaded previously)", flush=True)
        else:
            failed += 1; fails.append(vid)
            last = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "unknown"
            print(f"[{idx}/{total}] FAIL {vid}: {last}", flush=True)
        # tidy leftover fragments
        for f in glob.glob(os.path.join(STAGE, vid + ".*")):
            try: os.remove(f)
            except OSError: pass
        # pace between videos to stay under YouTube's per-IP volume throttle
        if idx < total:
            time.sleep(random.randint(12, 25))
    print(f"\nDONE: {done} downloaded, {skipped} skipped, {failed} failed, of {total}", flush=True)
    if fails:
        print("FAILED IDS: " + ",".join(fails), flush=True)

if __name__ == "__main__":
    main()
