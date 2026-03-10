"""
Transcribe a video file using Gemini API, using Zoom VTT transcript
as speaker identification hints for each chunk.

The Zoom VTT has correct speaker attribution (from audio channels)
but garbled text. Gemini has good speech recognition but often
misidentifies speakers. This combines both strengths.

Usage:
    python transcribe_with_vtt.py <video_path> <vtt_path>
    python transcribe_with_vtt.py <video_path> <vtt_path> --model gemini-3-pro-preview
    python transcribe_with_vtt.py <video_path> <vtt_path> --chunk-minutes 15

Output:
    Saves transcript as *_transcript_vtt2.txt next to the video.
"""

import argparse
import asyncio
from datetime import datetime
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in .env")
    sys.exit(1)

DEFAULT_MODEL = "gemini-3-pro-preview"
CHUNK_MINUTES = 10
OVERLAP_SECONDS = 15
MAX_CHUNKS = 3  # Limit number of chunks to process (None = all)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(SCRIPT_DIR, "sandbox", "prompt.txt")
if not os.path.exists(PROMPT_FILE):
    PROMPT_FILE = os.path.join(SCRIPT_DIR, "../../prompts/transcription_prompt.txt")
with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    PROMPT_TEMPLATE = f.read()
print(f"Using prompt: {PROMPT_FILE}")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))
from utils import retry_with_backoff


# --- VTT parsing ---

def parse_vtt(vtt_text: str) -> list[dict]:
    """Parse VTT content into list of {start_seconds, end_seconds, speaker, text}."""
    entries = []
    blocks = vtt_text.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        ts_line = None
        text_lines = []
        for line in lines:
            if " --> " in line:
                ts_line = line
            elif ts_line is not None:
                text_lines.append(line)
        if not ts_line or not text_lines:
            continue
        parts = ts_line.split(" --> ")
        start = _parse_vtt_ts(parts[0].strip())
        end = _parse_vtt_ts(parts[1].strip())
        if start is None or end is None:
            continue
        text = " ".join(text_lines)
        speaker = ""
        if ": " in text:
            maybe_speaker, rest = text.split(": ", 1)
            if len(maybe_speaker) < 40 and not any(c.isdigit() for c in maybe_speaker):
                speaker = maybe_speaker
                text = rest
        entries.append({
            "start_seconds": start,
            "end_seconds": end,
            "speaker": speaker,
            "text": text,
        })
    return entries


def _parse_vtt_ts(ts: str) -> float | None:
    """Parse VTT timestamp 'HH:MM:SS.mmm' to seconds."""
    try:
        parts = ts.replace(",", ".").split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
    except (ValueError, IndexError):
        return None
    return None


def extract_vtt_segment(entries: list[dict], start_sec: float, end_sec: float) -> str:
    """Extract VTT entries for a time range, with timestamps relative to chunk start.

    Includes full text so Gemini can cross-reference phrases with what it hears.
    """
    relevant = [
        e for e in entries
        if e["end_seconds"] >= start_sec and e["start_seconds"] <= end_sec
    ]
    if not relevant:
        return ""
    lines = []
    for e in relevant:
        local_ts = e["start_seconds"] - start_sec
        ts = _fmt_time(max(0, local_ts))
        speaker = e["speaker"] or "(unknown)"
        lines.append(f"[{ts}] {speaker}: {e['text']}")
    return "\n".join(lines)


# --- Video utils ---

def _fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h}:{m:02d}:{s:02d}"
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"


