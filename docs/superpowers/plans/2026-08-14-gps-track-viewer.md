# GPS軌跡ビューア（モック）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ブラウザ上でGPS軌跡CSVを選択・時間クロップ・時系列再生し、別GPS軌跡やタグCSVを重ねて可視化する、完全クライアント側の静的モックサイトを新規リポジトリで作る。

**Architecture:** 依存ライブラリなしのバニラES モジュール + Canvas 2D。純粋関数（時刻/CSV/種別判定/GPSパース/外れ値除去/タグ/投影/補間/時間軸）を DOM 非依存モジュールに切り出し `node --test` で単体テスト。描画・操作系（viewport/renderer/timeline/playback/app）は Canvas/DOM に依存するため手動確認。`python3 -m http.server` で静的配信。

**Tech Stack:** HTML5 + CSS + Vanilla JavaScript (ES modules) + Canvas 2D。テストは Node.js 組み込み `node:test` / `node:assert`（v22）。ビルドツール・npm依存なし。

**Spec:** `docs/superpowers/specs/2026-08-14-gps-track-viewer-design.md`（現 sailing リポジトリ内。新リポジトリの `docs/` にもコピーする）

## Global Constraints

- リポジトリ場所: `~/Documents/sailviz`（sailing リポジトリの**兄弟**ディレクトリ）。独立した新規 `git init`。
- runtime 依存ライブラリを追加しない（CSVパースも自前）。`package.json` はテストスクリプト用のみ、`dependencies` 空。
- 全 `src/*.js` は ES モジュール（`export`）。純粋モジュール（time/csv/detect/gps/tags/projection/interpolate/viewport/timeaxis）は `document`/`window`/`canvas` を import・参照しない。
- `time` 列はエポック**ナノ秒**。主時刻に採用し ms(number) へ変換、昇順ソート。
- GPS必須列: `time, latitude, longitude`。欠落ファイルは読込エラー通知。
- 外れ値除去は**既定ON**、閾値 `MAX_SPEED_MPS = 25`。精度フィルタは**既定OFF**。
- 座標系: 正距円筒。ローカル平面 `x=(lon−lon0)·cos(lat0)`, `y=(lat−lat0)`、北が上（画面Yは下向きなので描画時に反転）。
- ブラウザはデスクトップ前提。Chrome/Safari 最新で動けばよい。
- テスト実行コマンド: リポジトリ直下で `node --test`。

---

## File Structure

```
~/Documents/sailviz/
  index.html            # レイアウト骨格 + module script 読込
  styles.css            # レイアウト/配色
  package.json          # {"type":"module","scripts":{"test":"node --test"}} 依存なし
  src/
    time.js             # parseTime(value) -> epoch ms | NaN            [pure]
    csv.js              # parseCsv(text) -> {header, rows}              [pure]
    detect.js           # detectType(header) -> 'gps'|'tag'|'unknown'  [pure]
    gps.js              # parseGpsPoints / rejectOutliers / haversine  [pure]
    tags.js             # parseTags(header, rows) -> Event[]           [pure]
    projection.js       # fitBounds / project / computeBounds          [pure]
    viewport.js         # worldToScreen / screenToWorld / pan / zoomAt [pure]
    interpolate.js      # positionAt(points, t) -> {lat,lon}|null      [pure]
    timeaxis.js         # globalRange / trackLookupTime / clamp        [pure]
    renderer.js         # drawScene(ctx, state)                        [DOM]
    timeline.js         # タイムライン描画 + クロップ/playhead操作      [DOM]
    playback.js         # 再生クロック(rAF) + tick                     [DOM]
    app.js              # 状態/配線/読込/D&D/サイドバー                 [DOM]
  sample-data/          # gps/ の3CSVをコピー
  docs/                 # 引き継ぐmd + spec のコピー
  test/
    time.test.js
    csv.test.js
    detect.test.js
    gps.test.js
    tags.test.js
    projection.test.js
    viewport.test.js
    interpolate.test.js
    timeaxis.test.js
  README.md
```

**Data shapes（全タスク共通の型）**

```
Point  = { t:number, lat:number, lon:number, speed:number|null, bearing:number|null, accuracy:number|null }
Track  = { id:string, name:string, color:string, visible:boolean, points:Point[],
           bounds:{minLat,maxLat,minLon,maxLon}, tRange:{start:number,end:number} }
Event  = { kind:'point'|'range', t:number, tEnd:number|null, label:string, lat:number|null, lon:number|null }
Bounds = { minLat:number, maxLat:number, minLon:number, maxLon:number }
Transform = { scale:number, cx:number, cy:number, w:number, h:number }  // scale=px/world単位, (cx,cy)=画面中心のworld点
```

---

## Task 1: リポジトリ初期化とテスト土台

**Files:**
- Create: `~/Documents/sailviz/package.json`
- Create: `~/Documents/sailviz/.gitignore`
- Create: `~/Documents/sailviz/test/smoke.test.js`

**Interfaces:**
- Consumes: なし
- Produces: `node --test` が動作する空リポジトリ。以降の全タスクの土台。

- [ ] **Step 1: リポジトリ作成と git 初期化**

```bash
mkdir -p ~/Documents/sailviz/src ~/Documents/sailviz/test ~/Documents/sailviz/sample-data ~/Documents/sailviz/docs
cd ~/Documents/sailviz
git init
```

- [ ] **Step 2: package.json 作成**

`~/Documents/sailviz/package.json`:
```json
{
  "name": "sailviz",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "description": "Client-side GPS track viewer (mock) for sailing practice logs",
  "scripts": {
    "test": "node --test",
    "serve": "python3 -m http.server 8000"
  }
}
```

- [ ] **Step 3: .gitignore 作成**

`~/Documents/sailviz/.gitignore`:
```
.DS_Store
node_modules/
```

- [ ] **Step 4: スモークテスト作成**

`~/Documents/sailviz/test/smoke.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';

test('test runner works', () => {
  assert.equal(1 + 1, 2);
});
```

- [ ] **Step 5: テスト実行して通ることを確認**

Run: `cd ~/Documents/sailviz && node --test`
Expected: PASS（1 test passed）

- [ ] **Step 6: Commit**

```bash
cd ~/Documents/sailviz
git add -A
git commit -m "chore: scaffold sailviz repo with node --test harness"
```

---

## Task 2: 時刻パーサ（time.js）

**Files:**
- Create: `~/Documents/sailviz/src/time.js`
- Test: `~/Documents/sailviz/test/time.test.js`

**Interfaces:**
- Consumes: なし
- Produces: `parseTime(value: string|number) -> number`（epoch ms。失敗時 `NaN`）

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/time.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseTime } from '../src/time.js';

test('ns integer -> ms', () => {
  // 1786078509603689000 ns == 1786078509603.689 ms
  assert.equal(parseTime(1786078509603689000), 1786078509603.689);
});

test('ns string -> ms', () => {
  assert.equal(parseTime('1786078509603689000'), 1786078509603.689);
});

test('ms-scale number passes through', () => {
  assert.equal(parseTime(1786078509603), 1786078509603);
});

test('ISO string -> ms', () => {
  assert.equal(parseTime('2026-08-07T00:00:00.000Z'), Date.parse('2026-08-07T00:00:00.000Z'));
});

