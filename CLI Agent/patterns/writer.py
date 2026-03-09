"""
WriterAgent — Multi-agent role: Writer

Responsible for drafting Issue and PR content.
Operates AFTER the Planner has validated scope and produced a Plan.
Produces a DraftArtifact consumed by CriticAgent and GatekeeperAgent.
"""

from dataclasses import dataclass
from typing import Optional
from utils.ollama import OllamaClient
from utils.console import Console
from prompts.templates import (
    issue_draft_from_plan_prompt,
    pr_draft_from_plan_prompt,
)
from patterns.planner import Plan


@dataclass
class DraftArtifact:
    """Output produced by WriterAgent. Passed to Critic and Gatekeeper."""
    kind: str          # "issue" | "pr"
    title: str
    body: str
    labels: list
    plan: Plan         # The Plan that drove this draft

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "labels": self.labels,
        }


class WriterAgent:
    """
    Multi-agent role: Writer
    Generates structured Issue/PR drafts following the Planner's Plan.
    Emits [Writer] tagged log lines.
    """

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama

    def draft(self, plan: Plan, review_result=None, max_attempts: int = 2) -> Optional[DraftArtifact]:
        """Generate a draft following the plan. Returns DraftArtifact."""
        Console.agent_log("Writer", f"Drafting {plan.action.upper()} from plan…")
        Console.agent_log("Writer", f"Required sections: {', '.join(plan.required_sections)}")

        if plan.action == "issue":
            return self._draft_issue(plan, review_result, max_attempts)
        elif plan.action == "pr":
            return self._draft_pr(plan, review_result, max_attempts)
        else:
            Console.agent_log("Writer", "Plan action is no_action — nothing to draft.", level="warn")
            return None

    def redraft(self, plan: Plan, draft: DraftArtifact, reflection_notes: str, review_result=None) -> Optional[DraftArtifact]:
        """Revise an existing draft based on Critic feedback."""
        Console.agent_log("Writer", "Revising draft based on Critic feedback…")
        Console.agent_log("Writer", f"Reflection notes: {reflection_notes[:120]}")

        # Append reflection notes as revision instructions
        revision_plan = Plan(
            action=plan.action,
            rationale=plan.rationale,
            scope=plan.scope,
            risks=plan.risks,
            required_sections=plan.required_sections,
            acceptance_criteria=plan.acceptance_criteria,
            test_plan_required=plan.test_plan_required,
            instruction=plan.instruction + f"\n\nRevision required. Fix these issues:\n{reflection_notes}",
            from_review=plan.from_review,
            review_category=plan.review_category,
            review_risk=plan.review_risk,
            suggested_title=draft.title,
        )
        return self.draft(revision_plan, review_result)

    # ── Issue drafting ─────────────────────────────────────────────────────

    def _draft_issue(self, plan: Plan, review_result, max_attempts: int) -> Optional[DraftArtifact]:
        for attempt in range(max_attempts):
            if attempt > 0:
                Console.agent_log("Writer", f"Retry attempt {attempt + 1}…")

            prompt = issue_draft_from_plan_prompt(
                plan=plan,
                review_result=review_result,
            )

            try:
                body = self.ollama.generate(prompt, temperature=0.3, max_tokens=1800)
            except Exception as e:
                Console.agent_log("Writer", f"Generation failed: {e}", level="error")
                return None

            title = plan.suggested_title or "Untitled Issue"
            # Let AI suggest a title if embedded in body
            for line in body.splitlines()[:3]:
                if line.startswith("TITLE:"):
                    title = line.replace("TITLE:", "").strip()
                    body = body[body.index(line) + len(line):].lstrip("\n")
                    break

            labels = _infer_labels(plan, "issue")
            draft = DraftArtifact(kind="issue", title=title, body=body, labels=labels, plan=plan)
            Console.agent_log("Writer", f"Draft issue created: \"{title}\"")
            return draft

        return None

    # ── PR drafting ────────────────────────────────────────────────────────

    def _draft_pr(self, plan: Plan, review_result, max_attempts: int) -> Optional[DraftArtifact]:
        for attempt in range(max_attempts):
            if attempt > 0:
                Console.agent_log("Writer", f"Retry attempt {attempt + 1}…")

            prompt = pr_draft_from_plan_prompt(
                plan=plan,
                review_result=review_result,
            )

            try:
                body = self.ollama.generate(prompt, temperature=0.3, max_tokens=1800)
            except Exception as e:
                Console.agent_log("Writer", f"Generation failed: {e}", level="error")
                return None

            title = plan.suggested_title or "Untitled PR"
            for line in body.splitlines()[:3]:
                if line.startswith("TITLE:"):
                    title = line.replace("TITLE:", "").strip()
                    body = body[body.index(line) + len(line):].lstrip("\n")
                    break

            labels = _infer_labels(plan, "pr")
            draft = DraftArtifact(kind="pr", title=title, body=body, labels=labels, plan=plan)
            Console.agent_log("Writer", f"Draft PR created: \"{title}\"")
            return draft

        return None


def _infer_labels(plan: Plan, kind: str) -> list:
    labels = []
    cat = plan.review_category.lower()
    if cat == "bugfix":     labels.append("bug")
    if cat == "feature":    labels.append("enhancement")
    if cat == "security":   labels.extend(["bug", "security"])
    if cat == "docs":       labels.append("documentation")
    if cat == "refactor":   labels.append("refactor")
    if kind == "pr":        labels.append("pull-request")
    if plan.review_risk == "high": labels.append("priority: high")
    return list(dict.fromkeys(labels))  # dedup, preserve order
