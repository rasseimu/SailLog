# 動画データ 安全運用ルール（データ消失の再発防止）

2026-08-16 に一括リネームで約475本の練習動画を失った。原因は Google Drive
マウント上で `os.rename` が既存ファイルを**黙って上書き**したこと。以下を**必ず**守る。

## 大原則

1. **一括操作の前に、Drive 上で対象フォルダを複製する**（= バックアップ）。
2. **リネームは `safe_rename.py` 経由でのみ行う**（生 `os.rename` / `mv` は禁止）。

この2つのどちらか一方でも守れば今回の事故は起きなかった。両方やる。

---

## 手順（一括リネームをやるとき）

### ステップ1: Drive 上に複製フォルダを作る（バックアップ）

一括操作の直前に、対象フォルダ（例 `練習動画/2026練習`）を Drive 上で丸ごと複製する。
複製は **あなた自身が所有者** になるので、万一また消えても**自分のゴミ箱**から戻せる
（今回は他メンバー所有でゴミ箱に触れず復旧できなかった）。

やり方の候補:
- **Claude に頼む**: API (`copy_file`) で `_backup_YYYYMMDD` フォルダへ全ファイルを複製。
  本数が多いと時間はかかるが、確実で所有者も自分になる。
- **Drive ウェブ**: フォルダ内を全選択 →「コピーを作成」。フォルダ自体はコピー不可なので
  ファイル単位で。手早いが所有者は元のまま。

> ⚠️ マウント上で `cp -R` は動画バイトを全ダウンロードするので数百GB。基本は使わない。

### ステップ2: `safe_rename.py` でリネーム

生のリネームは絶対に書かない。必ずこのモジュールを通す:

```python
from safe_rename import plan_unique_targets, apply_plan

# (元パス, 付けたい名前<拡張子なし>) のリスト
desired = [(path, "20260329_1030-南南西-4"), ...]

root = Path.home() / "Google Drive/マイドライブ/練習動画/2026練習"
plans = plan_unique_targets(root, desired)          # 衝突しない一意な名前を割当
apply_plan(plans, "undo.csv", root=root, dry_run=True)   # まず必ず dry run
apply_plan(plans, "undo.csv", root=root, dry_run=False)  # 件数一致を確認して実行
```

`safe_rename.py` が構造的に保証すること:
- **絶対に上書きしない** (`guarded_move` が既存ターゲットで例外)
- **一意な名前を計画時に確定**（`exists()` 頼みにしない）
- **二相リネーム** `元 → 一意な一時名 → 最終` でスワップ上書きを防止
- **実行前後で本数を照合**（不一致なら警告して止める）
- **undo.csv に全件記録**、失敗ファイルはスキップして再実行で再開

自己テストで挙動を確認できる:

```bash
python3 safe_rename.py --selftest
# PASS: guarded_move refused to overwrite ...
# PASS: collision -> ['same.mov', 'same_2.mov']
# PASS: both original contents preserved (no data lost)
```

---

## やってはいけないこと

- ❌ マウント上で生の `os.rename` / `Path.rename` / `mv`
- ❌ 計画時 `exists()` で衝突回避したつもりになる（まだ何も動いてないので全部 false）
- ❌ dry run を飛ばしていきなり実行
- ❌ バックアップ複製を作らずに一括操作