test('garbage -> NaN', () => {
  assert.ok(Number.isNaN(parseTime('not-a-time')));
  assert.ok(Number.isNaN(parseTime('')));
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/time.test.js`
Expected: FAIL（Cannot find module '../src/time.js'）

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/time.js`:
```javascript
// 入力(string|number)を epoch ms に正規化する。失敗時は NaN。
// - 桁の大きい数値(>1e15)は epoch ns とみなし /1e6
// - それ以外の数値は既に ms 相当としてそのまま
// - 文字列は上記数値判定 -> だめなら Date.parse(ISO想定)
export function parseTime(value) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return NaN;
    return value > 1e15 ? value / 1e6 : value;
  }
  if (typeof value !== 'string') return NaN;
  const s = value.trim();
  if (s === '') return NaN;
  if (/^-?\d+(\.\d+)?$/.test(s)) {
    const n = Number(s);
    return n > 1e15 ? n / 1e6 : n;
  }
  const parsed = Date.parse(s);
  return Number.isNaN(parsed) ? NaN : parsed;
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/time.test.js`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: time parser (ns/ms/ISO -> epoch ms)"
```

---

## Task 3: CSV低レベルパーサ（csv.js）

**Files:**
- Create: `~/Documents/sailviz/src/csv.js`
- Test: `~/Documents/sailviz/test/csv.test.js`

**Interfaces:**
- Consumes: なし
- Produces: `parseCsv(text: string) -> { header: string[], rows: string[][] }`
  header はトリム済み原文字列配列、rows は各セルtrim済み文字列。空行は無視。

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/csv.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseCsv } from '../src/csv.js';

test('parses header and rows', () => {
  const { header, rows } = parseCsv('time,lat,lon\n1,2,3\n4,5,6\n');
  assert.deepEqual(header, ['time', 'lat', 'lon']);
  assert.deepEqual(rows, [['1', '2', '3'], ['4', '5', '6']]);
});

test('ignores blank lines and trims cells', () => {
  const { rows } = parseCsv('a,b\n 1 , 2 \n\n3,4\n');
  assert.deepEqual(rows, [['1', '2'], ['3', '4']]);
});

test('handles CRLF line endings', () => {
  const { header, rows } = parseCsv('a,b\r\n1,2\r\n');
  assert.deepEqual(header, ['a', 'b']);
  assert.deepEqual(rows, [['1', '2']]);
});

test('empty input -> empty header/rows', () => {
  const { header, rows } = parseCsv('');
  assert.deepEqual(header, []);
  assert.deepEqual(rows, []);
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/csv.test.js`
Expected: FAIL（Cannot find module）

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/csv.js`:
```javascript
// 単純なCSV（引用符・カンマ埋め込み非対応）を {header, rows} に分解。
// Sensor Logger / タグCSV はいずれも素直なカンマ区切りのため十分。
export function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== '');
  if (lines.length === 0) return { header: [], rows: [] };
  const header = lines[0].split(',').map((c) => c.trim());
  const rows = lines.slice(1).map((l) => l.split(',').map((c) => c.trim()));
  return { header, rows };
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/csv.test.js`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: minimal CSV parser (header + rows)"
```

---

## Task 4: ファイル種別判定（detect.js）

**Files:**
- Create: `~/Documents/sailviz/src/detect.js`
- Test: `~/Documents/sailviz/test/detect.test.js`

**Interfaces:**
- Consumes: なし
- Produces: `detectType(header: string[]) -> 'gps' | 'tag' | 'unknown'`
  判定順: `label` を含む or (`start`&`end`) を含む → `'tag'`。
  次に `time`,`latitude`,`longitude` を全て含む → `'gps'`。それ以外 `'unknown'`。

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/detect.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { detectType } from '../src/detect.js';

test('sensor logger header -> gps', () => {
  const h = ['time', 'seconds_elapsed', 'latitude', 'longitude', 'speed', 'bearing', 'horizontalAccuracy'];
  assert.equal(detectType(h), 'gps');
});

test('label column -> tag', () => {
  assert.equal(detectType(['time', 'label']), 'tag');
});

test('start/end -> tag (range)', () => {
  assert.equal(detectType(['start', 'end', 'label']), 'tag');
});

test('case-insensitive', () => {
  assert.equal(detectType(['Time', 'Latitude', 'Longitude', 'Speed']), 'gps');
  assert.equal(detectType(['Start', 'End']), 'tag');
});

test('missing required -> unknown', () => {
  assert.equal(detectType(['foo', 'bar']), 'unknown');
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/detect.test.js`
Expected: FAIL

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/detect.js`:
```javascript
// ヘッダー列名からファイル種別を判定する。
export function detectType(header) {
  const h = new Set(header.map((c) => c.toLowerCase()));
  if (h.has('label') || (h.has('start') && h.has('end'))) return 'tag';
  if (h.has('time') && h.has('latitude') && h.has('longitude')) return 'gps';
  return 'unknown';
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/detect.test.js`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: CSV type detection (gps/tag/unknown)"
```

---

## Task 5: GPSパース（gps.js: parseGpsPoints）

**Files:**
- Create: `~/Documents/sailviz/src/gps.js`
- Test: `~/Documents/sailviz/test/gps.test.js`

**Interfaces:**
- Consumes: `parseTime`（time.js）
- Produces: `parseGpsPoints(header: string[], rows: string[][]) -> Point[]`
  - 列名（小文字照合）で index 解決。必須: `time,latitude,longitude`。任意: `speed,bearing,horizontalaccuracy`。
  - `time`/`lat`/`lon` が NaN の行、lat∉[-90,90] / lon∉[-180,180] の行はスキップ。
  - 任意列は欠損/NaN のとき `null`。
  - `t` 昇順ソートして返す。

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/gps.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseGpsPoints } from '../src/gps.js';

const HEADER = ['time', 'latitude', 'longitude', 'speed', 'bearing', 'horizontalAccuracy'];

test('parses rows into sorted points with ns->ms', () => {
  // 実データ相当の Sensor Logger ns（いずれも >1e15 で ns->ms 変換が一様に効く）
  const rows = [
    ['1786078534949943000', '35.3', '139.48', '1.5', '90', '20'], // 後 -> pts[1]
    ['1786078509603689000', '35.1', '139.40', '2.5', '80', '30'], // 先 -> pts[0]
  ];
  const pts = parseGpsPoints(HEADER, rows);
  assert.equal(pts.length, 2);
  assert.ok(pts[0].t < pts[1].t, 'sorted ascending by t');
  assert.equal(pts[0].lat, 35.1);
  assert.equal(pts[0].speed, 2.5);
  assert.equal(pts[1].accuracy, 20);
});

test('skips rows with invalid lat/lon/time', () => {
  const rows = [
    ['1000000000000000', '35.3', '139.48', '', '', ''],
    ['bad', '35.3', '139.48', '', '', ''],
    ['1000000000000001', '999', '139.48', '', '', ''],   // lat out of range
    ['1000000000000002', '35.3', '', '', '', ''],         // lon NaN
  ];
  const pts = parseGpsPoints(HEADER, rows);
  assert.equal(pts.length, 1);
});

test('optional missing columns become null', () => {
  const pts = parseGpsPoints(['time', 'latitude', 'longitude'],
    [['1000000000000000', '35.3', '139.48']]);
  assert.equal(pts[0].speed, null);
  assert.equal(pts[0].bearing, null);
  assert.equal(pts[0].accuracy, null);
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/gps.test.js`
Expected: FAIL

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/gps.js`:
```javascript
import { parseTime } from './time.js';

function colIndex(header, name) {
  return header.findIndex((c) => c.toLowerCase() === name);
}

function numOrNull(cell) {
  if (cell === undefined || cell === '') return null;
  const n = Number(cell);
  return Number.isFinite(n) ? n : null;
}

// header/rows から Point[] を生成。必須列欠損・不正行はスキップ、t昇順ソート。
export function parseGpsPoints(header, rows) {
  const iTime = colIndex(header, 'time');
  const iLat = colIndex(header, 'latitude');
  const iLon = colIndex(header, 'longitude');
  const iSpeed = colIndex(header, 'speed');
  const iBearing = colIndex(header, 'bearing');
  const iAcc = colIndex(header, 'horizontalaccuracy');
  if (iTime < 0 || iLat < 0 || iLon < 0) return [];

  const points = [];
  for (const row of rows) {
    const t = parseTime(row[iTime]);
    const lat = Number(row[iLat]);
    const lon = Number(row[iLon]);
    if (Number.isNaN(t)) continue;
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) continue;
    if (!Number.isFinite(lon) || lon < -180 || lon > 180) continue;
    points.push({
      t,
      lat,
      lon,
      speed: iSpeed >= 0 ? numOrNull(row[iSpeed]) : null,
      bearing: iBearing >= 0 ? numOrNull(row[iBearing]) : null,
      accuracy: iAcc >= 0 ? numOrNull(row[iAcc]) : null,
    });
  }
  points.sort((a, b) => a.t - b.t);
  return points;
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/gps.test.js`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: parse GPS rows into sorted points"
```

---

## Task 6: 外れ値除去とハバーサイン（gps.js: rejectOutliers）

**Files:**
- Modify: `~/Documents/sailviz/src/gps.js`
- Test: `~/Documents/sailviz/test/gps.test.js`（追記）

**Interfaces:**
- Consumes: なし（Point[] を受ける）
- Produces:
  - `haversineMeters(a: Point, b: Point) -> number`（2点間の距離m）
  - `MAX_SPEED_MPS = 25`（export 定数）
  - `rejectOutliers(points: Point[], maxSpeedMps=MAX_SPEED_MPS) -> { points: Point[], removed: number }`
    - t昇順前提。直前の**採用点**との推定速度 `dist/Δt` が閾値超、または `Δt<=0` の点を除去。

- [ ] **Step 1: 失敗するテストを書く（追記）**

`~/Documents/sailviz/test/gps.test.js` の末尾に追記:
```javascript
import { rejectOutliers, haversineMeters, MAX_SPEED_MPS } from '../src/gps.js';

test('haversine ~111km per degree latitude', () => {
  const d = haversineMeters({ lat: 35, lon: 139 }, { lat: 36, lon: 139 });
  assert.ok(Math.abs(d - 111000) < 500, `got ${d}`);
});

test('rejects a spike point', () => {
  // 1秒ごとに緯度がわずかに動く現実的な列に、1点だけ遠方スパイクを差し込む
  const base = [
    { t: 0, lat: 35.300, lon: 139.480 },
    { t: 1000, lat: 35.3001, lon: 139.4801 },
    { t: 2000, lat: 40.000, lon: 145.000 }, // spike (>25 m/s)
    { t: 3000, lat: 35.3002, lon: 139.4802 },
  ];
  const { points, removed } = rejectOutliers(base);
  assert.equal(removed, 1);
  assert.equal(points.length, 3);
  assert.ok(!points.some((p) => p.lat === 40));
});

test('drops duplicate/backwards timestamps', () => {
  const { points, removed } = rejectOutliers([
    { t: 0, lat: 35.30, lon: 139.48 },
    { t: 0, lat: 35.30, lon: 139.48 }, // dt<=0
  ]);
  assert.equal(points.length, 1);
  assert.equal(removed, 1);
});

test('MAX_SPEED_MPS is 25', () => {
  assert.equal(MAX_SPEED_MPS, 25);
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/gps.test.js`
Expected: FAIL（rejectOutliers/haversineMeters/MAX_SPEED_MPS 未定義）

- [ ] **Step 3: 最小実装を書く（gps.js に追記）**

`~/Documents/sailviz/src/gps.js` の末尾に追記:
```javascript
export const MAX_SPEED_MPS = 25;

const R_EARTH_M = 6371000;
const toRad = (deg) => (deg * Math.PI) / 180;

// 2点間の大円距離（メートル）
export function haversineMeters(a, b) {
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R_EARTH_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

// 直前の採用点との推定速度が閾値超、または dt<=0 の点を外れ値として除去。
// t昇順であることを前提とする。
export function rejectOutliers(points, maxSpeedMps = MAX_SPEED_MPS) {
  const kept = [];
  let removed = 0;
  for (const p of points) {
    const prev = kept[kept.length - 1];
    if (prev) {
      const dtSec = (p.t - prev.t) / 1000;
      if (dtSec <= 0) { removed++; continue; }
      const speed = haversineMeters(prev, p) / dtSec;
      if (speed > maxSpeedMps) { removed++; continue; }
    }
    kept.push(p);
  }
  return { points: kept, removed };
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/gps.test.js`
Expected: PASS（全 test）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: spike/outlier rejection + haversine"
```

---

## Task 7: タグ/イベントパース（tags.js）

**Files:**
- Create: `~/Documents/sailviz/src/tags.js`
- Test: `~/Documents/sailviz/test/tags.test.js`

**Interfaces:**
- Consumes: `parseTime`（time.js）
- Produces: `parseTags(header: string[], rows: string[][]) -> Event[]`
  - `start`&`end` あり → `kind:'range'`, `t=start`, `tEnd=end`。
  - それ以外で `time`（無ければ `start`）あり → `kind:'point'`, `tEnd=null`。
  - `label`（無ければ `name`/`text`）→ label文字列（無ければ空文字）。
  - `lat`/`latitude`, `lon`/`longitude` あれば数値、無ければ null。
  - t が NaN の行はスキップ。

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/tags.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseTags } from '../src/tags.js';

test('range events from start/end', () => {
  const ev = parseTags(['start', 'end', 'label'],
    [['1000000000000000', '1000000000005000', 'upwind']]);
  assert.equal(ev.length, 1);
  assert.equal(ev[0].kind, 'range');
  assert.equal(ev[0].label, 'upwind');
  assert.ok(ev[0].tEnd > ev[0].t);
});

test('point events from time', () => {
  const ev = parseTags(['time', 'label'], [['1000000000000000', 'mark']]);
  assert.equal(ev[0].kind, 'point');
  assert.equal(ev[0].tEnd, null);
  assert.equal(ev[0].label, 'mark');
});

test('optional lat/lon parsed, else null', () => {
  const withPos = parseTags(['time', 'label', 'lat', 'lon'],
    [['1000000000000000', 'x', '35.3', '139.48']]);
  assert.equal(withPos[0].lat, 35.3);
  assert.equal(withPos[0].lon, 139.48);
  const noPos = parseTags(['time', 'label'], [['1000000000000000', 'x']]);
  assert.equal(noPos[0].lat, null);
});

test('skips rows with invalid time', () => {
  const ev = parseTags(['time', 'label'], [['bad', 'x'], ['1000000000000000', 'ok']]);
  assert.equal(ev.length, 1);
  assert.equal(ev[0].label, 'ok');
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/tags.test.js`
Expected: FAIL

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/tags.js`:
```javascript
import { parseTime } from './time.js';

function idx(header, ...names) {
  for (const name of names) {
    const i = header.findIndex((c) => c.toLowerCase() === name);
    if (i >= 0) return i;
  }
  return -1;
}

function numOrNull(cell) {
  if (cell === undefined || cell === '') return null;
  const n = Number(cell);
  return Number.isFinite(n) ? n : null;
}

// header/rows から Event[] を生成。start&end=range, それ以外=point。
export function parseTags(header, rows) {
  const iStart = idx(header, 'start');
  const iEnd = idx(header, 'end');
  const iTime = idx(header, 'time');
  const iLabel = idx(header, 'label', 'name', 'text');
  const iLat = idx(header, 'lat', 'latitude');
  const iLon = idx(header, 'lon', 'longitude');
  const isRange = iStart >= 0 && iEnd >= 0;
  const iPrimary = isRange ? iStart : (iTime >= 0 ? iTime : iStart);
  if (iPrimary < 0) return [];

  const events = [];
  for (const row of rows) {
    const t = parseTime(row[iPrimary]);
    if (Number.isNaN(t)) continue;
    const tEnd = isRange ? parseTime(row[iEnd]) : null;
    events.push({
      kind: isRange ? 'range' : 'point',
      t,
      tEnd: isRange && !Number.isNaN(tEnd) ? tEnd : null,
      label: iLabel >= 0 ? (row[iLabel] ?? '') : '',
      lat: iLat >= 0 ? numOrNull(row[iLat]) : null,
      lon: iLon >= 0 ? numOrNull(row[iLon]) : null,
    });
  }
  return events;
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/tags.test.js`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: parse tag/event CSV (point/range)"
```

---

## Task 8: 投影とフィット（projection.js）

**Files:**
- Create: `~/Documents/sailviz/src/projection.js`
- Test: `~/Documents/sailviz/test/projection.test.js`

**Interfaces:**
- Consumes: なし
- Produces:
  - `computeBounds(tracks: Track[]) -> Bounds | null`（可視トラックの全点の外接矩形。点が無ければ null）
  - `makeProjection(bounds: Bounds) -> { lat0, lon0, kx }`（kx=cos(lat0[rad])）
  - `project(lat, lon, proj) -> { x, y }`（ローカル平面。x東正・y北正）
  - `fitTransform(bounds, w, h, marginFrac=0.05) -> Transform`（外接矩形をw×hにアスペクト維持でフィット）

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/projection.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computeBounds, makeProjection, project, fitTransform } from '../src/projection.js';

function track(points) {
  return { visible: true, points };
}

test('computeBounds over visible tracks', () => {
  const b = computeBounds([
    track([{ lat: 35.0, lon: 139.0 }, { lat: 35.5, lon: 139.5 }]),
    track([{ lat: 34.9, lon: 139.6 }]),
  ]);
  assert.deepEqual(b, { minLat: 34.9, maxLat: 35.5, minLon: 139.0, maxLon: 139.6 });
});

test('computeBounds ignores invisible + empty -> null', () => {
  assert.equal(computeBounds([{ visible: false, points: [{ lat: 1, lon: 1 }] }]), null);
});

test('project: north is +y, east is +x, origin at center', () => {
  const b = { minLat: 35, maxLat: 36, minLon: 139, maxLon: 140 };
  const proj = makeProjection(b);
  const center = project(35.5, 139.5, proj);
  assert.ok(Math.abs(center.x) < 1e-9 && Math.abs(center.y) < 1e-9);
  const north = project(36, 139.5, proj);
  assert.ok(north.y > 0);
  const east = project(35.5, 140, proj);
  assert.ok(east.x > 0);
});

test('fitTransform keeps aspect ratio (uniform scale)', () => {
  const b = { minLat: 35, maxLat: 35.1, minLon: 139, maxLon: 139.2 };
  const t = fitTransform(b, 800, 400, 0.05);
  assert.ok(t.scale > 0 && Number.isFinite(t.scale));
  assert.equal(t.w, 800);
  assert.equal(t.h, 400);
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/projection.test.js`
Expected: FAIL

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/projection.js`:
```javascript
// 可視トラック全点の外接矩形。点が無ければ null。
export function computeBounds(tracks) {
  let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
  let any = false;
  for (const tr of tracks) {
    if (!tr.visible) continue;
    for (const p of tr.points) {
      any = true;
      if (p.lat < minLat) minLat = p.lat;
      if (p.lat > maxLat) maxLat = p.lat;
      if (p.lon < minLon) minLon = p.lon;
      if (p.lon > maxLon) maxLon = p.lon;
    }
  }
  return any ? { minLat, maxLat, minLon, maxLon } : null;
}

// 正距円筒: 基準は外接矩形の中心。kx=cos(lat0) で経度方向を圧縮しアスペクト補正。
export function makeProjection(bounds) {
  const lat0 = (bounds.minLat + bounds.maxLat) / 2;
  const lon0 = (bounds.minLon + bounds.maxLon) / 2;
  return { lat0, lon0, kx: Math.cos((lat0 * Math.PI) / 180) };
}

// ローカル平面(度スケール)。x=東正, y=北正。
export function project(lat, lon, proj) {
  return { x: (lon - proj.lon0) * proj.kx, y: lat - proj.lat0 };
}

// 外接矩形を w×h にアスペクト維持でフィットする Transform を返す。
// (cx,cy) は world 中心 = (0,0)。scale = px / world単位。
export function fitTransform(bounds, w, h, marginFrac = 0.05) {
  const proj = makeProjection(bounds);
  const c1 = project(bounds.minLat, bounds.minLon, proj);
  const c2 = project(bounds.maxLat, bounds.maxLon, proj);
  const worldW = Math.max(Math.abs(c2.x - c1.x), 1e-9);
  const worldH = Math.max(Math.abs(c2.y - c1.y), 1e-9);
  const usableW = w * (1 - 2 * marginFrac);
  const usableH = h * (1 - 2 * marginFrac);
  const scale = Math.min(usableW / worldW, usableH / worldH);
  return { scale, cx: 0, cy: 0, w, h, proj };
}
```

Note: `fitTransform` は `proj` も Transform に同梱して返す（renderer が lat/lon→world 変換に使う）。`Transform` 型に `proj` フィールドを追加した形（`{scale, cx, cy, w, h, proj}`）。

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/projection.test.js`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: equirectangular projection + fit-to-bounds transform"
```

---

## Task 9: ビューポート変換（viewport.js）

**Files:**
- Create: `~/Documents/sailviz/src/viewport.js`
- Test: `~/Documents/sailviz/test/viewport.test.js`

**Interfaces:**
- Consumes: `Transform`（projection.js の fitTransform が返す形。`{scale,cx,cy,w,h,proj}`）
- Produces:
  - `worldToScreen({x,y}, T) -> { px, py }`（py は下向き。北を上に見せるため y 反転）
  - `screenToWorld({px,py}, T) -> { x, y }`
  - `pan(T, dpx, dpy) -> T`（画面ドラッグ量だけ中心を移動した新 Transform）
  - `zoomAt(T, px, py, factor) -> T`（カーソル(px,py)固定でズーム。factor>1 で拡大）

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/viewport.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { worldToScreen, screenToWorld, pan, zoomAt } from '../src/viewport.js';

const T = { scale: 100, cx: 0, cy: 0, w: 800, h: 600, proj: null };

test('center world maps to screen center', () => {
  const s = worldToScreen({ x: 0, y: 0 }, T);
  assert.deepEqual(s, { px: 400, py: 300 });
});

test('north (+y) goes up (smaller py)', () => {
  assert.ok(worldToScreen({ x: 0, y: 1 }, T).py < 300);
});

test('screenToWorld is inverse of worldToScreen', () => {
  const w0 = { x: 0.7, y: -0.3 };
  const s = worldToScreen(w0, T);
  const w1 = screenToWorld(s, T);
  assert.ok(Math.abs(w1.x - w0.x) < 1e-9 && Math.abs(w1.y - w0.y) < 1e-9);
});

test('zoomAt keeps the cursor world point fixed', () => {
  const cursor = { px: 550, py: 200 };
  const before = screenToWorld(cursor, T);
  const T2 = zoomAt(T, cursor.px, cursor.py, 2);
  const after = screenToWorld(cursor, T2);
  assert.ok(Math.abs(after.x - before.x) < 1e-9 && Math.abs(after.y - before.y) < 1e-9);
  assert.ok(T2.scale === 200);
});

test('pan shifts center by pixel delta', () => {
  const T2 = pan(T, 100, 0); // ドラッグで右へ100px -> world中心は左へ
  assert.ok(T2.cx < 0);
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/viewport.test.js`
Expected: FAIL

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/viewport.js`:
```javascript
// world(x東正,y北正) -> screen(px右,py下)。北を上に見せるため y を反転。
export function worldToScreen(p, T) {
  return {
    px: T.w / 2 + (p.x - T.cx) * T.scale,
    py: T.h / 2 - (p.y - T.cy) * T.scale,
  };
}

export function screenToWorld(s, T) {
  return {
    x: T.cx + (s.px - T.w / 2) / T.scale,
    y: T.cy - (s.py - T.h / 2) / T.scale,
  };
}

// 画面ドラッグ(dpx,dpy)ぶん内容を動かす = 中心を逆向きに移動。
export function pan(T, dpx, dpy) {
  return { ...T, cx: T.cx - dpx / T.scale, cy: T.cy + dpy / T.scale };
}

// カーソル(px,py)の world点を固定したままズーム。
export function zoomAt(T, px, py, factor) {
  const before = screenToWorld({ px, py }, T);
  const scaled = { ...T, scale: T.scale * factor };
  const after = screenToWorld({ px, py }, scaled);
  return { ...scaled, cx: scaled.cx + (before.x - after.x), cy: scaled.cy + (before.y - after.y) };
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/viewport.test.js`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: viewport transform (pan/zoom, world<->screen)"
```

---

## Task 10: 位置補間（interpolate.js）

**Files:**
- Create: `~/Documents/sailviz/src/interpolate.js`
- Test: `~/Documents/sailviz/test/interpolate.test.js`

**Interfaces:**
- Consumes: なし（Point[] を受ける、t昇順前提）
- Produces: `positionAt(points: Point[], t: number) -> { lat, lon } | null`
  - `t < points[0].t` または `t > points[last].t` は null。
  - 区間内は二分探索して線形補間。

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/interpolate.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { positionAt } from '../src/interpolate.js';

const PTS = [
  { t: 0, lat: 35.0, lon: 139.0 },
  { t: 1000, lat: 35.0, lon: 139.2 },
  { t: 2000, lat: 35.4, lon: 139.2 },
];

test('exact endpoints', () => {
  assert.deepEqual(positionAt(PTS, 0), { lat: 35.0, lon: 139.0 });
  assert.deepEqual(positionAt(PTS, 2000), { lat: 35.4, lon: 139.2 });
});

test('linear interpolation mid-segment', () => {
  const p = positionAt(PTS, 500);
  assert.ok(Math.abs(p.lat - 35.0) < 1e-9);
  assert.ok(Math.abs(p.lon - 139.1) < 1e-9);
});

test('out of range -> null', () => {
  assert.equal(positionAt(PTS, -1), null);
  assert.equal(positionAt(PTS, 2001), null);
});

test('empty -> null', () => {
  assert.equal(positionAt([], 0), null);
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/interpolate.test.js`
Expected: FAIL

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/interpolate.js`:
```javascript
// t昇順の points から時刻 t の位置を線形補間。範囲外は null。
export function positionAt(points, t) {
  const n = points.length;
  if (n === 0) return null;
  if (t < points[0].t || t > points[n - 1].t) return null;
  // 二分探索: points[hi].t >= t となる最小 hi
  let lo = 0, hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid].t < t) lo = mid + 1;
    else hi = mid;
  }
  if (hi === 0) return { lat: points[0].lat, lon: points[0].lon };
  const a = points[hi - 1];
  const b = points[hi];
  const span = b.t - a.t;
  const f = span === 0 ? 0 : (t - a.t) / span;
  return { lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f };
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/interpolate.test.js`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: linear position interpolation with binary search"
```

---

## Task 11: 時間軸ヘルパ（timeaxis.js）

**Files:**
- Create: `~/Documents/sailviz/src/timeaxis.js`
- Test: `~/Documents/sailviz/test/timeaxis.test.js`

**Interfaces:**
- Consumes: なし（Track[] を受ける。各 Track は `tRange:{start,end}`, `visible`）
- Produces:
  - `globalRange(tracks, mode: 'absolute'|'elapsed') -> { start, end }`
    - absolute: min(start)..max(end)。elapsed: 0..max(end-start)。可視のみ。空なら {start:0,end:0}。
  - `trackLookupTime(track, now, mode) -> number`（そのトラックの点列を引くための絶対時刻。absolute=now, elapsed=track.tRange.start+now）
  - `clamp(v, lo, hi) -> number`

- [ ] **Step 1: 失敗するテストを書く**

`~/Documents/sailviz/test/timeaxis.test.js`:
```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { globalRange, trackLookupTime, clamp } from '../src/timeaxis.js';

const trackA = { visible: true, tRange: { start: 1000, end: 5000 } };
const trackB = { visible: true, tRange: { start: 3000, end: 4000 } };

test('absolute range spans all visible tracks', () => {
  assert.deepEqual(globalRange([trackA, trackB], 'absolute'), { start: 1000, end: 5000 });
});

test('elapsed range starts at 0, ends at longest duration', () => {
  assert.deepEqual(globalRange([trackA, trackB], 'elapsed'), { start: 0, end: 4000 });
});

test('ignores invisible tracks; empty -> zero range', () => {
  assert.deepEqual(globalRange([{ visible: false, tRange: { start: 1, end: 2 } }], 'absolute'),
    { start: 0, end: 0 });
});

test('trackLookupTime maps by mode', () => {
  assert.equal(trackLookupTime(trackA, 500, 'absolute'), 500);
  assert.equal(trackLookupTime(trackA, 500, 'elapsed'), 1500); // start(1000)+500
});

test('clamp', () => {
  assert.equal(clamp(5, 0, 10), 5);
  assert.equal(clamp(-1, 0, 10), 0);
  assert.equal(clamp(11, 0, 10), 10);
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/Documents/sailviz && node --test test/timeaxis.test.js`
Expected: FAIL

- [ ] **Step 3: 最小実装を書く**

`~/Documents/sailviz/src/timeaxis.js`:
```javascript
export function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

// 可視トラックのグローバル時間範囲。absolute=絶対時刻, elapsed=0起点の経過。
export function globalRange(tracks, mode) {
  const visible = tracks.filter((t) => t.visible);
  if (visible.length === 0) return { start: 0, end: 0 };
  if (mode === 'elapsed') {
    const maxDur = Math.max(...visible.map((t) => t.tRange.end - t.tRange.start));
    return { start: 0, end: maxDur };
  }
  return {
    start: Math.min(...visible.map((t) => t.tRange.start)),
    end: Math.max(...visible.map((t) => t.tRange.end)),
  };
}

// トラックの点列を引くための絶対時刻に変換。
export function trackLookupTime(track, now, mode) {
  return mode === 'elapsed' ? track.tRange.start + now : now;
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ~/Documents/sailviz && node --test test/timeaxis.test.js`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: time-axis helpers (global range, elapsed mapping, clamp)"
```

---

## Task 12: HTML/CSS 骨格

**Files:**
- Create: `~/Documents/sailviz/index.html`
- Create: `~/Documents/sailviz/styles.css`

**Interfaces:**
- Consumes: なし
- Produces: DOM要素 id（app.js が参照する契約）:
  `#map`(canvas), `#timeline`(canvas), `#file-input`(input file), `#drop-zone`(div),
  `#track-list`(div), `#tag-list`(div), `#align-mode`(select), `#accuracy-filter`(input checkbox),
  `#play-btn`(button), `#speed-select`(select), `#clock`(span)

- [ ] **Step 1: index.html 作成**

`~/Documents/sailviz/index.html`:
```html
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>SailViz — GPS軌跡ビューア</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header id="topbar">
    <strong>SailViz</strong>
    <label class="btn">CSV読込
      <input type="file" id="file-input" accept=".csv" multiple hidden />
    </label>
    <label>整列:
      <select id="align-mode">
        <option value="absolute">絶対時刻</option>
        <option value="elapsed">経過時間</option>
      </select>
    </label>
    <label><input type="checkbox" id="accuracy-filter" /> 精度フィルタ</label>
    <span id="status"></span>
  </header>

  <main>
    <aside id="sidebar">
      <h2>トラック</h2>
      <div id="track-list"></div>
      <h2>タグ</h2>
      <div id="tag-list"></div>
    </aside>
    <section id="stage">
      <canvas id="map"></canvas>
      <div id="drop-zone">CSVをここにドラッグ&ドロップ</div>
    </section>
  </main>

  <footer id="transport">
    <button id="play-btn">▶</button>
    <label>速度:
      <select id="speed-select">
        <option value="1">1x</option>
        <option value="2">2x</option>
        <option value="4">4x</option>
        <option value="8">8x</option>
      </select>
    </label>
    <span id="clock">--:--:--</span>
    <canvas id="timeline"></canvas>
  </footer>

  <script type="module" src="src/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: styles.css 作成**

`~/Documents/sailviz/styles.css`:
```css
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; font-family: system-ui, sans-serif; }
body { display: flex; flex-direction: column; height: 100vh; color: #1a2733; }
#topbar { display: flex; gap: 14px; align-items: center; padding: 8px 14px;
  background: #0d3b5e; color: #fff; }
#topbar .btn { background: #1c72b8; padding: 4px 10px; border-radius: 4px; cursor: pointer; }
#topbar select { padding: 2px; }
#status { margin-left: auto; font-size: 12px; opacity: 0.85; }
main { flex: 1; display: flex; min-height: 0; }
#sidebar { width: 240px; padding: 10px; overflow-y: auto; background: #f2f5f8;
  border-right: 1px solid #d4dde5; }
#sidebar h2 { font-size: 13px; text-transform: uppercase; color: #5a6b7b; margin: 12px 0 6px; }
#stage { position: relative; flex: 1; min-width: 0; background: #dfeaf2; }
#map { width: 100%; height: 100%; display: block; cursor: grab; }
#map:active { cursor: grabbing; }
#drop-zone { position: absolute; inset: 0; display: flex; align-items: center;
  justify-content: center; font-size: 20px; color: #4a6076; pointer-events: none; }
#drop-zone.hidden { display: none; }
#drop-zone.dragover { background: rgba(28,114,184,0.15); border: 3px dashed #1c72b8; }
#transport { display: flex; gap: 12px; align-items: center; padding: 8px 14px;
  background: #eef2f5; border-top: 1px solid #d4dde5; }
#play-btn { width: 40px; height: 32px; font-size: 16px; cursor: pointer; }
#clock { font-variant-numeric: tabular-nums; min-width: 88px; }
#timeline { flex: 1; height: 48px; cursor: pointer; }
.track-row, .tag-row { display: flex; align-items: center; gap: 6px; font-size: 13px;
  padding: 3px 0; }
.swatch { width: 12px; height: 12px; border-radius: 2px; flex: 0 0 auto; }
.track-row button { margin-left: auto; border: none; background: none; cursor: pointer; color: #b23; }
```

- [ ] **Step 3: 手動確認（静的表示）**

Run: `cd ~/Documents/sailviz && python3 -m http.server 8000`（別ターミナル）
ブラウザで `http://localhost:8000/` を開く。
Expected: ヘッダー/サイドバー/ステージ（"CSVをここに…"）/トランスポート の枠が表示される。
（app.js 未作成のためコンソールに 404/module エラーが出るのは想定内。次タスクで解消。）

- [ ] **Step 4: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: HTML/CSS layout skeleton"
```

---

## Task 13: レンダラ（renderer.js）

**Files:**
- Create: `~/Documents/sailviz/src/renderer.js`

**Interfaces:**
- Consumes: `worldToScreen`(viewport.js), `project`(projection.js), `positionAt`(interpolate.js), `trackLookupTime`(timeaxis.js)
- Produces: `drawScene(ctx, { transform, tracks, events, now, mode, crop })`
  - transform: 現在の `Transform`（proj 同梱）
  - tracks: `Track[]`、events: `Event[]`、now: 現在仮想時刻、mode: 整列、crop: `{start,end}`（グローバル時間）
  - 描画: 背景クリア → 可視トラックのポリライン（crop範囲内点のみ）→ 各トラックの現在位置マーカー → タグピン。

- [ ] **Step 1: renderer.js 作成**

`~/Documents/sailviz/src/renderer.js`:
```javascript
import { worldToScreen } from './viewport.js';
import { project } from './projection.js';
import { positionAt } from './interpolate.js';
import { trackLookupTime } from './timeaxis.js';

function toScreen(lat, lon, T) {
  return worldToScreen(project(lat, lon, T.proj), T);
}

// crop(グローバル時間)を各トラックの絶対時刻窓に変換
function trackWindow(track, crop, mode) {
  if (mode === 'elapsed') {
    return { lo: track.tRange.start + crop.start, hi: track.tRange.start + crop.end };
  }
  return { lo: crop.start, hi: crop.end };
}

export function drawScene(ctx, state) {
  const { transform: T, tracks, events, now, mode, crop } = state;
  ctx.clearRect(0, 0, T.w, T.h);
  if (!T.proj) return;

  // ポリライン
  for (const tr of tracks) {
    if (!tr.visible || tr.points.length < 2) continue;
    const win = trackWindow(tr, crop, mode);
    ctx.beginPath();
    let started = false;
    for (const p of tr.points) {
      if (p.t < win.lo || p.t > win.hi) { started = false; continue; }
      const s = toScreen(p.lat, p.lon, T);
      if (!started) { ctx.moveTo(s.px, s.py); started = true; }
      else ctx.lineTo(s.px, s.py);
    }
    ctx.strokeStyle = tr.color;
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // 現在位置マーカー
  for (const tr of tracks) {
    if (!tr.visible) continue;
    const lookup = trackLookupTime(tr, now, mode);
    const pos = positionAt(tr.points, lookup);
    if (!pos) continue;
    const s = toScreen(pos.lat, pos.lon, T);
    ctx.beginPath();
    ctx.arc(s.px, s.py, 6, 0, Math.PI * 2);
    ctx.fillStyle = tr.color;
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // タグピン（lat/lon があるものだけトラック上に表示）
  for (const ev of events) {
    if (ev.lat == null || ev.lon == null) continue;
    const s = toScreen(ev.lat, ev.lon, T);
    ctx.beginPath();
    ctx.moveTo(s.px, s.py);
    ctx.lineTo(s.px - 6, s.py - 14);
    ctx.lineTo(s.px + 6, s.py - 14);
    ctx.closePath();
    ctx.fillStyle = '#c0392b';
    ctx.fill();
  }
}
```

- [ ] **Step 2: 手動確認は Task 15（app配線後）で実施**

renderer 単体はDOM描画のため、app.js 配線後にまとめて目視確認する。ここではコミットのみ。

- [ ] **Step 3: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: canvas scene renderer (tracks, markers, tag pins)"
```

---

## Task 14: 再生クロック（playback.js）

**Files:**
- Create: `~/Documents/sailviz/src/playback.js`

**Interfaces:**
- Consumes: `requestAnimationFrame`（ブラウザ）
- Produces: `createPlayback({ onTick }) -> { play, pause, toggle, seek, setSpeed, setRange, getNow, isPlaying }`
  - 内部で `now`（グローバル時間ms）を保持。play中は rAF で実経過×speed だけ加算し、`onTick(now)` を毎フレーム呼ぶ。
  - `setRange({start,end})` で再生範囲（=クロップ）を設定。now は範囲内クランプ、末尾到達で自動 pause。

- [ ] **Step 1: playback.js 作成**

`~/Documents/sailviz/src/playback.js`:
```javascript
import { clamp } from './timeaxis.js';

// 再生クロック。onTick(now) を毎フレーム呼ぶ。now はグローバル時間(ms)。
export function createPlayback({ onTick }) {
  let now = 0;
  let range = { start: 0, end: 0 };
  let speed = 1;
  let playing = false;
  let rafId = null;
  let lastTs = 0;

  function frame(ts) {
    if (!playing) return;
    const dt = ts - lastTs;
    lastTs = ts;
    now = clamp(now + dt * speed, range.start, range.end);
    onTick(now);
    if (now >= range.end) { pause(); return; }
    rafId = requestAnimationFrame(frame);
  }

  function play() {
    if (playing || range.end <= range.start) return;
    if (now >= range.end) now = range.start; // 末尾で押したら頭出し
    playing = true;
    lastTs = performance.now();
    rafId = requestAnimationFrame(frame);
  }
  function pause() {
    playing = false;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
  }
  function toggle() { playing ? pause() : play(); }
  function seek(t) { now = clamp(t, range.start, range.end); onTick(now); }
  function setSpeed(x) { speed = x; }
  function setRange(r) {
    range = r;
    now = clamp(now, range.start, range.end);
    onTick(now);
  }
  return {
    play, pause, toggle, seek, setSpeed, setRange,
    getNow: () => now,
    isPlaying: () => playing,
  };
}
```

- [ ] **Step 2: 手動確認は Task 15 で実施**

rAF/performance に依存するため app 配線後に確認。ここではコミットのみ。

- [ ] **Step 3: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: playback clock (rAF, speed, range clamp)"
```

---

## Task 15: タイムライン描画・操作（timeline.js）

**Files:**
- Create: `~/Documents/sailviz/src/timeline.js`

**Interfaces:**
- Consumes: `clamp`(timeaxis.js)
- Produces: `createTimeline(canvas, { onCropChange, onScrub }) -> { render({range, crop, now, events}) }`
  - 横軸 = グローバル `range`。クロップ左右ハンドル、playhead、タグ（▲point/▬range）を描画。
  - ドラッグ: 左ハンドル/右ハンドル → `onCropChange({start,end})`、中央 → `onScrub(t)`。
  - ヒットテストは端から8px以内をハンドル、それ以外を playhead 移動とする。

- [ ] **Step 1: timeline.js 作成**

`~/Documents/sailviz/src/timeline.js`:
```javascript
import { clamp } from './timeaxis.js';

const HANDLE_PX = 8;

export function createTimeline(canvas, { onCropChange, onScrub }) {
  const ctx = canvas.getContext('2d');
  let state = { range: { start: 0, end: 0 }, crop: { start: 0, end: 0 }, now: 0, events: [] };
  let drag = null; // 'left' | 'right' | 'scrub'

  const tToX = (t) => {
    const { start, end } = state.range;
    const w = canvas.width;
    return end <= start ? 0 : ((t - start) / (end - start)) * w;
  };
  const xToT = (x) => {
    const { start, end } = state.range;
    return start + (x / canvas.width) * (end - start);
  };

  function render(next) {
    state = next;
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    // ベースライン
    ctx.fillStyle = '#c7d3dd';
    ctx.fillRect(0, h / 2 - 2, w, 4);
    // クロップ範囲
    const xL = tToX(state.crop.start), xR = tToX(state.crop.end);
    ctx.fillStyle = 'rgba(28,114,184,0.25)';
    ctx.fillRect(xL, 0, xR - xL, h);
    // タグ
    for (const ev of state.events) {
      if (ev.kind === 'range' && ev.tEnd != null) {
        ctx.fillStyle = 'rgba(192,57,43,0.35)';
        ctx.fillRect(tToX(ev.t), h - 10, tToX(ev.tEnd) - tToX(ev.t), 8);
      } else {
        const x = tToX(ev.t);
        ctx.fillStyle = '#c0392b';
        ctx.beginPath();
        ctx.moveTo(x, h - 12); ctx.lineTo(x - 5, h - 2); ctx.lineTo(x + 5, h - 2);
        ctx.closePath(); ctx.fill();
      }
    }
    // ハンドル
    ctx.fillStyle = '#0d3b5e';
    ctx.fillRect(xL - 2, 0, 4, h);
    ctx.fillRect(xR - 2, 0, 4, h);
    // playhead
    const xN = tToX(state.now);
    ctx.strokeStyle = '#e67e22';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(xN, 0); ctx.lineTo(xN, h); ctx.stroke();
  }

  function pickTarget(x) {
    if (Math.abs(x - tToX(state.crop.start)) <= HANDLE_PX) return 'left';
    if (Math.abs(x - tToX(state.crop.end)) <= HANDLE_PX) return 'right';
    return 'scrub';
  }
  function localX(e) {
    const rect = canvas.getBoundingClientRect();
    return ((e.clientX - rect.left) / rect.width) * canvas.width;
  }
  canvas.addEventListener('pointerdown', (e) => {
    drag = pickTarget(localX(e));
    canvas.setPointerCapture(e.pointerId);
    handleDrag(e);
  });
  canvas.addEventListener('pointermove', (e) => { if (drag) handleDrag(e); });
  canvas.addEventListener('pointerup', (e) => { drag = null; canvas.releasePointerCapture(e.pointerId); });

  function handleDrag(e) {
    const t = clamp(xToT(localX(e)), state.range.start, state.range.end);
    if (drag === 'left') onCropChange({ start: Math.min(t, state.crop.end), end: state.crop.end });
    else if (drag === 'right') onCropChange({ start: state.crop.start, end: Math.max(t, state.crop.start) });
    else onScrub(clamp(t, state.crop.start, state.crop.end));
  }

  return { render };
}
```

- [ ] **Step 2: 手動確認は Task 16 で実施**

- [ ] **Step 3: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: timeline render + crop/scrub interaction"
```

---

## Task 16: アプリ配線（app.js）と統合手動確認

**Files:**
- Create: `~/Documents/sailviz/src/app.js`

**Interfaces:**
- Consumes: `parseCsv`(csv.js), `detectType`(detect.js), `parseGpsPoints`/`rejectOutliers`(gps.js),
  `parseTags`(tags.js), `computeBounds`/`fitTransform`(projection.js),
  `pan`/`zoomAt`/`screenToWorld`(viewport.js), `globalRange`(timeaxis.js),
  `drawScene`(renderer.js), `createPlayback`(playback.js), `createTimeline`(timeline.js)
- Produces: なし（トップレベルの配線）

- [ ] **Step 1: app.js 作成**

`~/Documents/sailviz/src/app.js`:
```javascript
import { parseCsv } from './csv.js';
import { detectType } from './detect.js';
import { parseGpsPoints, rejectOutliers } from './gps.js';
import { parseTags } from './tags.js';
import { computeBounds, fitTransform } from './projection.js';
import { pan, zoomAt } from './viewport.js';
import { globalRange } from './timeaxis.js';
import { drawScene } from './renderer.js';
import { createPlayback } from './playback.js';
import { createTimeline } from './timeline.js';

const PALETTE = ['#1c72b8', '#e67e22', '#27ae60', '#8e44ad', '#c0392b', '#16a085'];

const state = {
  tracks: [],
  events: [],
  mode: 'absolute',
  accuracyFilter: false,
  crop: { start: 0, end: 0 },
  transform: { scale: 1, cx: 0, cy: 0, w: 1, h: 1, proj: null },
};

const $ = (id) => document.getElementById(id);
const mapCanvas = $('map');
const mapCtx = mapCanvas.getContext('2d');
const statusEl = $('status');

function resizeCanvas() {
  for (const c of [mapCanvas, $('timeline')]) {
    const r = c.getBoundingClientRect();
    c.width = Math.max(1, Math.floor(r.width));
    c.height = Math.max(1, Math.floor(r.height));
  }
  state.transform.w = mapCanvas.width;
  state.transform.h = mapCanvas.height;
}

const playback = createPlayback({ onTick: () => draw() });
const timeline = createTimeline($('timeline'), {
  onCropChange: (c) => { state.crop = c; playback.setRange(c); draw(); },
  onScrub: (t) => playback.seek(t),
});

function recomputeView() {
  const bounds = computeBounds(state.tracks);
  if (bounds) state.transform = fitTransform(bounds, mapCanvas.width, mapCanvas.height);
  const range = globalRange(state.tracks, state.mode);
  state.crop = { ...range };
  playback.setRange(range);
}

function draw() {
  const now = playback.getNow();
  drawScene(mapCtx, {
    transform: state.transform, tracks: state.tracks, events: state.events,
    now, mode: state.mode, crop: state.crop,
  });
  timeline.render({
    range: globalRange(state.tracks, state.mode), crop: state.crop, now, events: state.events,
  });
  $('clock').textContent = formatClock(now, state.mode, state.crop.start);
  $('drop-zone').classList.toggle('hidden', state.tracks.length > 0 || state.events.length > 0);
}

function formatClock(now, mode, base) {
  if (mode === 'elapsed') {
    const s = Math.max(0, Math.floor(now / 1000));
    return `+${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }
  const d = new Date(now);
  return d.toLocaleTimeString('ja-JP', { hour12: false });
}

async function loadFiles(fileList) {
  for (const file of fileList) {
    const text = await file.text();
    const { header, rows } = parseCsv(text);
    const type = detectType(header);
    if (type === 'gps') addTrack(file.name, header, rows);
    else if (type === 'tag') addTags(header, rows);
    else statusEl.textContent = `未対応の列構成: ${file.name}`;
  }
  recomputeView();
  draw();
  renderSidebar();
}

function addTrack(name, header, rows) {
  let points = parseGpsPoints(header, rows);
  if (state.accuracyFilter) points = points.filter((p) => p.accuracy == null || p.accuracy <= 50);
  const { points: clean, removed } = rejectOutliers(points);
  if (clean.length === 0) { statusEl.textContent = `${name}: 有効点なし`; return; }
  state.tracks.push({
    id: name, name, color: PALETTE[state.tracks.length % PALETTE.length],
    visible: true, points: clean,
    bounds: computeBounds([{ visible: true, points: clean }]),
    tRange: { start: clean[0].t, end: clean[clean.length - 1].t },
  });
  statusEl.textContent = `${name}: ${clean.length}点 (外れ値${removed}点除外)`;
}

function addTags(header, rows) {
  const evs = parseTags(header, rows);
  state.events.push(...evs);
  statusEl.textContent = `タグ ${evs.length}件 読込`;
}

function renderSidebar() {
  const tl = $('track-list'); tl.innerHTML = '';
  state.tracks.forEach((tr, i) => {
    const row = document.createElement('div'); row.className = 'track-row';
    row.innerHTML =
      `<input type="checkbox" ${tr.visible ? 'checked' : ''} data-i="${i}" />` +
      `<span class="swatch" style="background:${tr.color}"></span>` +
      `<span>${tr.name}</span><button data-del="${i}">×</button>`;
    tl.appendChild(row);
  });
  tl.querySelectorAll('input[type=checkbox]').forEach((cb) =>
    cb.addEventListener('change', (e) => {
      state.tracks[+e.target.dataset.i].visible = e.target.checked;
      recomputeView(); draw();
    }));
  tl.querySelectorAll('button[data-del]').forEach((b) =>
    b.addEventListener('click', (e) => {
      state.tracks.splice(+e.target.dataset.del, 1);
      recomputeView(); draw(); renderSidebar();
    }));

  const gl = $('tag-list'); gl.innerHTML = '';
  state.events.forEach((ev) => {
    const row = document.createElement('div'); row.className = 'tag-row';
    row.textContent = `${ev.kind === 'range' ? '▬' : '▲'} ${ev.label || '(無題)'}`;
    gl.appendChild(row);
  });
}

// --- 入力配線 ---
$('file-input').addEventListener('change', (e) => loadFiles(e.target.files));
$('play-btn').addEventListener('click', () => {
  playback.toggle();
  $('play-btn').textContent = playback.isPlaying() ? '⏸' : '▶';
});
$('speed-select').addEventListener('change', (e) => playback.setSpeed(+e.target.value));
$('align-mode').addEventListener('change', (e) => { state.mode = e.target.value; recomputeView(); draw(); });
$('accuracy-filter').addEventListener('change', (e) => {
  state.accuracyFilter = e.target.checked;
  statusEl.textContent = '精度フィルタ変更は次回読込から反映されます';
});

const dz = $('drop-zone');
const stage = $('stage');
['dragover', 'dragenter'].forEach((ev) => stage.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.add('dragover');
}));
['dragleave', 'drop'].forEach((ev) => stage.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.remove('dragover');
}));
stage.addEventListener('drop', (e) => { if (e.dataTransfer?.files?.length) loadFiles(e.dataTransfer.files); });

// pan/zoom
let dragging = null;
mapCanvas.addEventListener('pointerdown', (e) => { dragging = { x: e.offsetX, y: e.offsetY }; });
mapCanvas.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  state.transform = pan(state.transform, e.offsetX - dragging.x, e.offsetY - dragging.y);
  dragging = { x: e.offsetX, y: e.offsetY };
  draw();
});
window.addEventListener('pointerup', () => { dragging = null; });
mapCanvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
  state.transform = zoomAt(state.transform, e.offsetX, e.offsetY, factor);
  draw();
}, { passive: false });