def get_video_duration(video_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def split_video(video_path: str, chunk_minutes: int = CHUNK_MINUTES) -> list[dict]:
    duration = get_video_duration(video_path)
    chunk_seconds = chunk_minutes * 60
    chunks = []
    output_dir = Path(video_path).parent / "chunks"
    output_dir.mkdir(exist_ok=True)

    start = 0
    index = 0
    while start < duration:
        end = min(start + chunk_seconds + OVERLAP_SECONDS, duration)
        chunk_path = str(output_dir / f"chunk_{index:03d}.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(end - start),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            chunk_path,
        ]
        print(f"  Splitting chunk {index}: {_fmt_time(start)} — {_fmt_time(end)}")
        subprocess.run(cmd, capture_output=True, check=True)
        chunks.append({
            "path": chunk_path,
            "start_seconds": start,
            "end_seconds": min(start + chunk_seconds, duration),
            "index": index,
        })
        start += chunk_seconds
        index += 1

    print(f"  Split into {len(chunks)} chunks from {_fmt_time(duration)} total")
    return chunks


# --- Timestamp offset ---

def _add_offset_to_transcript(transcript: str, offset_seconds: int) -> str:
    """Add time offset to all [MM:SS] or [H:MM:SS] timestamps in transcript."""
    def replace_ts(match):
        ts_str = match.group(1)
        parts = ts_str.split(":")
        if len(parts) == 3:
            secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            secs = int(parts[0]) * 60 + int(parts[1])
        secs += offset_seconds
        return f"[{_fmt_time(secs)}]"

    return re.sub(r'\[(\d+:\d+(?::\d+)?)\]', replace_ts, transcript)


# --- Transcription ---


async def transcribe_chunk(
    client: genai.Client,
    chunk: dict,
    prompt_template: str,
    model: str,
    vtt_entries: list[dict] | None = None,
    prev_tail: str = "",
    total_chunks: int = 1,
) -> tuple[str, str]:
    """Transcribe one video chunk with optional VTT speaker hints.

    Gemini writes timestamps relative to chunk start (00:00).
    Caller is responsible for adding the absolute offset afterwards.
    """
    loop = asyncio.get_event_loop()
    chunk_path = chunk["path"]
    start = chunk["start_seconds"]
    end = chunk["end_seconds"]
    idx = chunk["index"]

    # Upload to Gemini
    print(f"  [{idx + 1}/{total_chunks}] Uploading chunk {_fmt_time(start)}—{_fmt_time(end)}...")
    video_file = await loop.run_in_executor(
        None, lambda: client.files.upload(file=chunk_path)
    )

    while video_file.state == "PROCESSING":
        await asyncio.sleep(3)
        video_file = await loop.run_in_executor(
            None, lambda: client.files.get(name=video_file.name)
        )

    if video_file.state != "ACTIVE":
        raise Exception(f"File processing failed for chunk {idx}: {video_file.state}")

    # Build chunk info
    chunk_info = f"- This is chunk {idx + 1} of {total_chunks}."

    if prev_tail:
        chunk_info += f"""
- End of previous chunk (for context, DO NOT repeat):
```
{prev_tail}
```
"""

    if idx == 0:
        chunk_info += "\n- This is the first chunk."
    if idx == total_chunks - 1:
        chunk_info += "\n- This is the last chunk. Transcribe until the very end, including goodbyes."

    # Build VTT segment
    vtt_segment = ""
    if vtt_entries:
        vtt_segment = extract_vtt_segment(vtt_entries, start, end)
        if vtt_segment:
            vtt_count = vtt_segment.count("\n") + 1
            print(f"  [{idx + 1}/{total_chunks}] Adding {vtt_count} VTT speaker hints")

    # Fill template
    full_prompt = prompt_template.format(
        chunk_info=chunk_info,
        vtt_segment=vtt_segment or "(no VTT data for this chunk)",
    )

    # Transcribe
    print(f"  [{idx + 1}/{total_chunks}] Transcribing via {model}...")
    t0 = time.time()

    def _generate():
        return client.models.generate_content(
            model=model,
            contents=[video_file, full_prompt],
            config=types.GenerateContentConfig(
                max_output_tokens=65536,
                temperature=0.2,
            ),
        )

    def _is_retryable(e: Exception):
        error_str = str(e).lower()
        if "400" in error_str and "bad request" in error_str:
            return False
        return True

    response = await loop.run_in_executor(
        None, lambda: retry_with_backoff(_generate, max_retries=3, delays=(15, 45, 90), retryable_check=_is_retryable)
    )

    elapsed = time.time() - t0

    # Token usage
    usage_str = ""
    if response.usage_metadata:
        inp = response.usage_metadata.prompt_token_count or 0
        out = response.usage_metadata.candidates_token_count or 0
        cost = (inp / 1e6) * 1.25 + (out / 1e6) * 10.0
        usage_str = f" | {inp:,}+{out:,} tokens, ${cost:.2f}"

    print(f"  [{idx + 1}/{total_chunks}] Done in {elapsed:.1f}s{usage_str}")

    if response.candidates and response.candidates[0].finish_reason:
        finish_reason = response.candidates[0].finish_reason
        if str(finish_reason) not in ("STOP", "FinishReason.STOP"):
            print(f"  [{idx + 1}/{total_chunks}] Warning: truncated (finish_reason={finish_reason})")

    try:
        await loop.run_in_executor(
            None, lambda: client.files.delete(name=video_file.name)
        )
    except Exception:
        pass

    transcript = response.text

    # Add absolute offset to timestamps
    offset = int(start)
    if offset > 0:
        transcript = _add_offset_to_transcript(transcript, offset)

    lines = transcript.strip().split("\n")
    tail = "\n".join(lines[-10:]) if len(lines) > 10 else transcript

    return transcript, tail


async def transcribe_video(
    video_path: str,
    vtt_path: str | None = None,
    model: str = DEFAULT_MODEL,
    chunk_minutes: int = CHUNK_MINUTES,
) -> str:
    """Main pipeline: split video → transcribe chunks with VTT hints → concatenate."""
    if not os.path.exists(video_path):
        print(f"Error: File not found: {video_path}")
        sys.exit(1)

    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"Transcribing {video_path} ({file_size_mb:.0f} MB) with {model}")

    # Parse VTT if provided
    vtt_entries = None
    if vtt_path:
        with open(vtt_path, "r", encoding="utf-8") as f:
            vtt_text = f.read()
        vtt_entries = parse_vtt(vtt_text)
        print(f"Loaded {len(vtt_entries)} VTT entries for speaker hints")

    client = genai.Client(api_key=GEMINI_API_KEY)
    chunks = split_video(video_path, chunk_minutes)
    if MAX_CHUNKS:
        chunks = chunks[:MAX_CHUNKS]
        print(f"  Limited to first {MAX_CHUNKS} chunks")

    try:
        all_transcripts = []
        prev_tail = ""

        for chunk in chunks:
            transcript, prev_tail = await transcribe_chunk(
                client=client,
                chunk=chunk,
                prompt_template=PROMPT_TEMPLATE,
                model=model,
                vtt_entries=vtt_entries,
                prev_tail=prev_tail,
                total_chunks=len(chunks),
            )
            all_transcripts.append(transcript)

        if len(all_transcripts) == 1:
            return all_transcripts[0]

        parts = []
        for i, transcript in enumerate(all_transcripts):
            chunk = chunks[i]
            parts.append(
                f"\n{'=' * 60}\n"
                f"## Chunk {i + 1}: {_fmt_time(chunk['start_seconds'])} — {_fmt_time(chunk['end_seconds'])}\n"
                f"{'=' * 60}\n\n"
                f"{transcript}"
            )
        return "\n".join(parts)

    finally:
        chunks_dir = Path(video_path).parent / "chunks"
        if chunks_dir.exists():
            shutil.rmtree(chunks_dir)
            print("  Chunks cleaned up")


