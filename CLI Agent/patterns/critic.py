"""
CriticAgent — Reflection Pattern

Runs AFTER the Writer produces a draft. Acts as a quality gate.
Checks for:
  - Unsupported claims (statements without evidence)
  - Missing required sections (from Plan)
  - Missing test plan (for PRs)
  - Vague language
  - Policy violations (empty body, no title, etc.)
  - Missing acceptance criteria (for issues)

Produces a ReflectionArtifact with:
  - verdict: PASS | FAIL
  - findings: list of specific problems found
  - missing_sections: sections required by Plan but absent in draft
  - revision_notes: actionable guidance for the Writer to fix

Emits [Gatekeeper] tagged lines for verdict announcement (shared role).
"""

from dataclasses import dataclass, field
from typing import List
from utils.ollama import OllamaClient
from utils.console import Console
from patterns.writer import DraftArtifact
from patterns.planner import Plan
from prompts.templates import reflection_prompt


@dataclass
class ReflectionArtifact:
    """Output of CriticAgent. Consumed by GatekeeperAgent."""
    verdict: str                         # "PASS" | "FAIL"
    findings: List[str]                  # Specific problems found
    missing_sections: List[str]          # Sections in Plan but absent in draft
    unsupported_claims: List[str]        # Claims without evidence
    revision_notes: str                  # Actionable guidance for Writer
    passes_policy: bool                  # Hard policy check (no empty body etc.)
    raw: dict = field(default_factory=dict)

    def is_pass(self) -> bool:
        return self.verdict == "PASS" and self.passes_policy

    def summary(self) -> str:
        if self.is_pass():
            return "All checks passed."
        parts = []
        if self.missing_sections:
            parts.append(f"Missing sections: {', '.join(self.missing_sections)}")
        if self.unsupported_claims:
            parts.append(f"Unsupported claims: {len(self.unsupported_claims)}")
        if self.findings:
            parts.append(f"Issues: {'; '.join(self.findings[:2])}")
        return " | ".join(parts) or "Draft failed quality checks."


class CriticAgent:
    """
    Multi-agent role: Critic (implements Reflection pattern)
    Reviews the WriterAgent's draft against the Plan.
    """

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama

    def reflect(self, draft: DraftArtifact, plan: Plan) -> ReflectionArtifact:
        """Analyze the draft and return a ReflectionArtifact."""
        Console.agent_log("Critic", f"Reflecting on {draft.kind.upper()} draft: \"{draft.title}\"")

        # ── 1. Hard policy checks (no AI needed) ──────────────────────────
        policy_failures = self._policy_check(draft)
        if policy_failures:
            for f in policy_failures:
                Console.agent_log("Critic", f"Policy violation: {f}", level="error")
            artifact = ReflectionArtifact(
                verdict="FAIL",
                findings=policy_failures,
                missing_sections=[],
                unsupported_claims=[],
                revision_notes="\n".join(f"- Fix: {p}" for p in policy_failures),
                passes_policy=False,
            )
            self._display_verdict(artifact)
            return artifact

        # ── 2. Section presence check ──────────────────────────────────────
        missing = self._check_sections(draft, plan)
        if missing:
            for s in missing:
                Console.agent_log("Critic", f"Missing required section: {s}", level="warn")

        # ── 3. AI reflection ───────────────────────────────────────────────
        Console.agent_log("Critic", "Running AI reflection check…")
        prompt = reflection_prompt(
            draft_title=draft.title,
            draft_body=draft.body,
            plan_action=plan.action,
            required_sections=plan.required_sections,
            missing_sections=missing,
            test_plan_required=plan.test_plan_required,
            acceptance_criteria=plan.acceptance_criteria,
            review_risk=plan.review_risk,
        )

        try:
            raw = self.ollama.generate_json(prompt)
        except Exception as e:
            Console.agent_log("Critic", f"AI reflection failed, using structural check only: {e}", level="warn")
            raw = {}

        # ── 4. Build artifact ──────────────────────────────────────────────
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

        artifact = ReflectionArtifact(
            verdict=verdict,
            findings=all_findings,
            missing_sections=missing,
            unsupported_claims=ai_unsupported,
            revision_notes="\n".join(revision_parts),
            passes_policy=True,
            raw=raw,
        )

        self._display_verdict(artifact)
        return artifact

    # ── Structural checks (no AI) ──────────────────────────────────────────

    def _policy_check(self, draft: DraftArtifact) -> list:
        failures = []
        if not draft.title or len(draft.title.strip()) < 5:
            failures.append("Title is empty or too short (minimum 5 characters)")
        if not draft.body or len(draft.body.strip()) < 50:
            failures.append("Body is empty or too short (minimum 50 characters)")
        if draft.title.strip().lower() in ("untitled issue", "untitled pr", "untitled"):
            failures.append("Title must not be a placeholder")
        return failures

    def _check_sections(self, draft: DraftArtifact, plan: Plan) -> list:
        """Check that required sections from the Plan appear in the draft body."""
        body_lower = draft.body.lower()
        missing = []
        # Map required section names to keywords to look for
        section_keywords = {
            "title": [],  # already checked separately
            "problem description": ["problem", "issue", "bug", "error", "fail"],
            "evidence": ["evidence", "example", "code", "file", "line", "diff", "```"],
            "acceptance criteria": ["acceptance criteria", "done when", "criteria", "- [ ]"],
            "risk level": ["risk", "impact", "severity", "danger"],
            "summary": ["summary", "overview", "description", "this pr", "this change"],
            "files affected": ["files", "changed", "modified", "affected"],
            "behavior change": ["behavior", "behaviour", "change", "before", "after"],
            "test plan": ["test", "testing", "pytest", "unittest", "spec", "coverage"],
        }

        for section in plan.required_sections:
            section_key = section.lower()
            if section_key == "title":
                continue
            keywords = section_keywords.get(section_key, [section_key])
            found = any(kw in body_lower for kw in keywords)
            if not found:
                missing.append(section)

        return missing

    def _display_verdict(self, artifact: ReflectionArtifact):
        if artifact.is_pass():
            Console.agent_log("Gatekeeper", "Reflection verdict: PASS", level="success")
        else:
            Console.agent_log("Gatekeeper", f"Reflection verdict: FAIL – {artifact.summary()}", level="error")
            if artifact.missing_sections:
                for s in artifact.missing_sections:
                    Console.agent_log("Critic", f"Missing: {s}", level="warn")
            if artifact.unsupported_claims:
                for c in artifact.unsupported_claims[:3]:
                    Console.agent_log("Critic", f"Unsupported claim: {c[:100]}", level="warn")
            if artifact.revision_notes:
                Console.agent_log("Critic", f"Revision required: {artifact.revision_notes[:200]}")