window.addEventListener('resize', () => { resizeCanvas(); recomputeView(); draw(); });
resizeCanvas();
draw();
```

- [ ] **Step 2: 統合手動確認（受け入れ基準の目視）**

Run: `cd ~/Documents/sailviz && python3 -m http.server 8000`、ブラウザで `http://localhost:8000/`。
`sample-data/`（Task 17 でコピー）か `~/Documents/sailing/gps/` の3CSVを使う。以下を確認:
1. CSVをD&D → 軌跡が正しいアスペクト比で描画され、drop-zone が消える。ステータスに点数と外れ値除外数。
2. ▶ で再生 → マーカーが軌跡上を移動。速度 1/2/4/8x が効く。
3. タイムライン中央ドラッグでスクラブ、左右ハンドルでクロップ → 軌跡と再生が範囲限定。
4. 複数CSVを重ね → 色分け表示、チェックで表示切替、× で削除。
5. 整列モードを経過時間に → 複数トラックが頭出し同期、時計表示が `+MM:SS`。
6. マップをドラッグでパン、ホイールでカーソル中心ズーム。
7. タグCSV（Task 17 のサンプル）を読込 → タイムラインに▲/▬、lat/lon付きはマップにピン。

問題があればコンソールエラーを確認し、該当モジュールを修正して再確認。