DEFAULT_VIDEO = os.path.join(SCRIPT_DIR, "sandbox", "video.mp4")
DEFAULT_VTT = os.path.join(SCRIPT_DIR, "sandbox", "zoom.vtt")


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe video via Gemini with VTT speaker hints"
    )
    parser.add_argument("video_path", nargs="?", default=DEFAULT_VIDEO,
                        help=f"Path to video file (default: sandbox/video.mp4)")
    parser.add_argument("vtt_path", nargs="?", default=DEFAULT_VTT,
                        help=f"Path to Zoom VTT transcript (default: sandbox/zoom.vtt)")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"Gemini model (default: {DEFAULT_MODEL})")
    parser.add_argument("--chunk-minutes", "-c", type=int, default=CHUNK_MINUTES,
                        help=f"Chunk size in minutes (default: {CHUNK_MINUTES})")

    args = parser.parse_args()
    transcript = asyncio.run(
        transcribe_video(args.video_path, args.vtt_path, args.model, args.chunk_minutes)
    )

    # Save with timestamp in sandbox
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sandbox_dir = os.path.join(SCRIPT_DIR, "sandbox")
    output_path = os.path.join(sandbox_dir, f"transcript_{ts}.md")

    # Append prompt used
    prompt_text = PROMPT_TEMPLATE
    output = transcript + f"\n\n---\n\n<details>\n<summary>Prompt used</summary>\n\n```\n{prompt_text}\n```\n\n</details>\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"\nTranscript saved to: {output_path}")
    print(f"Size: {len(transcript):,} chars")


if __name__ == "__main__":
    main()
