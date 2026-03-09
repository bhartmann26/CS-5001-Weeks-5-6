"""
ReviewAgent — Task 1: Analyze git changes.

Steps:
  1. Collect diff + file list + commit history
  2. Compute diff stats locally
  3. Send to Ollama for AI analysis (JSON schema)
  4. Display full structured report with evidence
  5. Return ReviewResult for downstream use by CreatorAgent
"""

from dataclasses import dataclass, field
from typing import Optional
from utils.git import GitClient, DiffStats
from utils.ollama import OllamaClient
from utils.console import Console
from prompts.templates import analysis_prompt


@dataclass
class ReviewResult:
    category: str
    risk: str
    risk_reason: str
    summary: str
    issues: list
    improvements: list
    recommendation: str          # create_issue | create_pr | no_action
    justification: str
    suggested_title: str
    labels: list
    stats: dict
    diff: str
    files: list
    branch: str
    raw_analysis: dict = field(default_factory=dict)


class ReviewAgent:
    def __init__(self, git: GitClient, ollama: OllamaClient):
        self.git = git
        self.ollama = ollama

    def review(
        self,
        commit_range: Optional[str] = None,
        include_staged: bool = False,
        include_untracked: bool = False,
    ) -> Optional[ReviewResult]:

        Console.section("Collecting repository changes")

        # ── 1. Gather raw git data ─────────────────────────────────────────
        branch = self.git.current_branch()
        Console.kv("Branch", branch)

        Console.step(1, 4, "Reading git diff…")
        diff = self.git.get_diff(commit_range)
        if include_staged:
            staged = self.git.get_staged_diff()
            if staged.strip():
                diff += "\n\n--- STAGED CHANGES ---\n\n" + staged

        if not diff.strip():
            Console.info("No diff found.")
            return None

        Console.step(2, 4, "Listing changed files…")
        files = self.git.get_files_changed(commit_range)
        if include_untracked:
            untracked = self.git.get_untracked_files()
            Console.info(f"Untracked files: {len(untracked)}")
            for f in untracked:
                Console.info(f"  + {f}")

        Console.step(3, 4, "Loading recent commits…")
        commits = self.git.get_recent_commits(n=8, commit_range=commit_range)
        stats = self.git.get_diff_stats(diff, files)

        # ── 2. Display local stats ─────────────────────────────────────────
        self._show_file_summary(files, stats, commits)

        # ── 3. AI Analysis ─────────────────────────────────────────────────
        Console.step(4, 4, f"Sending to Ollama ({self.ollama.model})…")
        Console.info("This may take 20–60 seconds for large diffs…")

        files_summary = self._build_files_summary(files)
        commits_summary = self._build_commits_summary(commits)

        prompt = analysis_prompt(
            diff=diff,
            files_summary=files_summary,
            branch=branch,
            recent_commits=commits_summary,
        )

        try:
            analysis = self.ollama.generate_json(prompt)
        except Exception as e:
            Console.error(f"AI analysis failed: {e}")
            return None

        # ── 4. Build result ────────────────────────────────────────────────
        result = ReviewResult(
            category=analysis.get("category", "unknown"),
            risk=analysis.get("risk", "unknown"),
            risk_reason=analysis.get("risk_reason", ""),
            summary=analysis.get("summary", ""),
            issues=analysis.get("issues", []),
            improvements=analysis.get("improvements", []),
            recommendation=analysis.get("recommendation", {}).get("action", "no_action"),
            justification=analysis.get("recommendation", {}).get("justification", ""),
            suggested_title=analysis.get("recommendation", {}).get("suggested_title", ""),
            labels=analysis.get("recommendation", {}).get("labels", []),
            stats=analysis.get("stats", {}),
            diff=diff,
            files=files,
            branch=branch,
            raw_analysis=analysis,
        )

        # ── 5. Display full report ─────────────────────────────────────────
        self._show_report(result)

        return result

    # ── Display helpers ────────────────────────────────────────────────────

    def _show_file_summary(self, files, stats: DiffStats, commits: list):
        Console.blank()
        Console.section("Change Overview")

        status_colors = {
            "A": Console.success,
            "M": Console.info,
            "D": Console.error,
            "R": Console.warning,
        }

        for fc in files:
            fn = status_colors.get(fc.status, Console.info)
            tags = []
            if fc.is_test:  tags.append("test")
            if fc.is_docs:  tags.append("docs")
            if fc.is_config: tags.append("config")
            if fc.has_security_signal(): tags.append("⚠ security")
            tag_str = f"  {Console.dim(' '.join(f'[{t}]' for t in tags))}" if tags else ""
            fn(f"  {fc.status_label.upper():10}  {fc.path}{tag_str}")

        Console.blank()
        Console.kv("Files changed", str(stats.files_changed))
        Console.kv("Lines added",   f"+{stats.lines_added}")
        Console.kv("Lines removed", f"-{stats.lines_removed}")
        Console.kv("Has tests",     "yes" if stats.has_tests else "no")
        Console.kv("Has docs",      "yes" if stats.has_docs else "no")

        if stats.security_sensitive:
            Console.warning("Security-sensitive files detected — extra caution recommended.")

        if commits:
            Console.blank()
            Console.section("Recent Commits")
            for c in commits[:5]:
                Console.info(f"{Console.cyan(c['hash'])}  {c['subject']}  {Console.dim(c['time'])}")

    def _show_report(self, r: ReviewResult):
        Console.blank()
        Console.section("AI Analysis Report")

        # Category + risk
        cat = Console.category_badge(r.category)
        risk = Console.risk_badge(r.risk)
        print(f"  {cat}  {risk}")
        Console.blank()

        Console.kv("Summary", "")
        Console.text_block(r.summary)

        Console.blank()
        Console.kv("Risk Reason", "")
        Console.text_block(r.risk_reason)

        # Issues
        if r.issues:
            Console.blank()
            Console.section(f"Issues Found ({len(r.issues)})")
            SEV_FN = {"critical": Console.error, "warning": Console.warning, "info": Console.info}
            for i, issue in enumerate(r.issues, 1):
                sev = issue.get("severity", "info")
                fn = SEV_FN.get(sev, Console.info)
                fn(f"[{sev.upper()}] {issue.get('file', '?')} — {issue.get('description', '')}")
                if issue.get("line_hint"):
                    Console.info(f"  Location: {issue['line_hint']}")
                Console.info(f"  → Fix: {issue.get('suggestion', '')}")
                if issue.get("evidence"):
                    print(f"    {Console.dim('Evidence:')} {Console.dim(issue['evidence'][:120])}")
                Console.blank()
        else:
            Console.success("No issues found")

        # Improvements
        if r.improvements:
            Console.section(f"Suggested Improvements ({len(r.improvements)})")
            for imp in r.improvements:
                Console.info(f"[{imp.get('type','?').upper()}] {imp.get('file','?')} — {imp.get('description','')}")
                Console.info(f"  → {imp.get('suggestion','')}")
                if imp.get("evidence"):
                    print(f"    {Console.dim('Evidence:')} {Console.dim(imp['evidence'][:100])}")
            Console.blank()

        # Recommendation
        Console.blank()
        Console.section("Agent Decision")

        action = r.recommendation
        ACTION_FN = {
            "create_issue": Console.warning,
            "create_pr": Console.success,
            "no_action": Console.info,
        }
        ACTION_LABEL = {
            "create_issue": "▶ CREATE ISSUE",
            "create_pr": "▶ CREATE PULL REQUEST",
            "no_action": "● NO ACTION REQUIRED",
        }
        fn = ACTION_FN.get(action, Console.info)
        fn(ACTION_LABEL.get(action, action.upper()))
        Console.blank()
        Console.kv("Justification", "")
        Console.text_block(r.justification)

        if r.suggested_title:
            Console.blank()
            Console.kv("Suggested title", Console.bold(r.suggested_title))

        if r.labels:
            Console.kv("Labels", ", ".join(r.labels))

        Console.blank()
        Console.divider()

    @staticmethod
    def _build_files_summary(files) -> str:
        return "\n".join(f"  {f.status_label.upper():10} {f.path}" for f in files)

    @staticmethod
    def _build_commits_summary(commits) -> str:
        return "\n".join(
            f"  {c['hash']} {c['subject']} ({c['author']}, {c['time']})"
            for c in commits
        )
