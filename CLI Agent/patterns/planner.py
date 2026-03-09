"""
PlannerAgent — Planning Pattern

Runs BEFORE any draft is created. Responsible for:
  - Validating scope (does the diff/instruction warrant action?)
  - Deciding action type: issue / pr / no_action
  - Producing a structured Plan that drives downstream agents
  - Emitting [Planner] tagged log lines

The Plan is a data artifact passed to Writer and Gatekeeper.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from utils.ollama import OllamaClient
from utils.git import GitClient
from utils.console import Console
from prompts.templates import planning_prompt, instruction_planning_prompt


@dataclass
class Plan:
    """Structured planning artifact produced by PlannerAgent."""
    action: str                          # "issue" | "pr" | "no_action"
    rationale: str                       # Why this action was chosen
    scope: str                           # What files/areas are in scope
    risks: List[str]                     # Identified risks
    required_sections: List[str]         # Sections the Writer MUST include
    acceptance_criteria: List[str]       # For issues: what done looks like
    test_plan_required: bool             # Whether a test plan is mandatory
    instruction: str                     # Original user instruction (if explicit)
    from_review: bool                    # True if derived from ReviewResult
    review_category: str = ""           # Carried from ReviewResult
    review_risk: str = ""               # Carried from ReviewResult
    suggested_title: str = ""           # Seed title for Writer
    raw: dict = field(default_factory=dict)

    def is_valid(self) -> bool:
        return self.action in ("issue", "pr")


class PlannerAgent:
    """
    Multi-agent role: Planner
    Runs first. Validates scope, decides action, emits structured Plan.
    """

    def __init__(self, ollama: OllamaClient, git: Optional[GitClient] = None):
        self.ollama = ollama
        self.git = git

    # ── Plan from ReviewResult (Task 1 → Task 2 flow) ─────────────────────

    def plan_from_review(self, review_result) -> Optional[Plan]:
        """Build a Plan from an existing ReviewResult (code review output)."""
        Console.agent_log("Planner", "Building plan from review result…")

        action = review_result.recommendation
        if action == "no_action":
            Console.agent_log("Planner", "Review recommends no action. Scope: nothing to draft.")
            return Plan(
                action="no_action",
                rationale=review_result.justification,
                scope="",
                risks=[],
                required_sections=[],
                acceptance_criteria=[],
                test_plan_required=False,
                instruction="",
                from_review=True,
                review_category=review_result.category,
                review_risk=review_result.risk,
                suggested_title=review_result.suggested_title,
            )

        # Use AI to build a fuller plan
        prompt = planning_prompt(
            action=action,
            category=review_result.category,
            risk=review_result.risk,
            risk_reason=review_result.risk_reason,
            summary=review_result.summary,
            issues=review_result.issues,
            improvements=review_result.improvements,
            diff_snippet=review_result.diff[:3000],
            files=[f.path for f in review_result.files],
        )

        try:
            raw = self.ollama.generate_json(prompt)
        except Exception as e:
            Console.agent_log("Planner", f"AI planning failed, using fallback: {e}", level="warn")
            raw = {}

        plan = self._build_plan(raw, action=action, from_review=True, review_result=review_result)
        self._display_plan(plan)
        return plan

    # ── Plan from explicit instruction (Task 2 direct) ────────────────────

    def plan_from_instruction(self, instruction: str, kind: str, diff: str = "", files: list = None) -> Optional[Plan]:
        """Build a Plan from explicit user instruction like 'Add rate limiting to login endpoint'."""
        Console.agent_log("Planner", f"Planning from explicit instruction: \"{instruction}\"")

        prompt = instruction_planning_prompt(
            instruction=instruction,
            kind=kind,
            diff_snippet=diff[:3000] if diff else "",
            files=files or [],
        )

        try:
            raw = self.ollama.generate_json(prompt)
        except Exception as e:
            Console.agent_log("Planner", f"AI planning failed, using fallback: {e}", level="warn")
            raw = {}

        plan = self._build_plan(raw, action=kind, from_review=False, instruction=instruction)
        self._display_plan(plan)
        return plan

    # ── Internal ───────────────────────────────────────────────────────────

    def _build_plan(
        self,
        raw: dict,
        action: str,
        from_review: bool,
        review_result=None,
        instruction: str = "",
    ) -> Plan:
        # Determine required sections based on action type
        if action in ("create_issue", "issue"):
            required = raw.get("required_sections") or [
                "Title", "Problem description", "Evidence", "Acceptance criteria", "Risk level"
            ]
        else:
            required = raw.get("required_sections") or [
                "Title", "Summary", "Files affected", "Behavior change", "Test plan", "Risk level"
            ]

        return Plan(
            action="issue" if action in ("create_issue", "issue") else "pr",
            rationale=raw.get("rationale") or (review_result.justification if review_result else instruction),
            scope=raw.get("scope") or self._infer_scope(review_result),
            risks=raw.get("risks") or (
                [review_result.risk_reason] if review_result else []
            ),
            required_sections=required,
            acceptance_criteria=raw.get("acceptance_criteria") or [],
            test_plan_required=raw.get("test_plan_required", action in ("create_pr", "pr")),
            instruction=instruction,
            from_review=from_review,
            review_category=review_result.category if review_result else "",
            review_risk=review_result.risk if review_result else raw.get("risk", "medium"),
            suggested_title=raw.get("suggested_title") or (
                review_result.suggested_title if review_result else instruction[:60]
            ),
            raw=raw,
        )

    def _infer_scope(self, review_result) -> str:
        if not review_result:
            return "unknown"
        files = [f.path for f in (review_result.files or [])]
        if not files:
            return "no files detected"
        return ", ".join(files[:5]) + ("…" if len(files) > 5 else "")

    def _display_plan(self, plan: Plan):
        if plan.action == "no_action":
            Console.agent_log("Planner", "No action warranted by current changes.")
            return

        Console.agent_log("Planner", f"Scope validated. Action: {plan.action.upper()}")
        Console.agent_log("Planner", f"Rationale: {plan.rationale[:120]}")
        Console.agent_log("Planner", f"Scope: {plan.scope[:100]}")
        Console.agent_log("Planner", f"Required sections: {', '.join(plan.required_sections)}")
        if plan.risks:
            for r in plan.risks:
                Console.agent_log("Planner", f"Risk identified: {r[:100]}", level="warn")
        if plan.acceptance_criteria:
            Console.agent_log("Planner", f"Acceptance criteria: {len(plan.acceptance_criteria)} defined")
        if plan.test_plan_required:
            Console.agent_log("Planner", "Test plan is REQUIRED for this draft.", level="warn")
