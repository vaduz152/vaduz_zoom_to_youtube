# VTT Speaker Hints — sandbox for transcript experiments

Zoom VTT has correct speaker names (from audio channels) but garbled text.
Gemini has good speech recognition but often misidentifies speakers.
This prototype combines both: VTT fragments are passed alongside video chunks
so Gemini can use them for speaker attribution.

## Setup

1. Create `sandbox/` directory (already in `.gitignore`):
   - `sandbox/video.mp4` — video to transcribe
   - `sandbox/zoom.vtt` — Zoom Cloud VTT transcript
   - `sandbox/prompt.txt` — editable prompt template
   - `sandbox/baseline.md` — reference transcript for comparison

2. Edit `sandbox/prompt.txt` to experiment with the prompt.
   Template variables: `{chunk_info}`, `{vtt_segment}`.

## Usage

```bash
cd /root/vaduz_zoom_to_youtube
venv/bin/python3 prototype/vtt_speaker_hints/transcribe_with_vtt.py
```

No arguments needed — defaults to `sandbox/video.mp4` and `sandbox/zoom.vtt`.

## Settings (constants in the script)

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_CHUNKS` | `2` | How many chunks to process (`None` = all) |
| `CHUNK_MINUTES` | `10` | Chunk duration in minutes |
| `OVERLAP_SECONDS` | `15` | Overlap between chunks for continuity |
| `DEFAULT_MODEL` | `gemini-3-pro-preview` | Gemini model to use |

## Output

Transcripts are saved to `sandbox/transcript_YYYYMMDD_HHMMSS.md`
with the prompt appended at the end in a `<details>` block.

## Workflow

1. Edit `sandbox/prompt.txt`
2. Run the script
3. Compare new `sandbox/transcript_*.md` with `sandbox/baseline.md`
4. Repeat
