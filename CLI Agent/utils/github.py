"""
GitHub API client — pure stdlib, no external dependencies.
Handles Issues and Pull Requests.
"""

import json
import urllib.request
import urllib.error
from typing import Optional
from utils.console import Console


GITHUB_API = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str, owner: str, repo: str):
        self.token = token
        self.owner = owner
        self.repo = repo

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "github-ai-agent/1.0",
        }

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"{GITHUB_API}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            try:
                msg = json.loads(error_body).get("message", error_body)
            except Exception:
                msg = error_body
            raise RuntimeError(f"GitHub API {method} {path} → {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"GitHub API request failed: {e}") from e

    # ── Issues ─────────────────────────────────────────────────────────────

    def get_issue(self, number: int) -> dict:
        return self._request("GET", f"/repos/{self.owner}/{self.repo}/issues/{number}")

    def create_issue(self, title: str, body: str, labels: list[str] = None) -> dict:
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return self._request("POST", f"/repos/{self.owner}/{self.repo}/issues", payload)

    def update_issue(self, number: int, title: str = None, body: str = None) -> dict:
        payload = {}
        if title:
            payload["title"] = title
        if body:
            payload["body"] = body
        return self._request("PATCH", f"/repos/{self.owner}/{self.repo}/issues/{number}", payload)

    # ── Pull Requests ───────────────────────────────────────────────────────

    def get_pr(self, number: int) -> dict:
        return self._request("GET", f"/repos/{self.owner}/{self.repo}/pulls/{number}")

    def create_pr(self, title: str, body: str, head: str, base: str, draft: bool = False) -> dict:
        payload = {"title": title, "body": body, "head": head, "base": base, "draft": draft}
        return self._request("POST", f"/repos/{self.owner}/{self.repo}/pulls", payload)

    def update_pr(self, number: int, title: str = None, body: str = None) -> dict:
        payload = {}
        if title:
            payload["title"] = title
        if body:
            payload["body"] = body
        return self._request("PATCH", f"/repos/{self.owner}/{self.repo}/pulls/{number}", payload)

    # ── Branches ────────────────────────────────────────────────────────────

    def list_branches(self) -> list[str]:
        data = self._request("GET", f"/repos/{self.owner}/{self.repo}/branches?per_page=50")
        return [b["name"] for b in data] if isinstance(data, list) else []

    def verify_token(self) -> bool:
        try:
            self._request("GET", "/user")
            return True
        except Exception:
            return False