- [ ] **Step 3: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "feat: app wiring (load, sidebar, pan/zoom, transport, D&D)"
```

---

## Task 17: サンプルデータ・タグ例・ドキュメント

**Files:**
- Create: `~/Documents/sailviz/sample-data/*.csv`（コピー）
- Create: `~/Documents/sailviz/sample-data/tags-points.csv`, `~/Documents/sailviz/sample-data/tags-ranges.csv`
- Create: `~/Documents/sailviz/docs/*`（md コピー）
- Create: `~/Documents/sailviz/README.md`

**Interfaces:**
- Consumes: なし
- Produces: デモ一式とドキュメント。

- [ ] **Step 1: 実データとmdをコピー**

```bash
cd ~/Documents/sailviz
cp ~/Documents/sailing/gps/Location0807.csv ~/Documents/sailing/gps/Location0808.csv ~/Documents/sailing/gps/Location0809.csv sample-data/
cp "$HOME/Documents/sailing/ヨット練習最適化_ハッカソン提案.md" docs/
cp "$HOME/Documents/sailing/芝工セイルログ_提案書.md" docs/
cp "$HOME/Documents/sailing/docs/superpowers/specs/2026-08-14-gps-track-viewer-design.md" docs/
```

- [ ] **Step 2: タグCSVサンプル作成**

1ファイル1ヘッダーが原則（`parseCsv` は1行目をヘッダーとする）。point用とrange用を別ファイルにする。
時刻は Location0807 の範囲に合わせた ns 例（実行時に該当セッションの実時刻へ調整してよい）。

`~/Documents/sailviz/sample-data/tags-points.csv`（点イベント。lat/lon付きはマップにピン）:
```csv
time,label,lat,lon
1786078540000000000,スタート,35.2996,139.4841
1786078700000000000,第1マーク,35.2998,139.4838
```

`~/Documents/sailviz/sample-data/tags-ranges.csv`（区間イベント）:
```csv
start,end,label
1786078560000000000,1786078620000000000,アップウィンド
```

- [ ] **Step 3: README作成**

`~/Documents/sailviz/README.md`:
```markdown
# SailViz — GPS軌跡ビューア（モック）

セーリング練習のGPSログ（Sensor Logger形式CSV）を、ブラウザ上で
選択・時間クロップ・時系列再生し、別のGPS軌跡やタグを重ねて可視化する
完全クライアント側の静的モックサイト。実地図タイル・DBなし。

## 使い方
```bash
python3 -m http.server 8000
# ブラウザで http://localhost:8000/
```
`sample-data/` のCSVをステージにドラッグ&ドロップ。

- 再生: ▶ / 速度 1〜8x / タイムライン中央ドラッグでスクラブ
- クロップ: タイムライン左右ハンドル
- 重ね合わせ: 複数CSVを読み込む（色分け・表示切替・削除）
- 整列: 絶対時刻 / 経過時間
- タグ: `time,label[,lat,lon]`（点） or `start,end,label`（区間）のCSV

## CSV形式
- GPS: Sensor Logger 形式（`time`(ns), `latitude`, `longitude`, 任意 `speed,bearing,horizontalAccuracy`）
- 外れ値（>25 m/s）は自動除去。精度フィルタは任意（ヘッダーのチェック）。

## テスト
```bash
node --test
```
純粋ロジック（パース/投影/補間/時間軸）を単体テスト。描画/操作は手動確認。

## 設計資料
`docs/2026-08-14-gps-track-viewer-design.md`、`docs/ヨット練習最適化_ハッカソン提案.md`
```

- [ ] **Step 4: 全テスト実行**

Run: `cd ~/Documents/sailviz && node --test`
Expected: 全 test PASS。

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/sailviz && git add -A && git commit -m "docs: sample data, tag example, README, carried-over proposals"
```

---

## Self-Review 結果（spec カバレッジ）

- §1 スコープ内 → CSV読込/D&D=Task16, 軌跡+pan/zoom=Task8,9,13,16, 再生=Task10,14,16,
  クロップ=Task15,16, 複数重ね=Task16, タグ=Task7,13,15,16, 整列モード=Task11,16,
  外れ値除去=Task6, 精度フィルタ=Task16。網羅。
- §2 技術（zero-build/依存なし/Canvas 2D）→ Task1,12。
- §3 データモデル（Point/Track/Event/時刻パーサ）→ Task2,5,6,7、Track組立=Task16。
- §4 投影/ビューポート/レンダラ → Task8,9,13。
- §5 時間軸/再生/クロップ → Task10,11,14,15。
- §6 UI → Task12,16。
- §8 テスト戦略 → 純粋モジュールに単体テスト（Task2–11）、手動=Task16。
- §9 受け入れ基準 → Task16 Step2 に対応チェックリスト。
- 型整合: Transform に `proj` 同梱（Task8で明記, viewport/renderer で使用）、
  `positionAt`/`trackLookupTime`/`globalRange`/`rejectOutliers` の呼び出し名・引数一致を確認。
- Placeholder: なし（各コードブロックは実装済み内容）。

## 備考 / 既知の割り切り
- タグの「基準トラック位置に補間してピン」は spec §3.2 の任意項目。今回の実装は
  `lat/lon` を持つタグのみマップ上ピン表示（時刻補間ピンは YAGNI で見送り、必要なら追加タスク）。
  タイムライン上の▲/▬表示は lat/lon 有無に関わらず行う。
- 精度フィルタは「次回読込から反映」（既存トラックには遡及しない）割り切り。
- 大量点デシメーションは未実装（実データ規模では Canvas 2D で十分軽い想定）。
