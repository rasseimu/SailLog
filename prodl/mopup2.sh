#!/bin/zsh
# Focused mop-up for the ~38 remaining videos. Longer gaps (15 min) so the per-IP
# throttle FULLY resets between passes — pass 4 earlier proved a cold throttle recovers ~47.
cd ~/Documents/sailing/prodl
DEST="$HOME/Library/CloudStorage/GoogleDrive-cy23247@shibaura-it.ac.jp/マイドライブ/練習動画/プロ動画"
target=204
echo "=== mopup2 started (long-gap passes) ==="
for pass in 1 2 3 4 5 6 7 8; do
  have=$(ls "$DEST" | grep -c 風速)
  echo "--- before pass $pass: $have/$target ---"
  if [ "$have" -ge "$target" ]; then echo "complete"; break; fi
  echo "cooling 900s for full throttle reset before pass $pass"
  sleep 900
  python3 download.py >> mopup2.log 2>&1
  echo "--- pass $pass done: $(ls "$DEST" | grep -c 風速)/$target ---"
done
echo "=== MOPUP2 DONE: $(ls "$DEST" | grep -c 風速)/$target present ==="
