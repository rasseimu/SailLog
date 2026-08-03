# 芝工セイルログ — Sub-project A: Foundations + MVP Pipeline

**Date:** 2026-08-03
**Status:** Approved — ready for implementation planning
**Parent:** `2026-08-03-sailog-architecture-design.md`

## 1. Goal

Deliver the §9 hackathon MVP end to end on the local Mac:

> upload a cleaned practice video → transcript + speaker diarization →
> "who said what to whom" list → Claude practice summary + simple
> repeated-advice detection → browse it in a local web app.

Situation tags are **manual only** in this sub-project (auto tagging is B).
Vision and metadata stages are **out of scope** here (C, D).

## 2. In scope

| Component | Module | What it does |
|---|---|---|
| Config | `sailog/config.py` | Load `.env` (HF_TOKEN, ANTHROPIC_API_KEY, Drive IDs), resolve paths, model settings |
| DB | `sailog/db/{schema.sql,store.py,models.py}` | SQLite schema + the only SQL access layer + row dataclasses |
| Ingest | `sailog/ingest/{drive.py,audio.py}` | rclone pull/push (refactor `denoise_pipeline.py`); ffmpeg extract/mux (refactor `denoise_local.py`) |
| ① Denoise | `sailog/stages/s1_denoise.py` | Wrap existing DeepFilterNet3 flow incl. hang-on-exit workaround |
| ② Transcribe | `sailog/stages/s2_transcribe.py` | faster-whisper large-v3 |
| ③ Diarize | `sailog/stages/s3_diarize.py` | pyannote speaker-diarization-3.1 |
| Merge | `sailog/stages/merge.py` | Align word timestamps × speaker turns → utterances |
| ⑤ Summarize | `sailog/stages/s5_summarize.py` | Claude → structured JSON summary per player |
| Repeated advice | `sailog/repeated/{embed.py,match.py}` | Multilingual embeddings + cosine similarity → repeated-advice links |
| Runner | `sailog/pipeline/{runner.py,jobs.py}` | Sequential resumable orchestration, per-stage job state |
| Web | `sailog/web/{app.py,routes/,templates/,static/}` | Upload, session view, per-player timeline, summary + repeated-advice display, manual tag entry |

## 3. Out of scope (later sub-projects)

- ④ automatic situation tagging (B)
- Vision: form-image extraction, sail-No OCR, stabilization (C)
- GPS/weather metadata, growth dashboards, knowledge DB, team sharing (D)
- Multi-user auth, cloud deploy

## 4. Stage specs (settings from proposal §5)

**② faster-whisper large-v3:** `language="ja"`, `beam_size=5`, VAD filter on,
`condition_on_previous_text=False`, `word_timestamps=True`,
`compute_type=int8` on CPU. Input = ① clean audio. Output → `utterances` text +
word timestamps held for merge.

**③ pyannote 3.1:** `min_speakers=2`, `max_speakers=4`. Dominant chase-boat
speaker labeled "coach", others "player"; first mapping is a manual step in the
UI, later inherited by voiceprint (voiceprint inheritance itself is post-MVP —
MVP just stores the manual mapping per session). Input = ① clean audio.

**merge:** overlap-max match of each word to the speaker turn covering it →
group into utterances. Coach→player targeting inferred heuristically (nearest
player turn / configurable default); stored in `utterances.target_speaker_id`.

**⑤ Claude:** whole session's utterances in one long-context call. Low
temperature. Output = structured JSON (speaker / target / advice category /
situation tag / summary) validated against a schema, stored in `summaries` and
`advice`. Model id per current Anthropic docs (consult claude-api skill at
implementation time).

**repeated advice:** embed each advice text with a local multilingual
sentence-transformer; cosine similarity across the player's prior advice; pairs
above a threshold get a `repeated_links` row. (Claude same-intent adjudication
is a post-MVP refinement; MVP uses the similarity threshold.)

## 5. Runner contract

`runner.run(session_id)` executes stages in order: `s1 → s2 → s3 → merge → s5 →
repeated`. Each stage checks `jobs` for its own completion and skips if done;
on success it marks the job complete, on failure it records the error and stops
the session (remaining stages not run). Re-invoking resumes from the first
incomplete stage. Every stage function signature: `run(session_id, store,
config) -> None`.

## 6. Web app routes

- `GET /` — session list + upload form
- `POST /upload` — accept a video (or pick a `cleaned/*.MOV`), create session,
  kick off `runner.run` in a background task, redirect to session view
- `GET /sessions/{id}` — status, video player, utterance timeline
  (who→whom, click timestamp to seek), per-player summary, repeated-advice
  callouts, manual situation-tag entry form
- `GET /players/{name}` — that player's utterances/advice across sessions
- `POST /sessions/{id}/tags` — add a manual situation tag

## 7. Build plan (subagents within Sub-project A)

1. **Foundation, sequential:** `config.py`, `db/schema.sql`, `db/store.py`,
   `db/models.py`, plus a fixture (a short cleaned clip + tiny expected-rows
   fixture). Nothing else starts until this is committed.
2. **Parallel fan-out, one subagent each** (all code against the DB contract +
   fixtures, all with unit tests, heavy models mocked):
   - `ingest/audio.py` + `ingest/drive.py`
   - `stages/s1_denoise.py`
   - `stages/s2_transcribe.py`
   - `stages/s3_diarize.py`
   - `repeated/embed.py` + `repeated/match.py`
3. **Join, sequential:** `stages/merge.py`, then `stages/s5_summarize.py`
   (depend on s2/s3 output shapes).
4. **Integrate:** `pipeline/jobs.py`, `pipeline/runner.py`.
5. **Web:** `web/app.py` + routes + templates + static.
6. **End-to-end:** run on one real `cleaned/*.MOV`; verify in the UI.

## 8. Testing

- Each module ships pytest unit tests against fixtures; model-heavy stages mock
  the model and assert on the DB writes / merge logic.
- One opt-in integration test (`-m integration`) runs the real models on the
  fixture clip.
- Manual E2E: `runner.run` on a real clip, review transcript / speakers /
  summary / repeated advice in the browser.
- `superpowers:test-driven-development` for each module;
  `superpowers:verification-before-completion` before claiming done.

## 9. Definition of done (MVP)

- `pip install -r requirements.txt` in `.venv`, `.env` filled, `uvicorn`
  serves the app.
- Selecting a real cleaned clip runs the full pipeline and produces, in the UI:
  a timestamped who→whom utterance list, a per-player Claude summary, and at
  least surfaced repeated-advice links when a player was told similar things
  twice.
- All unit tests green; integration test runs on the fixture clip.
