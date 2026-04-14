"""
Generate meeting summaries using Gemini API.

A single universal prompt handles all meeting formats (technical, forum,
check-in, meditation, etc.) — the model adapts structure to what actually
happened.

Usage:
    python summarize.py <path_to_transcript.md>
    python summarize.py --all          # all transcripts without summaries

Output:
    Saves summary as .md in meeting-transcripts/summaries/
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load .env from project root
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in .env")
    sys.exit(1)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")

# Paths
PROTO_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PROTO_DIR.parents[1]
TRANSCRIPTS_DIR = PROJECT_ROOT / "meeting-transcripts" / "transcripts"
SUMMARIES_DIR = PROJECT_ROOT / "meeting-transcripts" / "summaries"
SUMMARY_PROMPT_PATH = Path(
    os.getenv("SUMMARY_PROMPT_PATH", PROJECT_ROOT / "meeting-transcripts" / "prompts" / "summary_prompt.txt")
)

INPUT_PRICE_PER_MTOK = float(os.getenv("GEMINI_INPUT_PRICE_PER_MTOK", "1.25"))
OUTPUT_PRICE_PER_MTOK = float(os.getenv("GEMINI_OUTPUT_PRICE_PER_MTOK", "10.0"))

# Retry helper
sys.path.insert(0, str(PROJECT_ROOT))
from utils import retry_with_backoff


def _response_cost(response) -> tuple[str, int, int, int]:
    """Extract usage from response. Returns (cost_string, input_tokens, output_tokens, thinking_tokens)."""
    meta = response.usage_metadata
    if not meta:
        return ("?", 0, 0, 0)
    inp = meta.prompt_token_count or 0
    out = meta.candidates_token_count or 0
    think = meta.thoughts_token_count or 0
    cost = (inp / 1e6) * INPUT_PRICE_PER_MTOK + ((out + think) / 1e6) * OUTPUT_PRICE_PER_MTOK
    return (f"${cost:.3f}", inp, out, think)


def generate_summary(client: genai.Client, transcript: str, model: str) -> str:
    """Generate a summary using the universal prompt."""
    prompt = SUMMARY_PROMPT_PATH.read_text(encoding="utf-8")

    def _generate():
        return client.models.generate_content(
            model=model,
            contents=[prompt + "\n\n---\n\n" + transcript],
            config=types.GenerateContentConfig(
                max_output_tokens=16384,
                temperature=0.3,
            ),
        )

    response = retry_with_backoff(_generate, max_retries=2, delays=(10, 30))
    cost_str, inp, out, think = _response_cost(response)
    print(f"  Summary: {cost_str} (in={inp}, out={out}, think={think})")
    return response.text.strip()


def summarize_file(
    transcript_path: Path,
    client: genai.Client,
    model: str,
    overwrite: bool = False,
) -> Path | None:
    """Summarize a single transcript file. Returns output path or None."""
    print(f"\n{'='*60}")
    print(f"File: {transcript_path.name}")

    output_path = SUMMARIES_DIR / transcript_path.name
    if output_path.exists() and not overwrite:
        print(f"  Summary already exists, skipping (use --overwrite to regenerate)")
        return None

    transcript = transcript_path.read_text(encoding="utf-8")
    if not transcript.strip():
        print(f"  Empty transcript, skipping")
        return None

    t0 = time.time()
    summary = generate_summary(client, transcript, model)
    elapsed = time.time() - t0
    print(f"  Length: {len(summary)} chars ({elapsed:.1f}s)")

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary, encoding="utf-8")
    print(f"  Saved: {output_path}")

    preview_lines = summary.split("\n")[:8]
    print(f"  ---")
    for line in preview_lines:
        print(f"  {line}")
    if len(summary.split("\n")) > 8:
        print(f"  ...")

    return output_path


def find_transcripts_without_summaries() -> list[Path]:
    """Find transcript files that don't have a corresponding summary."""
    if not TRANSCRIPTS_DIR.exists():
        print(f"Transcripts directory not found: {TRANSCRIPTS_DIR}")
        return []

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    existing_summaries = {f.name for f in SUMMARIES_DIR.glob("*.md")}

    transcripts = sorted(TRANSCRIPTS_DIR.glob("*.md"))
    return [t for t in transcripts if t.name not in existing_summaries]


def main():
    parser = argparse.ArgumentParser(description="Generate meeting summaries via Gemini")
    parser.add_argument("transcript", nargs="?", help="Path to transcript .md file")
    parser.add_argument("--all", action="store_true", help="Process all transcripts without summaries")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model (default: {DEFAULT_MODEL})")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing summaries")
    args = parser.parse_args()

    if not args.transcript and not args.all:
        parser.error("Provide a transcript path or use --all")

    client = genai.Client(api_key=GEMINI_API_KEY)

    if args.all:
        files = find_transcripts_without_summaries()
        if not files:
            print("All transcripts already have summaries.")
            return
        print(f"Found {len(files)} transcript(s) to summarize")
        for f in files:
            try:
                summarize_file(f, client, args.model, args.overwrite)
            except Exception as e:
                print(f"  ERROR: {e}")
    else:
        path = Path(args.transcript)
        if not path.exists():
            print(f"File not found: {path}")
            sys.exit(1)
        summarize_file(path, client, args.model, args.overwrite)


if __name__ == "__main__":
    main()
