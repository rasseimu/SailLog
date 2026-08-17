# MOV denoise pipeline (Google Drive → Google Drive)

`denoise_pipeline.py` pulls every `.MOV` from a source Drive folder, denoises the
audio with DeepFilterNet3, muxes the cleaned audio back onto the untouched video,
and uploads `<name>_cleaned.MOV` to a destination Drive folder. Files already
present in the destination are skipped.

## One-time setup

1. **Install rclone**

   ```sh
   brew install rclone
   ```

2. **Create a Drive remote named `gdrive`**

   ```sh
   rclone config
   ```

   - `n` (new remote) → name it **`gdrive`**
   - Storage type: **`drive`** (Google Drive)
   - `client_id` / `client_secret`: leave blank (press Enter)
   - Scope: choose **`1` (full access)** — needed to upload
   - Leave `root_folder_id` / service account blank
   - Auto-config: **`y`** → a browser opens; log in and allow access
   - Confirm as a normal (not shared-drive) config unless your folders live on a Shared Drive

   Verify:

   ```sh
   rclone lsf gdrive: --drive-root-folder-id 1E4D6uMGz6PjKD7WeUQEJBbf8u0fooVTs
   ```

## Run

```sh
.venv/bin/python denoise_pipeline.py
```

Reads/writes the folder IDs configured at the top of the script. Re-run any time;
it only processes MOVs that aren't already in the destination.

## Config knobs (top of `denoise_pipeline.py`)

| Name             | Meaning                                              |
| ---------------- | ---------------------------------------------------- |
| `RCLONE_REMOTE`  | rclone remote name (`gdrive`)                        |
| `SRC_FOLDER_ID`  | source Drive folder ID                               |
| `DST_FOLDER_ID`  | destination Drive folder ID                          |
| `AUDIO_BITRATE`  | AAC bitrate for the muxed audio (`192k`)             |
| `OUTPUT_SUFFIX`  | suffix added to processed files (`_cleaned`)         |

Each file is processed in a temp dir that is deleted afterward, so the pipeline
doesn't accumulate large local files. One file failing logs the error and moves
on; the script exits non-zero if any file failed.
