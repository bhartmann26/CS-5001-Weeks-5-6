"""
MCP GitHub Tool Server — exposes GitHub API operations via Model Context Protocol.

Tools:
  github_get_issue     — fetch an existing issue
  github_create_issue  — create a new issue
  github_update_issue  — update an existing issue
  github_get_pr        — fetch an existing pull request
  github_create_pr     — create a new pull request
  github_update_pr     — update an existing pull request
  github_verify_token  — verify the GitHub token
  github_list_branches — list repository branches

Transport: stdio (launched as a subprocess by the MCP client)
Requires env vars: GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from utils.github import GitHubClient

mcp = FastMCP("GitHub Tools", instructions="GitHub API tools for issues, PRs, and branches")


def _github() -> GitHubClient:
    token = os.environ.get("GITHUB_TOKEN", "")
    owner = os.environ.get("GITHUB_OWNER", "")
    repo = os.environ.get("GITHUB_REPO", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN environment variable is required")
    if not owner or not repo:
        raise RuntimeError("GITHUB_OWNER and GITHUB_REPO environment variables are required")
    return GitHubClient(token=token, owner=owner, repo=repo)


# ── Issue Tools ────────────────────────────────────────────────────────────────


@mcp.tool()
def github_get_issue(number: int) -> dict:
    """Fetch a GitHub issue by number. Returns the full issue object."""
    return _github().get_issue(number)


@mcp.tool()
def github_create_issue(title: str, body: str, labels: list[str] = None) -> dict:
    """Create a new GitHub issue. Returns the created issue object with number and html_url."""
    return _github().create_issue(title=title, body=body, labels=labels)


@mcp.tool()
def github_update_issue(number: int, title: str = "", body: str = "") -> dict:
    """Update an existing GitHub issue. Only non-empty fields are updated."""
    return _github().update_issue(number=number, title=title or None, body=body or None)


# ── Pull Request Tools ────────────────────────────────────────────────────────


@mcp.tool()
def github_get_pr(number: int) -> dict:
    """Fetch a GitHub pull request by number. Returns the full PR object."""
    return _github().get_pr(number)


@mcp.tool()
def github_create_pr(title: str, body: str, head: str, base: str, draft: bool = False) -> dict:
    """Create a new GitHub pull request. Returns the created PR object with number and html_url."""
    return _github().create_pr(title=title, body=body, head=head, base=base, draft=draft)


@mcp.tool()
def github_update_pr(number: int, title: str = "", body: str = "") -> dict:
    """Update an existing GitHub pull request. Only non-empty fields are updated."""
    return _github().update_pr(number=number, title=title or None, body=body or None)


# ── Utility Tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def github_verify_token() -> bool:
    """Verify that the GitHub token is valid."""
    return _github().verify_token()


@mcp.tool()
def github_list_branches() -> list[str]:
    """List repository branches (up to 50)."""
    return _github().list_branches()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
