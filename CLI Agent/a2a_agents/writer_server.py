"""
A2A Writer Agent Server — drafts Issue and PR content.

Accepts tasks:
  - "draft": generate a draft from a Plan
  - "redraft": revise a draft based on critic feedback

Uses Ollama for AI text generation.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_a2a import A2AServer, skill, agent, run_server, TaskStatus, TaskState
from utils.ollama import OllamaClient
from prompts.templates import issue_draft_from_plan_prompt, pr_draft_from_plan_prompt
from patterns.planner import Plan


@agent(
    name="Writer Agent",
    description="Drafts Issue and PR content following structured Plans from the Planner.",
    version="2.0.0",
)
class WriterAgentServer(A2AServer):

    def __init__(self, ollama: OllamaClient = None):
        super().__init__()
        self.ollama = ollama or OllamaClient()

    @skill(
        name="Draft Content",
        description="Generate issue or PR draft from a plan",
        tags=["writing", "draft"],
    )
    def draft(self, plan, review_result=None):
        """Generate draft content."""
        pass

    @skill(
        name="Redraft Content",
        description="Revise a draft based on critic feedback",
        tags=["writing", "revision"],
    )
    def redraft(self, plan, draft, reflection_notes):
        """Revise draft based on feedback."""
        pass

    def handle_task(self, task):
        message_data = task.message or {}
        content = message_data.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)

        try:
            params = json.loads(text) if text else {}
            plan_dict = params.get("plan", {})
            review_dict = params.get("review_result")
            reflection_notes = params.get("reflection_notes", "")

            # Reconstruct Plan object for prompt templates
            plan = self._dict_to_plan(plan_dict)

            # If reflection_notes present, this is a redraft
            if reflection_notes:
                plan = Plan(
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
                    suggested_title=plan.suggested_title,
                )

            # Build a mock review_result object for prompts
            review_obj = _MockReview(review_dict) if review_dict else None

            if plan.action == "issue":
                draft_result = self._draft_issue(plan, review_obj)
            elif plan.action == "pr":
                draft_result = self._draft_pr(plan, review_obj)
            else:
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message={"role": "agent", "content": {"type": "text", "text": "No action needed"}},
                )
                return task

            task.artifacts = [{"parts": [{"type": "text", "text": json.dumps(draft_result)}]}]
            task.status = TaskStatus(state=TaskState.COMPLETED)

        except Exception as e:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"type": "text", "text": f"Writing failed: {e}"}},
            )

        return task

    def _draft_issue(self, plan: Plan, review_obj) -> dict:
        prompt = issue_draft_from_plan_prompt(plan=plan, review_result=review_obj)
        body = self.ollama.generate(prompt, temperature=0.3, max_tokens=1800)

        title = plan.suggested_title or "Untitled Issue"
        for line in body.splitlines()[:3]:
            if line.startswith("TITLE:"):
                title = line.replace("TITLE:", "").strip()
                body = body[body.index(line) + len(line):].lstrip("\n")
                break

        labels = self._infer_labels(plan, "issue")
        return {"kind": "issue", "title": title, "body": body, "labels": labels}

    def _draft_pr(self, plan: Plan, review_obj) -> dict:
        prompt = pr_draft_from_plan_prompt(plan=plan, review_result=review_obj)
        body = self.ollama.generate(prompt, temperature=0.3, max_tokens=1800)

        title = plan.suggested_title or "Untitled PR"
        for line in body.splitlines()[:3]:
            if line.startswith("TITLE:"):
                title = line.replace("TITLE:", "").strip()
                body = body[body.index(line) + len(line):].lstrip("\n")
                break

        labels = self._infer_labels(plan, "pr")
        return {"kind": "pr", "title": title, "body": body, "labels": labels}

    @staticmethod
    def _infer_labels(plan: Plan, kind: str) -> list:
        labels = []
        cat = plan.review_category.lower()
        if cat == "bugfix": labels.append("bug")
        if cat == "feature": labels.append("enhancement")
        if cat == "security": labels.extend(["bug", "security"])
        if cat == "docs": labels.append("documentation")
        if cat == "refactor": labels.append("refactor")
        if kind == "pr": labels.append("pull-request")
        if plan.review_risk == "high": labels.append("priority: high")
        return list(dict.fromkeys(labels))

    @staticmethod
    def _dict_to_plan(d: dict) -> Plan:
        return Plan(
            action=d.get("action", "issue"),
            rationale=d.get("rationale", ""),
            scope=d.get("scope", ""),
            risks=d.get("risks", []),
            required_sections=d.get("required_sections", []),
            acceptance_criteria=d.get("acceptance_criteria", []),
            test_plan_required=d.get("test_plan_required", False),
            instruction=d.get("instruction", ""),
            from_review=d.get("from_review", False),
            review_category=d.get("review_category", ""),
            review_risk=d.get("review_risk", ""),
            suggested_title=d.get("suggested_title", ""),
        )


class _MockReview:
    """Lightweight stand-in for ReviewResult, used by prompt templates."""
    def __init__(self, data: dict):
        self.diff = data.get("diff", "")
        self.issues = data.get("issues", [])
        self.files = [_MockFile(f) for f in data.get("files", [])]


class _MockFile:
    def __init__(self, data):
        if isinstance(data, dict):
            self.path = data.get("path", "")
        else:
            self.path = str(data)


if __name__ == "__main__":
    port = int(os.environ.get("WRITER_PORT", "5003"))
    server = WriterAgentServer()
    print(f"[A2A] Writer Agent starting on port {port}")
    run_server(server, port=port)
