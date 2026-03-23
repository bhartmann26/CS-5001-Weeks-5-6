"""
Git utility — wraps subprocess git commands.
All diff / log / branch operations live here.
"""

import subprocess
import re
from dataclasses import dataclass, field
from typing import Optional
from utils.console import Console


@dataclass
class FileChange:
    status: str          # A=added, M=modified, D=deleted, R=renamed
    path: str
    old_path: Optional[str] = None  # only for renames

    @property
    def status_label(self) -> str:
        labels = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied"}
        return labels.get(self.status, self.status)

    @property
    def extension(self) -> str:
        return self.path.rsplit(".", 1)[-1].lower() if "." in self.path else ""

    @property
    def is_test(self) -> bool:
        return bool(re.search(r"(test|spec)[_\.]|[_\.](test|spec)\.", self.path, re.I))

    @property
    def is_docs(self) -> bool:
        return self.extension in ("md", "rst", "txt", "adoc") or "docs/" in self.path

    @property
    def is_config(self) -> bool:
        return self.extension in ("json", "yaml", "yml", "toml", "ini", "cfg", "env") \
               or self.path in ("Dockerfile", "Makefile", ".gitignore")

    @property
    def is_source(self) -> bool:
        return self.extension in (
            "py", "js", "ts", "jsx", "tsx", "go", "rs", "java", "c", "cpp",
            "cs", "rb", "php", "swift", "kt", "scala", "r", "sh", "bash"
        )

    def has_security_signal(self) -> bool:
        signals = ("auth", "password", "secret", "token", "crypto", "jwt",
                   "oauth", "permission", "acl", "role", "admin", "sudo",
                   "inject", "xss", "csrf", "sql")
        low = self.path.lower()
        return any(s in low for s in signals)


@dataclass
class DiffStats:
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    has_tests: bool = False
    has_docs: bool = False
    has_config: bool = False
    security_sensitive: bool = False
    binary_files: list = field(default_factory=list)


class GitClient:
    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path
        self._validate()

    def _validate(self):
        try:
            self._run(["git", "rev-parse", "--git-dir"], silent=True)
        except subprocess.CalledProcessError:
            Console.error(f"'{self.repo_path}' is not a git repository.")
            raise SystemExit(1)

    def _run(self, cmd: list, silent=False) -> str:
        result = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 and not silent:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result.stdout

    def current_branch(self) -> str:
        return self._run(["git", "branch", "--show-current"]).strip() or "HEAD"

    def default_remote_branch(self) -> str:
        """Try to find the default branch (main/master)."""
        try:
            out = self._run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], silent=True).strip()
            return out.split("/")[-1]
        except Exception:
            for b in ("main", "master"):
                try:
                    self._run(["git", "rev-parse", "--verify", b], silent=True)
                    return b
                except Exception:
                    pass
            return "main"

    def get_diff(self, commit_range: Optional[str] = None) -> str:
        """Get unified diff. If no range, diffs working tree against HEAD."""
        if commit_range:
            cmd = ["git", "diff", commit_range, "--", "."]
        else:
            cmd = ["git", "diff", "HEAD", "--", "."]
        return self._run(cmd)

    def get_staged_diff(self) -> str:
        return self._run(["git", "diff", "--staged", "--", "."])

    def get_files_changed(self, commit_range: Optional[str] = None) -> list[FileChange]:
        """Return list of FileChange objects."""
        if commit_range:
            cmd = ["git", "diff", "--name-status", commit_range]
        else:
            cmd = ["git", "diff", "--name-status", "HEAD"]
        output = self._run(cmd)
        staged = self._run(["git", "diff", "--name-status", "--staged"])
        combined = _merge_name_status(output, staged)
        return _parse_name_status(combined)

    def get_recent_commits(self, n: int = 10, commit_range: Optional[str] = None) -> list[dict]:
        fmt = "%H|%s|%an|%ar|%D"
        if commit_range:
            cmd = ["git", "log", f"--format={fmt}", commit_range]
        else:
            cmd = ["git", "log", f"--format={fmt}", f"-{n}"]
        output = self._run(cmd)
        commits = []
        for line in output.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 4)
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0][:8],
                    "subject": parts[1],
                    "author": parts[2],
                    "time": parts[3],
                    "refs": parts[4] if len(parts) > 4 else "",
                })
        return commits

    def get_diff_stats(self, diff_text: str, files: list[FileChange]) -> DiffStats:
        stats = DiffStats()
        stats.files_changed = len(files)
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                stats.lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                stats.lines_removed += 1
        stats.has_tests = any(f.is_test for f in files)
        stats.has_docs = any(f.is_docs for f in files)
        stats.has_config = any(f.is_config for f in files)
        stats.security_sensitive = any(f.has_security_signal() for f in files)
        stats.binary_files = [f.path for f in files if not (f.is_source or f.is_docs or f.is_config or f.is_test)]
        return stats

    def get_remote_url(self) -> Optional[str]:
        try:
            return self._run(["git", "remote", "get-url", "origin"], silent=True).strip()
        except Exception:
            return None

    def get_untracked_files(self) -> list[str]:
        output = self._run(["git", "ls-files", "--others", "--exclude-standard"])
        return [f for f in output.strip().splitlines() if f]


def _merge_name_status(working: str, staged: str) -> str:
    """Merge name-status output, dedup by filename."""
    seen = {}
    for block in [working, staged]:
        for line in block.strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                seen[parts[1]] = line
    return "\n".join(seen.values())


def _parse_name_status(output: str) -> list[FileChange]:
    changes = []
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][0].upper()  # R100 -> R
        if status == "R" and len(parts) == 3:
            changes.append(FileChange(status="R", path=parts[2], old_path=parts[1]))
        elif len(parts) >= 2:
            changes.append(FileChange(status=status, path=parts[1]))
    return changes
