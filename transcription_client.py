"""Gemini-based video transcription and title generation."""
import asyncio
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from google import genai
from google.genai import types

import config
from utils import retry_with_backoff

logger = logging.getLogger(__name__)

CHUNK_MINUTES = 10
OVERLAP_SECONDS = 15


@dataclass
class UsageStats:
    """Accumulated Gemini API token usage."""
    input_tokens: int = 0
    output_tokens: int = 0

    def add_response(self, response) -> None:
        """Add token counts from a Gemini response."""
        if response.usage_metadata:
            self.input_tokens += response.usage_metadata.prompt_token_count or 0
            self.output_tokens += response.usage_metadata.candidates_token_count or 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost_string(self) -> str:
        """Format cost as a human-readable string with token counts."""
        input_m = self.input_tokens / 1_000_000
        output_m = self.output_tokens / 1_000_000
        cost = input_m * config.GEMINI_INPUT_PRICE_PER_MTOK + output_m * config.GEMINI_OUTPUT_PRICE_PER_MTOK
        return f"${cost:.2f}"


def _load_prompt(path: Path) -> str:
    """Read prompt file content."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


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


def _get_video_duration(video_path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def _split_video(video_path: str, chunk_minutes: int = CHUNK_MINUTES) -> list[dict]:
    """Split video into chunks of N minutes with overlap."""
    duration = _get_video_duration(video_path)
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

        logger.info(f"  Splitting chunk {index}: {_fmt_time(start)} — {_fmt_time(end)}")
        subprocess.run(cmd, capture_output=True, check=True)

        chunks.append({
            "path": chunk_path,
            "start_seconds": start,
            "end_seconds": min(start + chunk_seconds, duration),
            "index": index,
        })

        start += chunk_seconds
        index += 1

    logger.info(f"  Split into {len(chunks)} chunks from {_fmt_time(duration)} total")
    return chunks


async def _transcribe_chunk(
    client: genai.Client,
    chunk: dict,
    prompt: str,
    model: str,
    prev_tail: str = "",
    total_chunks: int = 1,
    usage: UsageStats | None = None,
) -> tuple[str, str]:
    """Transcribe one video chunk. Returns (transcript_text, tail_for_next_chunk)."""
    loop = asyncio.get_event_loop()
    chunk_path = chunk["path"]
    start = chunk["start_seconds"]
    end = chunk["end_seconds"]
    idx = chunk["index"]

    # Upload to Gemini
    logger.info(f"  [{idx + 1}/{total_chunks}] Uploading chunk {_fmt_time(start)}—{_fmt_time(end)}...")
    video_file = await loop.run_in_executor(
        None, lambda: retry_with_backoff(
            lambda: client.files.upload(file=chunk_path),
            max_retries=3, delays=(15, 45, 90),
        )
    )

    # Wait for processing
    while video_file.state == "PROCESSING":
        await asyncio.sleep(3)
        video_file = await loop.run_in_executor(
            None, lambda: client.files.get(name=video_file.name)
        )

    if video_file.state != "ACTIVE":
        raise Exception(f"File processing failed for chunk {idx}: {video_file.state}")

    # Build chunk context
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
    logger.info(f"  [{idx + 1}/{total_chunks}] Transcribing via {model}...")
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
    logger.info(f"  [{idx + 1}/{total_chunks}] Done in {elapsed:.1f}s")

    # Track usage
    if usage is not None:
        usage.add_response(response)

    # Check truncation
    if response.candidates and response.candidates[0].finish_reason:
        finish_reason = response.candidates[0].finish_reason
        if str(finish_reason) not in ("STOP", "FinishReason.STOP"):
            logger.warning(f"  [{idx + 1}/{total_chunks}] Truncated (finish_reason={finish_reason})")

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


async def _transcribe_video_async(
    video_path: str, model: str, chunk_minutes: int, usage: UsageStats | None = None,
) -> str:
    """Internal async transcription pipeline: split → transcribe chunks → concatenate."""
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = _load_prompt(config.TRANSCRIPTION_PROMPT_PATH)

    chunks = _split_video(video_path, chunk_minutes)

    try:
        all_transcripts = []
        prev_tail = ""

        for chunk in chunks:
            transcript, prev_tail = await _transcribe_chunk(
                client=client,
                chunk=chunk,
                prompt=prompt,
                model=model,
                prev_tail=prev_tail,
                total_chunks=len(chunks),
                usage=usage,
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
            logger.debug("  Chunks cleaned up")


def transcribe_video(
    video_path: str, duration_seconds: int = 0,
) -> tuple[str | None, UsageStats]:
    """
    Transcribe a video file using Gemini.

    Returns (transcript_text, usage_stats). Transcript is None if skipped/failed.
    """
    usage = UsageStats()

    if not config.GEMINI_API_KEY:
        logger.info("Transcription skipped: GEMINI_API_KEY not configured")
        return None, usage

    if duration_seconds > 0 and duration_seconds > config.MAX_TRANSCRIPTION_DURATION:
        logger.info(
            f"Video too long for transcription ({duration_seconds}s > "
            f"{config.MAX_TRANSCRIPTION_DURATION}s), skipping"
        )
        return None, usage

    file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    logger.info(f"Transcribing {video_path} ({file_size_mb:.0f} MB) with {config.GEMINI_MODEL}")

    try:
        transcript = asyncio.run(
            _transcribe_video_async(video_path, config.GEMINI_MODEL, CHUNK_MINUTES, usage)
        )
        return transcript, usage
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return None, usage


def generate_title(transcript: str, usage: UsageStats | None = None) -> str | None:
    """Generate a short title from transcript using Gemini."""
    if not config.GEMINI_API_KEY:
        return None

    try:
        prompt = _load_prompt(config.TITLE_PROMPT_PATH)
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Use only the first ~4000 chars of transcript for title generation
        # (a short title doesn't need the full transcript, and this avoids
        # context window pressure that can cause output truncation)
        transcript_excerpt = transcript[:4000]

        def _generate():
            return client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[prompt + "\n\n" + transcript_excerpt],
                config=types.GenerateContentConfig(
                    max_output_tokens=256,
                    temperature=0.3,
                ),
            )

        response = retry_with_backoff(
            _generate, max_retries=3, delays=(5, 10, 20)
        )
        if usage is not None:
            usage.add_response(response)
        title = response.text.strip()
        logger.info(f"Generated title: {title}")
        return title
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        return None
