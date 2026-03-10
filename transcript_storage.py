"""Store transcripts in a GitHub repository via local git clone."""
import logging
import subprocess
from pathlib import Path
from urllib.parse import quote

import config

logger = logging.getLogger(__name__)


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


def _github_url(github_repo: str, filename: str) -> str:
    """Construct GitHub blob URL for a file."""
    return f"https://github.com/{github_repo}/blob/main/{quote(filename)}"


def save_transcript(
    transcript: str,
    folder_name: str,
    title: str | None = None,
) -> str | None:
    """
    Save transcript to the GitHub repo.

    Returns the GitHub URL of the transcript, or None on failure.
    """
    repo_path = config.TRANSCRIPTS_REPO_PATH
    repo_url = config.TRANSCRIPTS_REPO_URL
    github_repo = config.TRANSCRIPTS_GITHUB_REPO

    if not repo_url or not github_repo:
        logger.warning("Transcript storage not configured (missing TRANSCRIPTS_REPO_URL or TRANSCRIPTS_GITHUB_REPO)")
        return None

    try:
        _ensure_repo(repo_path, repo_url)
        _sync_repo(repo_path)

        filename = derive_filename(folder_name, title)
        dest = repo_path / filename
        dest.write_text(transcript, encoding="utf-8")
        logger.info(f"Wrote transcript: {dest}")

        _run(["git", "add", filename], cwd=str(repo_path))

        # Check if there's anything to commit
        status = _run(["git", "status", "--porcelain"], cwd=str(repo_path))
        if not status.stdout.strip():
            logger.info("Transcript already exists with same content, no commit needed")
            return _github_url(github_repo, filename)

        _run(
            ["git", "commit", "-m", f"Add transcript: {filename}"],
            cwd=str(repo_path),
        )
        _run(["git", "push"], cwd=str(repo_path))

        url = _github_url(github_repo, filename)
        logger.info(f"Transcript pushed: {url}")
        return url

    except Exception as e:
        logger.error(f"Failed to save transcript: {e}")
        return None
