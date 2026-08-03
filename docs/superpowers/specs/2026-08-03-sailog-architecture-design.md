# 芝工セイルログ (Shibaura Sail Log) — Architecture Design

**Date:** 2026-08-03
**Status:** Approved (overarching architecture)
**Source proposal:** `芝工セイルログ_提案書.md`

## 1. Purpose

Turn noisy sailing-practice videos into a searchable, comparable, shareable
coaching log. The audio-cleaning stage (① DeepFilterNet3) already runs on real
data (23 clips). This design covers building out the rest of the pipeline and a
local web app so players and coaches can browse "who said what to whom", search
by situation, and see repeated advice across sessions.

## 2. Constraints & decisions (locked)

- **Scope:** Full — audio NLP pipeline + situation tags + video/CV + metadata +
  web app. Built incrementally via sub-projects (§7).
- **Interface:** Local web app — FastAPI + SQLite + server-rendered Jinja2
  pages + light vanilla JS. HTML5 `<video>` deep-linked to utterance
  timestamps. No React build step.
- **Runtime:** Local-first on the dev Mac (macOS, CPU). SQLite + local files.
  `rclone` syncs raw MOV from Google Drive. Anthropic API for ⑤.
- **Orchestration:** Sequential, resumable runner that writes to the DB and
  skips work already recorded (same philosophy as the existing denoise script).
  No task queue, no DAG tool — deferred with scale.
- **Build method:** Independent, swappable stage modules behind small
  interfaces, constructed by parallel Claude Code subagents against a shared DB
  contract (§6).

## 3. Prerequisites

- HuggingFace token (pyannote 3.1 gated model) → `.env` `HF_TOKEN`
- Anthropic API key → `.env` `ANTHROPIC_API_KEY`
- Existing `.venv`, `ffmpeg`/`ffprobe`/`rclone` on PATH (all present)
- Running whisper large-v3 + pyannote on CPU is acceptable (slow, fine for a
  handful of clips)

## 4. Module structure

```
sailing/
  sailog/
    config.py              # env + paths + model settings (.env-driven)
    db/  schema.sql, store.py, models.py      # SQLite: shared contract
    ingest/  drive.py (rclone), audio.py (ffmpeg extract/mux)
    stages/
      s1_denoise.py        # wraps existing DeepFilterNet3 (+ hang-on-exit workaround)
      s2_transcribe.py     # faster-whisper large-v3
      s3_diarize.py        # pyannote 3.1
      merge.py             # align words × speaker turns → utterances
      s4_situation.py      # situation tags (manual + simple-auto)
      s5_summarize.py      # Claude → structured JSON
    vision/  detect.py, ocr.py, stabilize.py
    metadata/ gps_weather.py
    repeated/ embed.py, match.py
    pipeline/ runner.py, jobs.py
    web/  app.py, routes/, templates/, static/
  data/  sessions/<id>/... , sailog.db      # gitignored
  requirements.txt, README.md
```

Each stage exposes a single entry function `run(session_id, store, config) ->
None` that reads its inputs from the DB/filesystem and writes its outputs to the
DB. Stages are idempotent: re-running a completed stage is a no-op.

## 5. Data model (SQLite — the contract)

- `sessions` (id, video_path, clean_path, date, boat, crew, status, created_at)
- `speakers` (id, session_id, label, role, voiceprint_ref)
- `utterances` (id, session_id, start_s, end_s, speaker_id, target_speaker_id, text)
- `situation_tags` (id, session_id, start_s, end_s, kind, value, source)  — source ∈ {manual, auto}
- `form_images` (id, session_id, ts_s, path, sail_no)
- `summaries` (id, session_id, player, json)
- `advice` (id, session_id, player, category, text, embedding)
- `repeated_links` (advice_id_a, advice_id_b, similarity)
- `jobs` (id, session_id, stage, status, error, updated_at)  — runner state

Schema lives in `db/schema.sql`; `store.py` is the only module that issues SQL.

## 6. Data flow

```
cleaned/*.MOV  →  ① (done)
                    │
                    ├─▶ ② transcribe (word ts) ─┐
                    │                            ├─▶ merge → utterances
                    ├─▶ ③ diarize (turns) ──────┘        │
                    │                                      ▼
                    ├─▶ ④ situation tags ◀── metadata/gps_weather, vision (later)
                    │                                      │
                    └─▶ vision: detect→form_images, ocr→sail_no, stabilize
                                                           ▼
                                        ⑤ Claude summary + repeated-advice detect
                                                           ▼
                                                    SQLite → web app
```

## 7. Sub-projects (each: own spec → plan → build)

- **A — Foundations + MVP pipeline** *(build first)*: config, DB/store, ingest,
  s1 wrap, s2, s3, merge, s5, repeated-advice, runner, minimal viewer. Delivers
  the §9 hackathon MVP: upload → transcript + diarization → who-said-what list →
  Claude summary + simple repeated-advice. Situation tags start manual.
- **B — Situation tags ④ + search UI**: auto/simple situation tagging + search
  by tag/tuning across sessions.
- **C — Vision stack**: stern-boat detection → form image, sail-number OCR,
  electronic stabilization; form images surfaced in UI.
- **D — Metadata + dashboards**: GPS/time × weather auto-tagging; per-player
  growth dashboard, knowledge DB, team sharing.

## 8. Build strategy (subagents)

1. **Foundation (sequential, first):** config + `db/schema.sql` + store +
   fixtures. Shared contract; must land before fan-out.
2. **Parallel fan-out (one subagent per module):** s2, s3, vision/*,
   metadata/gps_weather, repeated/* — each against the DB contract + a fixture
   clip, each with its own tests.
3. **Join:** merge, s4, s5.
4. **Runner + Web.**

Driven with `superpowers:subagent-driven-development` /
`superpowers:dispatching-parallel-agents` at execution time. Within Sub-project
A the same fan-out applies at smaller scale (see the MVP spec).

## 9. Testing & verification

- Per-module unit tests against fixtures (a short cleaned clip + expected DB
  rows). Heavy model calls mocked in unit tests; one opt-in integration test
  runs the real models on the fixture clip.
- End-to-end: run the MVP pipeline on one real `cleaned/*.MOV`, eyeball the
  transcript/diarization/summary in the web UI.
- Effectiveness (per proposal §9): transcription accuracy vs a hand transcript;
  repeated-advice precision judged by a coach. Deferred to post-MVP measurement.
