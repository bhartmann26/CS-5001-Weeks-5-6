"""
CreatorAgent — Draft and publish GitHub Issues / PRs.

Human approval is REQUIRED before any GitHub action is taken.
The agent:
  1. Generates a draft (title + body) using Ollama
  2. Shows the draft to the user for review/editing
  3. Asks explicit confirmation before publishing
"""

from typing import Optional
from utils.ollama import OllamaClient
from utils.github import GitHubClient
from utils.git import GitClient
from utils.console import Console
from prompts.templates import issue_draft_prompt, pr_draft_prompt


class CreatorAgent:
    def __init__(self, ollama: OllamaClient, github: GitHubClient, git: GitClient):
        self.ollama = ollama
        self.github = github
        self.git = git

    # ── Public API ──────────────────────────────────────────────────────────

    def create_issue(self, review_result, custom_instructions: str = "") -> Optional[dict]:
        Console.section("Drafting GitHub Issue")

        # Verify token
        if not self._verify_github():
            return None

        Console.step(1, 3, "Generating AI draft…")
        prompt = issue_draft_prompt(
            analysis=review_result.raw_analysis,
            diff_snippet=review_result.diff,
            custom_instructions=custom_instructions,
        )

        try:
            body = self.ollama.generate(prompt, temperature=0.3, max_tokens=1500)
        except Exception as e:
            Console.error(f"Draft generation failed: {e}")
            return None

        title = review_result.suggested_title or "Untitled Issue"
        labels = review_result.labels or []

        Console.step(2, 3, "Review draft")
        title, body, labels = self._review_draft(
            title=title,
            body=body,
            labels=labels,
            kind="Issue",
        )
        if title is None:
            Console.warning("Cancelled.")
            return None

        Console.step(3, 3, "Publishing to GitHub…")
        result = self._confirm_and_create_issue(title=title, body=body, labels=labels)
        return result

    def create_pr(
        self,
        review_result,
        base_branch: str = "main",
        custom_instructions: str = "",
    ) -> Optional[dict]:
        Console.section("Drafting GitHub Pull Request")

        if not self._verify_github():
            return None

        head_branch = review_result.branch

        Console.step(1, 3, "Generating AI draft…")
        prompt = pr_draft_prompt(
            analysis=review_result.raw_analysis,
            diff_snippet=review_result.diff,
            branch=head_branch,
            base_branch=base_branch,
            custom_instructions=custom_instructions,
        )

        try:
            body = self.ollama.generate(prompt, temperature=0.3, max_tokens=1500)
        except Exception as e:
            Console.error(f"Draft generation failed: {e}")
            return None

        title = review_result.suggested_title or f"Changes from {head_branch}"
        labels = review_result.labels or []

        Console.step(2, 3, "Review draft")
        title, body, labels = self._review_draft(
            title=title,
            body=body,
            labels=labels,
            kind="Pull Request",
            extra_info=f"  Head: {head_branch} → Base: {base_branch}",
        )
        if title is None:
            Console.warning("Cancelled.")
            return None

        # Confirm head branch
        head_branch = Console.prompt("Head branch to merge FROM", default=head_branch)
        base_branch = Console.prompt("Base branch to merge INTO", default=base_branch)
        draft_pr = Console.confirm("Create as draft PR?", default=False)

        Console.step(3, 3, "Publishing to GitHub…")
        result = self._confirm_and_create_pr(
            title=title, body=body,
            head=head_branch, base=base_branch,
            draft=draft_pr,
        )
        return result

    # ── Review draft interactively ──────────────────────────────────────────

    def _review_draft(
        self,
        title: str,
        body: str,
        labels: list,
        kind: str,
        extra_info: str = "",
    ) -> tuple[Optional[str], Optional[str], Optional[list]]:
        """Show draft to user and allow edits. Returns (title, body, labels) or (None, None, None) if cancelled."""

        while True:
            Console.blank()
            Console.divider("═")
            print(f"  {Console.bold(Console.cyan(f'  ── DRAFT {kind.upper()} ──'))}")
            Console.divider("═")
            Console.blank()

            # ⚠️ Approval banner
            print(f"  {Console.yellow('⚠')}  {Console.bold(Console.yellow('HUMAN APPROVAL REQUIRED'))}")
            Console.info("Review the AI-generated draft below. Nothing is published until you confirm.")
            if extra_info:
                Console.info(extra_info)
            Console.blank()

            Console.kv("Title", Console.bold(title))
            if labels:
                Console.kv("Labels", ", ".join(labels))
            Console.blank()
            Console.kv("Body preview", "")
            Console.markdown_preview(body, max_lines=60)
            Console.blank()
            Console.divider("═")
            Console.blank()

            action = Console.choose(
                "What would you like to do?",
                [
                    "✅  Approve and publish",
                    "✏️   Edit title",
                    "📝  Edit body in terminal",
                    "🏷️   Edit labels",
                    "🔄  Regenerate draft",
                    "❌  Cancel",
                ],
            )

            if action.startswith("✅"):
                return title, body, labels

            elif action.startswith("✏️"):
                title = Console.prompt("New title", default=title) or title

            elif action.startswith("📝"):
                Console.info("Paste new body (end with a line containing only '###END'):")
                lines = []
                try:
                    while True:
                        line = input()
                        if line.strip() == "###END":
                            break
                        lines.append(line)
                    if lines:
                        body = "\n".join(lines)
                except (KeyboardInterrupt, EOFError):
                    Console.warning("Edit cancelled, keeping previous body.")

            elif action.startswith("🏷️"):
                raw = Console.prompt("Labels (comma-separated)", default=", ".join(labels))
                labels = [l.strip() for l in raw.split(",") if l.strip()]

            elif action.startswith("🔄"):
                Console.info("Regenerating…")
                return "__regenerate__", body, labels

            elif action.startswith("❌"):
                return None, None, None

    # ── GitHub publishing ───────────────────────────────────────────────────

    def _confirm_and_create_issue(self, title: str, body: str, labels: list) -> Optional[dict]:
        Console.blank()
        Console.warning(f"About to create issue: '{title}'")
        Console.info(f"Repo: {self.github.owner}/{self.github.repo}")
        if not Console.confirm("Publish this issue to GitHub?", default=False):
            Console.warning("Cancelled — nothing was published.")
            return None

        try:
            result = self.github.create_issue(title=title, body=body, labels=labels)
            Console.blank()
            Console.success(f"Issue #{result['number']} created!")
            Console.kv("URL", result["html_url"])
            return result
        except Exception as e:
            Console.error(f"Failed to create issue: {e}")
            return None

    def _confirm_and_create_pr(
        self, title: str, body: str, head: str, base: str, draft: bool
    ) -> Optional[dict]:
        Console.blank()
        Console.warning(f"About to create PR: '{title}'")
        Console.info(f"Repo: {self.github.owner}/{self.github.repo}  |  {head} → {base}")
        if draft:
            Console.info("(draft PR)")
        if not Console.confirm("Publish this PR to GitHub?", default=False):
            Console.warning("Cancelled — nothing was published.")
            return None

        try:
            result = self.github.create_pr(title=title, body=body, head=head, base=base, draft=draft)
            Console.blank()
            Console.success(f"PR #{result['number']} created!")
            Console.kv("URL", result["html_url"])
            return result
        except Exception as e:
            Console.error(f"Failed to create PR: {e}")
            return None

    def _verify_github(self) -> bool:
        Console.info(f"Verifying GitHub token for {self.github.owner}/{self.github.repo}…")
        if not self.github.verify_token():
            Console.error("GitHub token is invalid or expired.")
            return False
        Console.success("GitHub token verified.")
        return True
