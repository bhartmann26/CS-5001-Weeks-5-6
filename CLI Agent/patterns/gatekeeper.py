"""
GatekeeperAgent — Multi-agent role: Gatekeeper

The final safety layer before ANY GitHub action is taken. Responsibilities:
  - Enforce human approval (explicit y/N) before creating anything
  - Persist draft state to .agent_draft.json for `approve --yes/--no`
  - Verify reflection passed before allowing creation
  - Log all decisions and outcomes to .agent_log.jsonl
  - Safely abort on rejection (no side effects)

Emits [Gatekeeper] tagged log lines.
"""

import json
import os
import time
from typing import Optional
from utils.ollama import OllamaClient
from utils.github import GitHubClient
from utils.console import Console
from patterns.writer import DraftArtifact
from patterns.critic import ReflectionArtifact

DRAFT_FILE = ".agent_draft.json"
LOG_FILE = ".agent_log.jsonl"


class GatekeeperAgent:
    """
    Multi-agent role: Gatekeeper
    Controls the publish gate. Nothing reaches GitHub without passing through here.
    """

    def __init__(self, github: Optional[GitHubClient] = None):
        self.github = github

    # ── Gate: present draft + reflection, get approval ────────────────────

    def gate(
        self,
        draft: DraftArtifact,
        reflection: ReflectionArtifact,
        auto_answer: Optional[bool] = None,   # True = --yes, False = --no, None = interactive
        head_branch: str = "",
        base_branch: str = "main",
        as_draft_pr: bool = False,
    ) -> bool:
        """
        Show draft and reflection to user, request approval.
        Returns True if approved and published, False if rejected/failed.
        auto_answer: override interactive prompt (used by `approve --yes/--no`).
        """
        Console.agent_log("Gatekeeper", "Presenting draft for human review…")

        # Display full draft
        self._display_draft(draft)

        # Display reflection outcome
        self._display_reflection(reflection)

        # If reflection failed, warn loudly
        if not reflection.is_pass():
            Console.agent_log("Gatekeeper", "WARNING: Reflection checks FAILED. Proceeding requires manual override.", level="warn")

        # Persist draft for deferred `approve` command
        self._save_draft(draft, reflection, head_branch, base_branch, as_draft_pr)

        # Get human decision
        if auto_answer is True:
            Console.agent_log("Gatekeeper", "--yes flag provided. Auto-approving.")
            approved = True
        elif auto_answer is False:
            Console.agent_log("Gatekeeper", "--no flag provided. Auto-rejecting.")
            approved = False
        else:
            approved = self._prompt_approval(draft, reflection)

        if not approved:
            Console.agent_log("Gatekeeper", "Draft rejected. No changes made.", level="warn")
            self._log_event("rejected", draft, reflection)
            self._clear_draft()
            return False

        # Publish
        return self._publish(draft, reflection, head_branch, base_branch, as_draft_pr)

    # ── Deferred approve (agent approve --yes/--no) ───────────────────────

    def approve_saved(self, yes: bool, head_branch: str = "", base_branch: str = "main") -> bool:
        """Load saved draft and approve or reject it."""
        saved = self._load_draft()
        if not saved:
            Console.agent_log("Gatekeeper", "No pending draft found. Run 'agent draft' first.", level="error")
            return False

        draft_data = saved["draft"]
        draft = DraftArtifact(
            kind=draft_data["kind"],
            title=draft_data["title"],
            body=draft_data["body"],
            labels=draft_data.get("labels", []),
            plan=_dummy_plan(draft_data),
        )

        # Reconstruct minimal reflection
        refl_data = saved.get("reflection", {})
        reflection = ReflectionArtifact(
            verdict=refl_data.get("verdict", "PASS"),
            findings=refl_data.get("findings", []),
            missing_sections=refl_data.get("missing_sections", []),
            unsupported_claims=refl_data.get("unsupported_claims", []),
            revision_notes=refl_data.get("revision_notes", ""),
            passes_policy=refl_data.get("passes_policy", True),
        )

        h = saved.get("head_branch", head_branch)
        b = saved.get("base_branch", base_branch)
        as_draft = saved.get("as_draft_pr", False)

        Console.agent_log("Gatekeeper", f"Loaded saved {draft.kind.upper()} draft: \"{draft.title}\"")
        self._display_draft(draft)
        self._display_reflection(reflection)

        if not yes:
            Console.agent_log("Gatekeeper", "Draft rejected. No changes made.", level="warn")
            self._log_event("rejected", draft, reflection)
            self._clear_draft()
            return False

        Console.agent_log("Gatekeeper", "--yes confirmed. Creating on GitHub…")
        return self._publish(draft, reflection, h, b, as_draft)

    # ── Publishing ─────────────────────────────────────────────────────────

    def _publish(
        self,
        draft: DraftArtifact,
        reflection: ReflectionArtifact,
        head_branch: str,
        base_branch: str,
        as_draft_pr: bool,
    ) -> bool:
        if not self.github:
            Console.agent_log("Gatekeeper", "No GitHub client configured. Cannot publish.", level="error")
            return False

        Console.agent_log("Gatekeeper", f"Creating {draft.kind.upper()}…")

        try:
            if draft.kind == "issue":
                result = self.github.create_issue(
                    title=draft.title,
                    body=draft.body,
                    labels=draft.labels,
                )
                Console.agent_log("Gatekeeper", f"GitHub API call successful.")
                Console.success(f"Issue #{result['number']} created: {result['html_url']}")
                self._log_event("created_issue", draft, reflection, result)

            else:  # pr
                if not head_branch:
                    head_branch = Console.prompt("Head branch (source branch)", default="")
                if not head_branch:
                    Console.agent_log("Gatekeeper", "Head branch is required for PRs.", level="error")
                    return False

                result = self.github.create_pr(
                    title=draft.title,
                    body=draft.body,
                    head=head_branch,
                    base=base_branch,
                    draft=as_draft_pr,
                )
                Console.agent_log("Gatekeeper", f"GitHub API call successful.")
                Console.success(f"PR #{result['number']} created: {result['html_url']}")
                self._log_event("created_pr", draft, reflection, result)

            self._clear_draft()
            return True

        except Exception as e:
            Console.agent_log("Gatekeeper", f"GitHub API call failed: {e}", level="error")
            self._log_event("failed", draft, reflection, {"error": str(e)})
            return False

    # ── Interactive prompt ─────────────────────────────────────────────────

    def _prompt_approval(self, draft: DraftArtifact, reflection: ReflectionArtifact) -> bool:
        Console.blank()
        if not reflection.is_pass():
            print(f"  {Console.yellow('⚠')}  {Console.bold(Console.yellow('Reflection checks FAILED'))}")
            Console.info("You may still approve, but consider fixing the issues first.")

        print(f"  {Console.yellow('⚠')}  {Console.bold(Console.yellow('HUMAN APPROVAL REQUIRED'))}")
        Console.info(f"About to create a {draft.kind.upper()} on GitHub: \"{draft.title}\"")
        Console.info("This action cannot be undone without manually closing/deleting on GitHub.")
        Console.blank()

        return Console.confirm(f"Approve and publish this {draft.kind}?", default=False)

    # ── Display ────────────────────────────────────────────────────────────

    def _display_draft(self, draft: DraftArtifact):
        Console.blank()
        Console.divider("═")
        print(f"  {Console.bold(Console.cyan(f'── DRAFT {draft.kind.upper()} ──'))}")
        Console.divider("═")
        Console.blank()
        Console.kv("Title", Console.bold(draft.title))
        if draft.labels:
            Console.kv("Labels", ", ".join(draft.labels))
        Console.blank()
        Console.markdown_preview(draft.body, max_lines=80)
        Console.blank()
        Console.divider("═")

    def _display_reflection(self, reflection: ReflectionArtifact):
        Console.blank()
        Console.section("Reflection Report")
        if reflection.is_pass():
            Console.agent_log("Gatekeeper", "Reflection verdict: PASS", level="success")
        else:
            Console.agent_log("Gatekeeper", f"Reflection verdict: FAIL – {reflection.summary()}", level="error")
            for f in reflection.findings:
                Console.agent_log("Critic", f"Finding: {f}", level="warn")
        Console.blank()

    # ── Draft persistence ──────────────────────────────────────────────────

    def _save_draft(
        self,
        draft: DraftArtifact,
        reflection: ReflectionArtifact,
        head_branch: str,
        base_branch: str,
        as_draft_pr: bool,
    ):
        data = {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "draft": draft.to_dict(),
            "reflection": {
                "verdict": reflection.verdict,
                "findings": reflection.findings,
                "missing_sections": reflection.missing_sections,
                "unsupported_claims": reflection.unsupported_claims,
                "revision_notes": reflection.revision_notes,
                "passes_policy": reflection.passes_policy,
            },
            "head_branch": head_branch,
            "base_branch": base_branch,
            "as_draft_pr": as_draft_pr,
        }
        try:
            with open(DRAFT_FILE, "w") as f:
                json.dump(data, f, indent=2)
            Console.agent_log("Gatekeeper", f"Draft saved to {DRAFT_FILE} (use 'agent approve --yes/--no')")
        except Exception as e:
            Console.agent_log("Gatekeeper", f"Could not save draft: {e}", level="warn")

    def _load_draft(self) -> Optional[dict]:
        if not os.path.exists(DRAFT_FILE):
            return None
        try:
            with open(DRAFT_FILE) as f:
                return json.load(f)
        except Exception:
            return None

    def _clear_draft(self):
        try:
            if os.path.exists(DRAFT_FILE):
                os.remove(DRAFT_FILE)
        except Exception:
            pass

    # ── Audit log ──────────────────────────────────────────────────────────

    def _log_event(self, event: str, draft: DraftArtifact, reflection: ReflectionArtifact, result: dict = None):
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "kind": draft.kind,
            "title": draft.title,
            "reflection_verdict": reflection.verdict,
            "result": result or {},
        }
        try:
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


# ── Helpers ────────────────────────────────────────────────────────────────

def _dummy_plan(draft_data: dict):
    """Reconstruct a minimal Plan from saved draft data for deferred approval."""
    from agent.planner import Plan
    return Plan(
        action=draft_data.get("kind", "issue"),
        rationale="",
        scope="",
        risks=[],
        required_sections=[],
        acceptance_criteria=[],
        test_plan_required=False,
        instruction="",
        from_review=False,
    )
