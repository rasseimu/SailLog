#!/bin/zsh
# Wait for the in-flight download to finish, then run idempotent mop-up passes
# for any 403-failed videos. download.py skips anything already on disk/in archive,
# so each pass only retries the stragglers. Long gaps let the IP throttle reset.
cd ~/Documents/sailing/prodl
echo "=== mopup orchestrator started ==="

# 1) wait for the current run to complete
while pgrep -f "download.py" >/dev/null; do sleep 30; done
echo "=== initial pass finished; beginning mop-up ==="

DEST="$HOME/Library/CloudStorage/GoogleDrive-cy23247@shibaura-it.ac.jp/マイドライブ/練習動画/プロ動画"
target=204
for pass in 1 2 3 4 5; do
  have=$(ls "$DEST" | grep -c 風速)
  echo "--- before mop-up pass $pass: $have/$target on disk ---"
  if [ "$have" -ge "$target" ]; then echo "all present; done"; break; fi
  echo "cooling 300s to let throttle reset before pass $pass"
  sleep 300
  python3 download.py >> mopup.log 2>&1
  echo "--- mop-up pass $pass complete ---"
done

final=$(ls "$DEST" | grep -c 風速)
echo "=== MOPUP DONE: $final/$target videos present ==="
