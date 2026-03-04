"""
Transcribe a video file using Gemini API with speaker diarization.

Splits video into 10-minute chunks to avoid Gemini's 65K output token limit,
transcribes each chunk sequentially, and concatenates results.

Usage:
    python transcribe.py <path_to_video>
    python transcribe.py <path_to_video> --model gemini-2.5-flash --chunk-minutes 15

Output:
    Saves transcript as a .txt file next to the video.
"""

import argparse
import asyncio
import os
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

PROMPT_FILE = os.getenv(
    "TRANSCRIPTION_PROMPT_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../prompts/transcription_prompt.txt"),
)
with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    TRANSCRIPTION_PROMPT = f.read()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))
from utils import retry_with_backoff


def _fmt_time(seconds: float) -> str:
    """Format seconds as MM:SS or H:MM:SS."""
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
    """Get video duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def split_video(video_path: str, chunk_minutes: int = CHUNK_MINUTES) -> list[dict]:
    """
    Split video into chunks of N minutes with overlap.
    Returns list of {path, start_seconds, end_seconds, index}.
    """
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


async def transcribe_chunk(
    client: genai.Client,
    chunk: dict,
    prompt: str,
    model: str,
    prev_tail: str = "",
    total_chunks: int = 1,
) -> tuple[str, str]:
    """
    Transcribe one video chunk.
    Returns (transcript_text, last_10_lines_for_next_chunk_context).
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

    # Wait for processing
    while video_file.state == "PROCESSING":
        await asyncio.sleep(3)
        video_file = await loop.run_in_executor(
            None, lambda: client.files.get(name=video_file.name)
        )

    if video_file.state != "ACTIVE":
        raise Exception(f"File processing failed for chunk {idx}: {video_file.state}")

    # Build chunk context to inject into prompt
    chunk_context = f"""
- This is chunk {idx + 1} of {total_chunks}
- Time range in original video: {_fmt_time(start)} — {_fmt_time(end)}
- ALL timestamps in transcript must be ABSOLUTE (from the start of the original video). Add {_fmt_time(start)} offset to what you see in this chunk.
"""

    if prev_tail:
        chunk_context += f"""
- End of previous chunk (for context, DO NOT repeat):
```
{prev_tail}
```
"""

    if idx == 0:
        chunk_context += "\n- This is the BEGINNING of the recording."

    if idx == total_chunks - 1:
        chunk_context += "\n- This is the END of the recording. Transcribe until the very end, including goodbyes."

    full_prompt = prompt + "\n\n## Chunk info\n" + chunk_context

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
    print(f"  [{idx + 1}/{total_chunks}] Done in {elapsed:.1f}s")

    # Check truncation
    if response.candidates and response.candidates[0].finish_reason:
        finish_reason = response.candidates[0].finish_reason
        if str(finish_reason) not in ("STOP", "FinishReason.STOP"):
            print(f"  [{idx + 1}/{total_chunks}] Warning: truncated (finish_reason={finish_reason})")

    # Cleanup uploaded file
    try:
        await loop.run_in_executor(
            None, lambda: client.files.delete(name=video_file.name)
        )
    except Exception:
        pass

    transcript = response.text

    # Tail for next chunk context
    lines = transcript.strip().split("\n")
    tail = "\n".join(lines[-10:]) if len(lines) > 10 else transcript

    return transcript, tail


async def transcribe_video(video_path: str, model: str = DEFAULT_MODEL, chunk_minutes: int = CHUNK_MINUTES) -> str:
    """Main transcription pipeline: split → transcribe chunks → concatenate."""
    if not os.path.exists(video_path):
        print(f"Error: File not found: {video_path}")
        sys.exit(1)

    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"Transcribing {video_path} ({file_size_mb:.0f} MB) with {model}")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Split video into chunks
    chunks = split_video(video_path, chunk_minutes)

    try:
        # Transcribe each chunk sequentially
        all_transcripts = []
        prev_tail = ""

        for chunk in chunks:
            transcript, prev_tail = await transcribe_chunk(
                client=client,
                chunk=chunk,
                prompt=TRANSCRIPTION_PROMPT,
                model=model,
                prev_tail=prev_tail,
                total_chunks=len(chunks),
            )
            all_transcripts.append(transcript)

        # Concatenate
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
        # Cleanup chunk files
        chunks_dir = Path(video_path).parent / "chunks"
        if chunks_dir.exists():
            shutil.rmtree(chunks_dir)
            print("  Chunks cleaned up")


def main():
    parser = argparse.ArgumentParser(description="Transcribe video via Gemini with chunking")
    parser.add_argument("video_path", help="Path to video file")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"Gemini model (default: {DEFAULT_MODEL})")
    parser.add_argument("--chunk-minutes", "-c", type=int, default=CHUNK_MINUTES,
                        help=f"Chunk size in minutes (default: {CHUNK_MINUTES})")

    args = parser.parse_args()
    transcript = asyncio.run(transcribe_video(args.video_path, args.model, args.chunk_minutes))

    # Save next to video as .txt
    output_path = os.path.splitext(args.video_path)[0] + "_transcript.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(transcript)

    print(f"\nTranscript saved to: {output_path}")
    print(f"Size: {len(transcript):,} chars")
    print(f"\n--- Preview (first 500 chars) ---\n")
    print(transcript[:500])


if __name__ == "__main__":
    main()
