"""
Push a transcript file to the meeting-transcripts GitHub repo.

Usage:
    python push_transcript.py <transcript_path> [--title "Custom title"]

The filename in the repo is derived from the parent folder name:
    "2026-03-03 12-00 - Вместе на полянке" → "2026-03-03 12-00 - Вместе на полянке.txt"

If --title is given, it replaces the topic part:
    "2026-03-03 12-00 - Custom title.txt"
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

TRANSCRIPTS_REPO_URL = os.getenv("TRANSCRIPTS_REPO_URL")
TRANSCRIPTS_GITHUB_REPO = os.getenv("TRANSCRIPTS_GITHUB_REPO")

if not TRANSCRIPTS_REPO_URL or not TRANSCRIPTS_GITHUB_REPO:
    print("Error: TRANSCRIPTS_REPO_URL and TRANSCRIPTS_GITHUB_REPO must be set in .env")
    sys.exit(1)


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  STDERR: {result.stderr.strip()}")
        result.check_returncode()
    return result


def derive_filename(transcript_path: str, title: str | None = None) -> str:
    """Derive target filename from the meeting folder name."""
    folder_name = Path(transcript_path).parent.name
    # folder_name example: "2026-03-03 12-00 - Вместе на полянке"

    if title:
        # Replace topic part: everything after " - "
        parts = folder_name.split(" - ", 1)
        date_time = parts[0]  # "2026-03-03 12-00"
        return f"{date_time} - {title}.txt"

    return f"{folder_name}.txt"


def push_transcript(transcript_path: str, title: str | None = None) -> str:
    """Clone repo, add transcript, commit and push. Returns the GitHub URL."""
    transcript_path = os.path.abspath(transcript_path)
    if not os.path.exists(transcript_path):
        print(f"Error: {transcript_path} not found")
        sys.exit(1)

    filename = derive_filename(transcript_path, title)
    print(f"Transcript: {transcript_path}")
    print(f"Target filename: {filename}")

    # Clone into a temp directory
    tmp_dir = tempfile.mkdtemp(prefix="transcripts_")
    repo_dir = os.path.join(tmp_dir, "repo")

    try:
        print("\nCloning repo...")
        run(["git", "clone", "--depth", "1", TRANSCRIPTS_REPO_URL, repo_dir])

        # Copy transcript
        dest = os.path.join(repo_dir, filename)
        shutil.copy2(transcript_path, dest)
        print(f"Copied to {dest}")

        # Commit and push
        run(["git", "add", filename], cwd=repo_dir)

        # Check if there's anything to commit
        status = run(["git", "status", "--porcelain"], cwd=repo_dir)
        if not status.stdout.strip():
            print("Nothing to commit — file already exists with same content")
            return _github_url(filename)

        run(["git", "commit", "-m", f"Add transcript: {filename}"], cwd=repo_dir)

        print("\nPushing...")
        run(["git", "push"], cwd=repo_dir)

        url = _github_url(filename)
        print(f"\nDone! {url}")
        return url

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _github_url(filename: str) -> str:
    from urllib.parse import quote
    return f"https://github.com/{TRANSCRIPTS_GITHUB_REPO}/blob/main/{quote(filename)}"


def main():
    parser = argparse.ArgumentParser(description="Push transcript to GitHub repo")
    parser.add_argument("transcript_path", help="Path to transcript .txt file")
    parser.add_argument("--title", "-t", help="Custom title (replaces topic from folder name)")
    args = parser.parse_args()

    push_transcript(args.transcript_path, args.title)


if __name__ == "__main__":
    main()
