"""Store transcripts in a GitHub repository via local git clone."""
import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import config

logger = logging.getLogger(__name__)

_TIMESTAMP_RE = re.compile(r"^\[\d+:\d+(?::\d+)?\]")


def _run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command with logging."""
    logger.debug(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        logger.warning(f"  STDERR: {result.stderr.strip()}")
        result.check_returncode()
    return result


def _ensure_repo(repo_path: Path, repo_url: str) -> None:
    """Clone the repo if it doesn't exist locally."""
    if (repo_path / ".git").exists():
        logger.debug(f"Repo already exists at {repo_path}")
        return

    logger.info(f"Cloning transcripts repo to {repo_path}...")
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", repo_url, str(repo_path)])


def _sync_repo(repo_path: Path) -> None:
    """Reset any dirty state and pull latest changes."""
    # Reset uncommitted changes from previous failed runs
    _run(["git", "checkout", "--", "."], cwd=str(repo_path), check=False)
    _run(["git", "clean", "-fd"], cwd=str(repo_path), check=False)
    # Pull latest
    _run(["git", "pull", "--rebase"], cwd=str(repo_path))


def derive_filename(folder_name: str, title: str | None = None) -> str:
    """
    Derive transcript filename from meeting folder name and optional generated title.

    folder_name: "2026-03-03 12-00 - Вместе на полянке"
    title: "Баланс кошельков и аналитика" (from Gemini)

    Returns: "2026-03-03 12-00 - Баланс кошельков и аналитика.md"
    """
    if title:
        parts = folder_name.split(" - ", 1)
        date_time = parts[0]  # "2026-03-03 12-00"
        return f"{date_time} - {title}.md"
    return f"{folder_name}.md"


def _github_url(github_repo: str, filepath: str) -> str:
    """Construct GitHub blob URL for a file."""
    return f"https://github.com/{github_repo}/blob/main/{quote(filepath)}"


def sync_clone() -> None:
    """Ensure the transcripts repo is cloned, pulled to latest, and clean of dirty state.

    Call once at the start of the transcript+summary step. All subsequent
    writes/reads in this module assume the clone is already synced and do not
    touch git until the final commit in save_transcript_and_summary.
    """
    repo_path = config.TRANSCRIPTS_REPO_PATH
    repo_url = config.TRANSCRIPTS_REPO_URL
    if not repo_url:
        raise RuntimeError("TRANSCRIPTS_REPO_URL not configured")
    _ensure_repo(repo_path, repo_url)
    _sync_repo(repo_path)


def write_transcript_raw(
    transcript_body: str,
    folder_name: str,
    title: str | None = None,
) -> None:
    """Write raw transcript body to the clone locally (no header, no commit).

    Used right after a fresh transcription so that subsequent code paths can
    uniformly load the transcript from disk via ``load_transcript_body``.
    The file is overwritten with headers + cross-refs later in
    ``save_transcript_and_summary``.
    """
    filename = derive_filename(folder_name, title)
    transcripts_dir = config.TRANSCRIPTS_REPO_PATH / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    dest = transcripts_dir / filename
    dest.write_text(transcript_body, encoding="utf-8")
    logger.debug(f"Wrote raw transcript to clone: {dest}")


def _strip_header(text: str) -> str:
    """Strip markdown header (everything before first ``[MM:SS]``-prefixed line)."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _TIMESTAMP_RE.match(line):
            return "\n".join(lines[i:])
    return text


def load_transcript_body(folder_name: str, title: str | None = None) -> str:
    """Load transcript from the clone and return only its body (header stripped).

    Raises ``FileNotFoundError`` if the file is missing. Assumes ``sync_clone``
    was called earlier; does not touch git.
    """
    filename = derive_filename(folder_name, title)
    path = config.TRANSCRIPTS_REPO_PATH / "transcripts" / filename
    if not path.exists():
        raise FileNotFoundError(f"Transcript not found in clone: {path}")
    full_text = path.read_text(encoding="utf-8")
    return _strip_header(full_text)


def predict_urls(folder_name: str, title: str | None = None) -> tuple[str, str]:
    """Compute (transcript_url, summary_url) in advance, before saving anything.

    Both files use the same filename, derived from folder_name + title.
    """
    github_repo = config.TRANSCRIPTS_GITHUB_REPO
    if not github_repo:
        raise RuntimeError("TRANSCRIPTS_GITHUB_REPO not configured")

    filename = derive_filename(folder_name, title)
    transcript_rel = f"transcripts/{filename}"
    summary_rel = f"summaries/{filename}"
    return (
        _github_url(github_repo, transcript_rel),
        _github_url(github_repo, summary_rel),
    )


def save_transcript_and_summary(
    transcript: str,
    summary: str,
    folder_name: str,
    title: str | None = None,
) -> tuple[str, str]:
    """
    Save transcript + summary to the GitHub repo in a single commit.

    Raises on failure. Returns (transcript_url, summary_url).
    """
    repo_path = config.TRANSCRIPTS_REPO_PATH
    repo_url = config.TRANSCRIPTS_REPO_URL
    github_repo = config.TRANSCRIPTS_GITHUB_REPO

    if not repo_url or not github_repo:
        raise RuntimeError(
            "Transcript storage not configured (missing TRANSCRIPTS_REPO_URL or TRANSCRIPTS_GITHUB_REPO)"
        )

    # Caller is expected to have called ``sync_clone`` already; do not sync here
    # to avoid wiping out any intermediate local state (e.g. a raw transcript
    # written earlier in the same step).

    filename = derive_filename(folder_name, title)

    transcripts_dir = repo_path / "transcripts"
    transcripts_dir.mkdir(exist_ok=True)
    transcript_dest = transcripts_dir / filename
    transcript_dest.write_text(transcript, encoding="utf-8")
    logger.info(f"Wrote transcript: {transcript_dest}")

    summaries_dir = repo_path / "summaries"
    summaries_dir.mkdir(exist_ok=True)
    summary_dest = summaries_dir / filename
    summary_dest.write_text(summary, encoding="utf-8")
    logger.info(f"Wrote summary: {summary_dest}")

    transcript_rel = f"transcripts/{filename}"
    summary_rel = f"summaries/{filename}"
    _run(["git", "add", transcript_rel, summary_rel], cwd=str(repo_path))

    transcript_url = _github_url(github_repo, transcript_rel)
    summary_url = _github_url(github_repo, summary_rel)

    status = _run(["git", "status", "--porcelain"], cwd=str(repo_path))
    if not status.stdout.strip():
        logger.info("Transcript and summary already exist with same content, no commit needed")
        return transcript_url, summary_url

    _run(
        ["git", "commit", "-m", f"Add transcript and summary: {filename}"],
        cwd=str(repo_path),
    )
    _run(["git", "push"], cwd=str(repo_path))

    logger.info(f"Transcript pushed: {transcript_url}")
    logger.info(f"Summary pushed: {summary_url}")
    return transcript_url, summary_url
