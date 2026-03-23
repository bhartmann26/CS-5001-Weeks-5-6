"""
MCP Git Tool Server — exposes git operations via Model Context Protocol.

Tools:
  git_current_branch   — get the current branch name
  git_diff             — get unified diff (optional commit range)
  git_staged_diff      — get staged changes diff
  git_files_changed    — list files changed (optional commit range)
  git_recent_commits   — list recent commits
  git_diff_stats       — compute diff statistics
  git_untracked_files  — list untracked files

Transport: stdio (launched as a subprocess by the MCP client)
"""

import sys
import os

# Ensure parent dir is on path so we can import utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from utils.git import GitClient, FileChange

mcp = FastMCP("Git Tools", instructions="Git repository analysis tools")

# The repo path is set via environment variable or defaults to cwd
REPO_PATH = os.environ.get("GIT_REPO_PATH", ".")


def _git() -> GitClient:
    return GitClient(REPO_PATH)


# ── Tools ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def git_current_branch() -> str:
    """Get the current git branch name."""
    return _git().current_branch()


@mcp.tool()
def git_diff(commit_range: str = "") -> str:
    """Get unified diff. If no commit_range, diffs working tree against HEAD."""
    return _git().get_diff(commit_range or None)


@mcp.tool()
def git_staged_diff() -> str:
    """Get staged changes diff."""
    return _git().get_staged_diff()


@mcp.tool()
def git_files_changed(commit_range: str = "") -> list[dict]:
    """List files changed with status. Returns list of {status, path, old_path, is_test, is_docs, is_config, has_security_signal}."""
    files = _git().get_files_changed(commit_range or None)
    return [
        {
            "status": f.status,
            "path": f.path,
            "old_path": f.old_path,
            "status_label": f.status_label,
            "is_test": f.is_test,
            "is_docs": f.is_docs,
            "is_config": f.is_config,
            "is_source": f.is_source,
            "has_security_signal": f.has_security_signal(),
        }
        for f in files
    ]


@mcp.tool()
def git_recent_commits(n: int = 8, commit_range: str = "") -> list[dict]:
    """Get recent commits. Returns list of {hash, subject, author, time, refs}."""
    return _git().get_recent_commits(n=n, commit_range=commit_range or None)


@mcp.tool()
def git_diff_stats(diff_text: str, files_json: list[dict]) -> dict:
    """Compute diff statistics from raw diff text and file list.
    
    files_json: list of dicts with at least {status, path} keys.
    Returns {files_changed, lines_added, lines_removed, has_tests, has_docs, has_config, security_sensitive}.
    """
    files = [FileChange(status=f["status"], path=f["path"]) for f in files_json]
    stats = _git().get_diff_stats(diff_text, files)
    return {
        "files_changed": stats.files_changed,
        "lines_added": stats.lines_added,
        "lines_removed": stats.lines_removed,
        "has_tests": stats.has_tests,
        "has_docs": stats.has_docs,
        "has_config": stats.has_config,
        "security_sensitive": stats.security_sensitive,
        "binary_files": stats.binary_files,
    }


@mcp.tool()
def git_untracked_files() -> list[str]:
    """List untracked files in the repository."""
    return _git().get_untracked_files()


@mcp.tool()
def git_remote_url() -> str:
    """Get the remote origin URL."""
    return _git().get_remote_url() or ""


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
