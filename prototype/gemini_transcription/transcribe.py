"""
Standalone script to transcribe a video file using Gemini API with speaker diarization.

Usage:
    python transcribe.py <path_to_video>

Output:
    Saves transcript as a .txt file next to the video.
"""

import sys
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in .env")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT_FILE = os.getenv("TRANSCRIPTION_PROMPT_PATH",
                         os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../prompts/transcription_prompt.txt"))
with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    TRANSCRIPTION_PROMPT = f.read()


def transcribe_video(video_path: str) -> str:
    if not os.path.exists(video_path):
        print(f"Error: File not found: {video_path}")
        sys.exit(1)

    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"Uploading {video_path} ({file_size_mb:.0f} MB) to Gemini...")

    video_file = client.files.upload(file=video_path)

    # Wait for file processing
    while video_file.state == "PROCESSING":
        print("  Processing video...")
        time.sleep(5)
        video_file = client.files.get(name=video_file.name)

    if video_file.state == "FAILED":
        print(f"Error: File processing failed")
        sys.exit(1)

    print("Upload complete. Generating transcript...")

    def _generate():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[video_file, TRANSCRIPTION_PROMPT],
            config=types.GenerateContentConfig(
                max_output_tokens=65536,
                thinking_config=types.ThinkingConfig(thinking_budget=4096),
            ),
        )

    def _is_retryable(e: Exception):
        error_str = str(e).lower()
        if "400" in error_str and "bad request" in error_str:
            return False
        return True

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))
    from utils import retry_with_backoff
    response = retry_with_backoff(_generate, max_retries=3, delays=(15, 45, 90),
                                  retryable_check=_is_retryable)

    # Cleanup uploaded file
    try:
        client.files.delete(name=video_file.name)
    except Exception:
        pass

    # Check if response was truncated
    finish_reason = None
    if response.candidates and response.candidates[0].finish_reason:
        finish_reason = response.candidates[0].finish_reason
    if finish_reason and str(finish_reason) not in ("STOP", "FinishReason.STOP"):
        print(f"  Warning: response truncated (finish_reason={finish_reason})")

    return response.text


def main():
    if len(sys.argv) != 2:
        print("Usage: python transcribe.py <path_to_video>")
        sys.exit(1)

    video_path = sys.argv[1]
    transcript = transcribe_video(video_path)

    # Save next to video as .txt
    output_path = os.path.splitext(video_path)[0] + "_transcript.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(transcript)

    print(f"\nTranscript saved to: {output_path}")
    print(f"\n--- Preview (first 500 chars) ---\n")
    print(transcript[:500])


if __name__ == "__main__":
    main()
