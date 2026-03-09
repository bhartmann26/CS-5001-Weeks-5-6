"""
ImproverAgent — Improve existing GitHub Issues / PRs.

Process:
  1. Fetch the current issue/PR from GitHub
  2. Generate an improved rewrite via Ollama
  3. Show side-by-side (original vs improved) in terminal
  4. Let user approve / edit / cancel — NEVER silently modify
"""

from typing import Optional
from utils.ollama import OllamaClient
from utils.github import GitHubClient
from utils.console import Console
from prompts.templates import improve_issue_prompt, improve_pr_prompt


class ImproverAgent:
    def __init__(self, ollama: OllamaClient, github: GitHubClient):
        self.ollama = ollama
        self.github = github

    def improve(self, number: int, kind: str, context: str = "") -> Optional[dict]:
        """Fetch, improve, and optionally update a GitHub Issue or PR."""

        Console.section(f"Fetching {kind} #{number}")

        # ── 1. Fetch original ──────────────────────────────────────────────
        try:
            if kind == "issue":
                item = self.github.get_issue(number)
            else:
                item = self.github.get_pr(number)
        except Exception as e:
            Console.error(f"Failed to fetch {kind} #{number}: {e}")
            return None

        original_title = item.get("title", "")
        original_body = item.get("body", "") or ""

        Console.kv("Current title", original_title)
        Console.kv("Body length", f"{len(original_body)} characters")
        Console.blank()

        # Show original
        Console.section("Original Content")
        Console.kv("Title", original_title)
        Console.blank()
        Console.markdown_preview(original_body, max_lines=30)

        # ── 2. Generate improvement ────────────────────────────────────────
        Console.blank()
        Console.step(1, 2, f"Generating improved {kind} draft with Ollama…")

        original_full = f"Title: {original_title}\n\n{original_body}"
        if kind == "issue":
            prompt = improve_issue_prompt(original=original_full, context=context)
        else:
            prompt = improve_pr_prompt(original=original_full, context=context)

        try:
            improved_raw = self.ollama.generate(prompt, temperature=0.3, max_tokens=1800)
        except Exception as e:
            Console.error(f"Improvement generation failed: {e}")
            return None

        # Parse IMPROVED TITLE: prefix
        improved_title = original_title
        improved_body = improved_raw

        for line in improved_raw.splitlines():
            if line.startswith("IMPROVED TITLE:"):
                improved_title = line.replace("IMPROVED TITLE:", "").strip()
                rest = improved_raw[improved_raw.index(line) + len(line):]
                improved_body = rest.lstrip("\n")
                break

        Console.step(2, 2, "Review the improvement")

        # ── 3. Interactive review ──────────────────────────────────────────
        while True:
            Console.blank()
            Console.divider("═")
            print(f"  {Console.bold(Console.cyan(f'  ── IMPROVED {kind.upper()} #{number} ──'))}")
            Console.divider("═")
            Console.blank()

            print(f"  {Console.yellow('⚠')}  {Console.bold(Console.yellow('HUMAN APPROVAL REQUIRED'))}")
            Console.info("This is a SUGGESTION only. Review carefully — nothing changes until you confirm.")
            Console.blank()

            # Side-by-side titles
            Console.section("Title Comparison")
            Console.kv("Before", Console.dim(original_title))
            Console.kv("After ",  Console.bold(Console.green(improved_title)))

            Console.blank()
            Console.section("Improved Body")
            Console.markdown_preview(improved_body, max_lines=60)
            Console.blank()
            Console.divider("═")
            Console.blank()

            # Diff hint
            if len(improved_body) > len(original_body):
                delta = len(improved_body) - len(original_body)
                Console.info(f"Body grew by ~{delta} characters")
            else:
                delta = len(original_body) - len(improved_body)
                Console.info(f"Body shrank by ~{delta} characters")

            Console.blank()

            action = Console.choose(
                f"Apply improvement to {kind} #{number}?",
                [
                    "✅  Apply to GitHub",
                    "✏️   Edit improved title",
                    "📝  Edit improved body",
                    "📋  Copy to clipboard (no GitHub update)",
                    "🔄  Regenerate improvement",
                    "❌  Cancel — keep original",
                ],
            )

            if action.startswith("✅"):
                return self._apply_improvement(
                    number=number,
                    kind=kind,
                    original_title=original_title,
                    new_title=improved_title,
                    new_body=improved_body,
                )

            elif action.startswith("✏️"):
                improved_title = Console.prompt("New title", default=improved_title) or improved_title

            elif action.startswith("📝"):
                Console.info("Paste replacement body (end with '###END'):")
                lines = []
                try:
                    while True:
                        line = input()
                        if line.strip() == "###END":
                            break
                        lines.append(line)
                    if lines:
                        improved_body = "\n".join(lines)
                except (KeyboardInterrupt, EOFError):
                    Console.warning("Edit cancelled.")

            elif action.startswith("📋"):
                self._copy_to_clipboard(f"# {improved_title}\n\n{improved_body}")
                Console.success("Copied! No changes made to GitHub.")
                return None

            elif action.startswith("🔄"):
                Console.info("Regenerating with your context hint…")
                new_context = Console.prompt("Additional context for regeneration", default=context)
                original_full = f"Title: {original_title}\n\n{original_body}"
                if kind == "issue":
                    prompt = improve_issue_prompt(original=original_full, context=new_context)
                else:
                    prompt = improve_pr_prompt(original=original_full, context=new_context)
                try:
                    improved_raw = self.ollama.generate(prompt, temperature=0.3, max_tokens=1800)
                    improved_title = original_title
                    improved_body = improved_raw
                    for line in improved_raw.splitlines():
                        if line.startswith("IMPROVED TITLE:"):
                            improved_title = line.replace("IMPROVED TITLE:", "").strip()
                            rest = improved_raw[improved_raw.index(line) + len(line):]
                            improved_body = rest.lstrip("\n")
                            break
                except Exception as e:
                    Console.error(f"Regeneration failed: {e}")

            elif action.startswith("❌"):
                Console.info("Cancelled. Original unchanged.")
                return None

    def _apply_improvement(
        self,
        number: int,
        kind: str,
        original_title: str,
        new_title: str,
        new_body: str,
    ) -> Optional[dict]:
        Console.blank()
        Console.warning(f"About to update {kind} #{number} on GitHub.")
        Console.kv("Repo", f"{self.github.owner}/{self.github.repo}")

        if new_title != original_title:
            Console.kv("Title change", f"{original_title!r} → {new_title!r}")

        if not Console.confirm(f"Apply these changes to {kind} #{number}?", default=False):
            Console.warning("Cancelled. Original unchanged.")
            return None

        try:
            if kind == "issue":
                result = self.github.update_issue(number=number, title=new_title, body=new_body)
            else:
                result = self.github.update_pr(number=number, title=new_title, body=new_body)

            Console.blank()
            Console.success(f"{kind.capitalize()} #{number} updated!")
            Console.kv("URL", result.get("html_url", ""))
            return result

        except Exception as e:
            Console.error(f"Failed to update {kind} #{number}: {e}")
            return None

    @staticmethod
    def _copy_to_clipboard(text: str):
        """Best-effort clipboard copy (no deps required)."""
        import subprocess, sys
        try:
            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
            elif sys.platform.startswith("linux"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
            else:
                Console.info("Clipboard not supported on this platform. Printing instead:")
                print(text)
        except Exception:
            Console.info("Could not copy to clipboard. Printing instead:")
            print(text)
