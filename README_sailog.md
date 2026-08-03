# Sailog: Sailing Session Analysis

Sailog is an end-to-end pipeline and web interface for analyzing sailing training sessions. It ingests denoised video, transcribes speech, diarizes speakers, merges utterances, generates summaries via Claude, identifies repeated advice, and serves an interactive web UI for browsing sessions and advice by player.

## Installation

1. **Create a virtual environment and install dependencies:**

   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   ```

## Configuration

1. **Copy the example `.env` file:**

   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and add your credentials:**

   ```
   HF_TOKEN=<your-huggingface-token>
   ANTHROPIC_API_KEY=<your-anthropic-api-key>
   ```

3. **Accept the pyannote speaker diarization model terms:**

   - Go to https://huggingface.co/pyannote/speaker-diarization-3.1
   - Log in with your HuggingFace account
   - Accept the model's terms of use
   - Your `HF_TOKEN` will now have access to the model

## Running the Web App

Start the web server:

```bash
.venv/bin/uvicorn sailog.web.app:app --factory --reload
```

Then open http://localhost:8000 in your browser.

## Pipeline Flow

The pipeline processes denoised sailing videos through the following stages:

1. **① Denoise (s1):** Audio denoising via DeepFilterNet3. Cleaned clips in `cleaned/` are already denoised.
2. **② Transcribe (s2):** Speech-to-text transcription using Whisper (model: `large-v3`).
3. **③ Diarize (s3):** Speaker identification and segmentation using pyannote speaker diarization.
4. **④ Merge:** Combine transcribed utterances with speaker labels.
5. **⑤ Summarize (s5):** Generate session summary and situational insights via Claude.
6. **⑥ Repeated Advice:** Identify and link repeated coaching advice across sessions.

Once complete, sessions appear in the web UI where you can browse utterances, speakers, summaries, and advice by player.

## Input

Place denoised `.MOV` files in the `cleaned/` directory. The web UI displays available clips and allows selecting one to process. The pipeline creates a session and runs all stages in sequence.

## Output

- **Database:** `data/sailog.db` (SQLite)
- **Session data:** `data/sessions/` (speaker info, utterances, summaries, advice links)
- **Web UI:** http://localhost:8000
  - Browse all sessions and their details
  - View speaker utterances and roles
  - Read session summaries and advice per player
