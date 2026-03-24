"""
A2A Planner Agent Server — validates scope and produces structured Plans.

Accepts tasks:
  - "plan_from_review": build plan from a ReviewResult JSON
  - "plan_from_instruction": build plan from explicit user instruction

Uses Ollama for AI planning.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_a2a import A2AServer, skill, agent, run_server, TaskStatus, TaskState
from utils.ollama import OllamaClient
from prompts.templates import planning_prompt, instruction_planning_prompt, json_sections


@agent(
    name="Planner Agent",
    description="Validates scope, decides action type (issue/pr/no_action), and produces structured Plans.",
    version="2.0.0",
)
class PlannerAgentServer(A2AServer):

<<<<<<< HEAD
    def __init__(self, ollama: OllamaClient = None, url: str = None, **kwargs):
        if url:
            kwargs['url'] = url
        super().__init__(**kwargs)
=======
    def __init__(self, ollama: OllamaClient = None):
        port = int(os.environ.get("PLANNER_PORT", "5002"))
        super().__init__(url=f"http://localhost:{port}")
>>>>>>> a85e6e12bfdc907914c9af95aec89666dd0a6c03
        self.ollama = ollama or OllamaClient()

    @skill(
        name="Plan from Review",
        description="Build a structured Plan from a code review result",
        tags=["planning", "review"],
    )
    def plan_from_review(self, review_result):
        """Build plan from review result."""
        pass

    @skill(
        name="Plan from Instruction",
        description="Build a structured Plan from explicit user instruction",
        tags=["planning", "instruction"],
    )
    def plan_from_instruction(self, instruction, kind):
        """Build plan from instruction."""
        pass

    def handle_task(self, task):
        message_data = task.message or {}
        content = message_data.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)

        try:
            params = json.loads(text) if text else {}

            if "review_result" in params:
                plan = self._plan_from_review(params["review_result"])
            elif "instruction" in params:
                plan = self._plan_from_instruction(
                    instruction=params["instruction"],
                    kind=params.get("kind", "issue"),
                    diff=params.get("diff", ""),
                    files=params.get("files", []),
                )
            else:
                task.status = TaskStatus(
                    state=TaskState.INPUT_REQUIRED,
                    message={"role": "agent", "content": {"type": "text", "text": "Provide review_result or instruction"}},
                )
                return task

            result_json = json.dumps(plan)
            task.artifacts = [{"parts": [{"type": "text", "text": result_json}]}]
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                message={"role": "agent", "content": {"type": "text", "text": result_json}},
            )

        except Exception as e:
            error_json = json.dumps({"error": str(e), "action": "no_action"})
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"type": "text", "text": error_json}},
            )

        return task

    def _plan_from_review(self, review: dict) -> dict:
        action = review.get("recommendation", "no_action")
        if action == "no_action":
            return {"action": "no_action", "rationale": review.get("justification", "")}

        prompt = planning_prompt(
            action=action,
            category=review.get("category", ""),
            risk=review.get("risk", ""),
            risk_reason=review.get("risk_reason", ""),
            summary=review.get("summary", ""),
            issues=review.get("issues", []),
            improvements=review.get("improvements", []),
            diff_snippet=review.get("diff", "")[:3000],
            files=[f["path"] if isinstance(f, dict) else f for f in review.get("files", [])],
        )

        try:
            raw = self.ollama.generate_json(prompt)
        except Exception:
            raw = {}

        kind = "issue" if action in ("create_issue", "issue") else "pr"
        return self._build_plan_dict(raw, kind, from_review=True, review=review)

    def _plan_from_instruction(self, instruction: str, kind: str, diff: str = "", files: list = None) -> dict:
        prompt = instruction_planning_prompt(
            instruction=instruction,
            kind=kind,
            diff_snippet=diff[:3000],
            files=files or [],
        )

        try:
            raw = self.ollama.generate_json(prompt)
        except Exception:
            raw = {}

        return self._build_plan_dict(raw, kind, from_review=False, instruction=instruction)

    def _build_plan_dict(self, raw: dict, kind: str, from_review: bool, review: dict = None, instruction: str = "") -> dict:
        if kind in ("create_issue", "issue"):
            required = raw.get("required_sections") or [
                "Title", "Problem description", "Evidence", "Acceptance criteria", "Risk level"
            ]
            action = "issue"
        else:
            required = raw.get("required_sections") or [
                "Title", "Summary", "Files affected", "Behavior change", "Test plan", "Risk level"
            ]
            action = "pr"

        return {
            "action": action,
            "rationale": raw.get("rationale") or (review.get("justification", "") if review else instruction),
            "scope": raw.get("scope") or "",
            "risks": raw.get("risks") or ([review.get("risk_reason", "")] if review else []),
            "required_sections": required,
            "acceptance_criteria": raw.get("acceptance_criteria") or [],
            "test_plan_required": raw.get("test_plan_required", action == "pr"),
            "instruction": instruction,
            "from_review": from_review,
            "review_category": review.get("category", "") if review else "",
            "review_risk": review.get("risk", "") if review else raw.get("risk", "medium"),
            "suggested_title": raw.get("suggested_title") or (
                review.get("suggested_title", "") if review else instruction[:60]
            ),
        }


if __name__ == "__main__":
    port = int(os.environ.get("PLANNER_PORT", "5002"))
    url = f"http://localhost:{port}"
    server = PlannerAgentServer(url=url)
    print(f"[A2A] Planner Agent starting on port {port}")
    run_server(server, port=port)
