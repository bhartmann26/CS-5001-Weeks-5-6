"""
A2A Critic Agent Server — reflects on draft quality (Reflection pattern).

Accepts tasks:
  - "reflect": analyze a draft against its plan, return ReflectionArtifact

Performs both structural policy checks and AI-based reflection.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_a2a import A2AServer, skill, agent, run_server, TaskStatus, TaskState
from utils.ollama import OllamaClient
from prompts.templates import reflection_prompt


@agent(
    name="Critic Agent",
    description="Reflects on draft quality — checks evidence, sections, test plans, and policy violations.",
    version="2.0.0",
)
class CriticAgentServer(A2AServer):

    def __init__(self, ollama: OllamaClient = None):
        port = int(os.environ.get("CRITIC_PORT", "5004"))
        super().__init__(url=f"http://localhost:{port}")
        self.ollama = ollama or OllamaClient()

    @skill(
        name="Reflect on Draft",
        description="Check draft for unsupported claims, missing sections, vague language, policy violations",
        tags=["reflection", "quality", "review"],
    )
    def reflect(self, draft, plan):
        """Reflect on draft quality."""
        pass

    def handle_task(self, task):
        message_data = task.message or {}
        content = message_data.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)

        try:
            params = json.loads(text) if text else {}
            draft = params.get("draft", {})
            plan = params.get("plan", {})

            # ── 1. Policy checks (no AI needed) ──────────────────────────
            policy_failures = self._policy_check(draft)
            if policy_failures:
                artifact = {
                    "verdict": "FAIL",
                    "findings": policy_failures,
                    "missing_sections": [],
                    "unsupported_claims": [],
                    "revision_notes": "\n".join(f"- Fix: {p}" for p in policy_failures),
                    "passes_policy": False,
                }
                result_json = json.dumps(artifact)
                task.artifacts = [{"parts": [{"type": "text", "text": result_json}]}]
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message={"role": "agent", "content": {"type": "text", "text": result_json}}
                )
                return task

            # ── 2. Section presence check ─────────────────────────────────
            missing = self._check_sections(draft, plan)

            # ── 3. AI reflection ──────────────────────────────────────────
            prompt = reflection_prompt(
                draft_title=draft.get("title", ""),
                draft_body=draft.get("body", ""),
                plan_action=plan.get("action", "issue"),
                required_sections=plan.get("required_sections", []),
                missing_sections=missing,
                test_plan_required=plan.get("test_plan_required", False),
                acceptance_criteria=plan.get("acceptance_criteria", []),
                review_risk=plan.get("review_risk", "medium"),
            )

            try:
                raw = self.ollama.generate_json(prompt)
            except Exception:
                raw = {}

            # ── 4. Build artifact ─────────────────────────────────────────
            ai_findings = raw.get("findings", [])
            ai_unsupported = raw.get("unsupported_claims", [])
            ai_verdict = raw.get("verdict", "PASS" if not missing else "FAIL")
            ai_notes = raw.get("revision_notes", "")

            all_findings = missing + ai_findings
            verdict = "FAIL" if (missing or ai_verdict == "FAIL") else "PASS"

            revision_parts = []
            if missing:
                revision_parts.append(f"Add missing sections: {', '.join(missing)}")
            if ai_notes:
                revision_parts.append(ai_notes)
            if ai_unsupported:
                revision_parts.append(f"Support these claims with evidence: {'; '.join(ai_unsupported[:3])}")

            artifact = {
                "verdict": verdict,
                "findings": all_findings,
                "missing_sections": missing,
                "unsupported_claims": ai_unsupported,
                "revision_notes": "\n".join(revision_parts),
                "passes_policy": True,
            }

            result_json = json.dumps(artifact)
            task.artifacts = [{"parts": [{"type": "text", "text": result_json}]}]
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                message={"role": "agent", "content": {"type": "text", "text": result_json}}
            )

        except Exception as e:
            error_json = json.dumps({"error": str(e), "verdict": "FAIL", "findings": [str(e)]})
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"type": "text", "text": error_json}},
            )

        return task

    @staticmethod
    def _policy_check(draft: dict) -> list:
        failures = []
        title = draft.get("title", "")
        body = draft.get("body", "")
        if not title or len(title.strip()) < 5:
            failures.append("Title is empty or too short (minimum 5 characters)")
        if not body or len(body.strip()) < 50:
            failures.append("Body is empty or too short (minimum 50 characters)")
        if title.strip().lower() in ("untitled issue", "untitled pr", "untitled"):
            failures.append("Title must not be a placeholder")
        return failures

    @staticmethod
    def _check_sections(draft: dict, plan: dict) -> list:
        body_lower = draft.get("body", "").lower()
        missing = []
        section_keywords = {
            "title": [],
            "problem description": ["problem", "issue", "bug", "error", "fail"],
            "evidence": ["evidence", "example", "code", "file", "line", "diff", "```"],
            "acceptance criteria": ["acceptance criteria", "done when", "criteria", "- [ ]"],
            "risk level": ["risk", "impact", "severity", "danger"],
            "summary": ["summary", "overview", "description", "this pr", "this change"],
            "files affected": ["files", "changed", "modified", "affected"],
            "behavior change": ["behavior", "behaviour", "change", "before", "after"],
            "test plan": ["test", "testing", "pytest", "unittest", "spec", "coverage"],
        }

        for section in plan.get("required_sections", []):
            section_key = section.lower()
            if section_key == "title":
                continue
            keywords = section_keywords.get(section_key, [section_key])
            found = any(kw in body_lower for kw in keywords)
            if not found:
                missing.append(section)

        return missing


if __name__ == "__main__":
    port = int(os.environ.get("CRITIC_PORT", "5004"))
    server = CriticAgentServer()
    print(f"[A2A] Critic Agent starting on port {port}")
    run_server(server, port=port)
