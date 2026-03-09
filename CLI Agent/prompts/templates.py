"""
Prompt templates for all AI operations.
Centralized here to make tuning easy.
"""


def analysis_prompt(diff: str, files_summary: str, branch: str, recent_commits: str) -> str:
    return f"""You are a senior software engineer performing a thorough code review.
Analyze the git diff below and return ONLY a valid JSON object — no markdown, no explanation, no preamble.

Branch: {branch}

Recent commits:
{recent_commits}

Files changed:
{files_summary}

Diff (may be truncated):
{diff[:7000]}

Return this EXACT JSON schema (all fields required):
{{
  "category": "<feature|bugfix|refactor|docs|test|chore|security|performance>",
  "risk": "<low|medium|high>",
  "risk_reason": "<one sentence justifying the risk level with specific evidence from the diff>",
  "summary": "<2-3 sentences describing what changed and why it matters>",
  "issues": [
    {{
      "severity": "<critical|warning|info>",
      "file": "<filename>",
      "line_hint": "<approximate line or function name from diff, or empty string>",
      "description": "<what the issue is>",
      "suggestion": "<concrete fix or improvement>",
      "evidence": "<quote or paraphrase of the specific diff line(s) that show this issue>"
    }}
  ],
  "improvements": [
    {{
      "type": "<performance|readability|security|maintainability|testing|error_handling>",
      "file": "<filename>",
      "description": "<what could be better>",
      "suggestion": "<specific actionable suggestion>",
      "evidence": "<relevant line or pattern from diff>"
    }}
  ],
  "recommendation": {{
    "action": "<create_issue|create_pr|no_action>",
    "justification": "<2-3 sentences explaining this decision with direct evidence from the diff — cite file names and specific changes>",
    "suggested_title": "<concise, informative title for the issue or PR>",
    "labels": ["<label1>", "<label2>"]
  }},
  "stats": {{
    "lines_added": <int>,
    "lines_removed": <int>,
    "has_tests": <true|false>,
    "has_docs": <true|false>,
    "security_sensitive": <true|false>
  }}
}}"""


def issue_draft_prompt(analysis: dict, diff_snippet: str, custom_instructions: str = "") -> str:
    issues_text = "\n".join(
        f"- [{i['severity'].upper()}] {i['file']}: {i['description']} (Evidence: {i.get('evidence', 'see diff')})"
        for i in analysis.get("issues", [])
    )
    improvements_text = "\n".join(
        f"- [{i['type']}] {i['file']}: {i['description']}"
        for i in analysis.get("improvements", [])
    )

    return f"""You are drafting a GitHub Issue based on a code review.
Write a professional, detailed issue report in GitHub Markdown.
Do NOT wrap in JSON. Return plain markdown only.

Code review summary:
- Category: {analysis.get('category')}
- Risk: {analysis.get('risk')} — {analysis.get('risk_reason')}
- Summary: {analysis.get('summary')}

Issues found:
{issues_text or '(none)'}

Suggested improvements:
{improvements_text or '(none)'}

Suggested title: {analysis.get('recommendation', {}).get('suggested_title', '')}

Diff snippet:
{diff_snippet[:2000]}

{f'Additional instructions: {custom_instructions}' if custom_instructions else ''}

Write the issue body with these sections:
## Summary
## Problem Description  
## Evidence (cite specific files and changes)
## Suggested Fix
## Additional Context

Use clear Markdown. Be specific and actionable. Reference actual file names and code patterns."""


def pr_draft_prompt(analysis: dict, diff_snippet: str, branch: str, base_branch: str, custom_instructions: str = "") -> str:
    return f"""You are drafting a GitHub Pull Request description based on a code review.
Write a professional PR description in GitHub Markdown.
Do NOT wrap in JSON. Return plain markdown only.

Branch: {branch} → {base_branch}
Category: {analysis.get('category')}
Risk: {analysis.get('risk')} — {analysis.get('risk_reason')}
Summary: {analysis.get('summary')}

Issues addressed: {len(analysis.get('issues', []))}
Improvements: {len(analysis.get('improvements', []))}
Has tests: {analysis.get('stats', {}).get('has_tests', False)}
Has docs: {analysis.get('stats', {}).get('has_docs', False)}

Suggested title: {analysis.get('recommendation', {}).get('suggested_title', '')}

Diff snippet:
{diff_snippet[:2000]}

{f'Additional instructions: {custom_instructions}' if custom_instructions else ''}

Write the PR body with:
## Summary
## Changes Made (bullet points per file/area)
## Testing
## Risk Assessment
## Checklist
- [ ] Tests added/updated
- [ ] Documentation updated  
- [ ] No breaking changes (or breaking changes documented)

Be specific and reference actual files and changes from the diff."""


def improve_issue_prompt(original: str, context: str = "") -> str:
    return f"""You are improving an existing GitHub Issue.
Rewrite it to be clearer, more actionable, and better structured.
Do NOT wrap in JSON. Return plain markdown only.

Original issue:
{original}

{f'Context/focus: {context}' if context else ''}

Improve it by:
1. Making the title more specific and searchable (prefix with "IMPROVED TITLE: <title>")
2. Adding clear reproduction steps if it's a bug (or acceptance criteria if it's a feature)  
3. Structuring with proper sections: Summary, Problem, Steps to Reproduce / Expected Behavior, Evidence, Suggested Fix
4. Removing vague language and replacing with specific, technical details
5. Adding any missing context that would help a developer act on it immediately

Return the improved body. Start with "IMPROVED TITLE: <suggested title>" on the first line."""


def improve_pr_prompt(original: str, context: str = "") -> str:
    return f"""You are improving an existing GitHub Pull Request description.
Rewrite it to be clearer, more comprehensive, and easier to review.
Do NOT wrap in JSON. Return plain markdown only.

Original PR:
{original}

{f'Context/focus: {context}' if context else ''}

Improve it by:
1. Making the title more descriptive (prefix with "IMPROVED TITLE: <title>")  
2. Adding a clear summary of WHY these changes were made
3. Breaking down changes by file/component
4. Adding or improving the testing section
5. Noting any risks, side effects, or breaking changes
6. Adding a reviewer checklist

Return the improved body. Start with "IMPROVED TITLE: <suggested title>" on the first line."""


# ══════════════════════════════════════════════════════════════════════════════
# NEW TEMPLATES — Planning, Reflection, Writer (Plan-driven)
# ══════════════════════════════════════════════════════════════════════════════


def planning_prompt(
    action: str,
    category: str,
    risk: str,
    risk_reason: str,
    summary: str,
    issues: list,
    improvements: list,
    diff_snippet: str,
    files: list,
) -> str:
    issues_text = "\n".join(
        f"- [{i.get('severity','?').upper()}] {i.get('file','?')}: {i.get('description','')}"
        for i in issues
    )
    improvements_text = "\n".join(
        f"- [{i.get('type','?')}] {i.get('file','?')}: {i.get('description','')}"
        for i in improvements
    )
    files_text = "\n".join(f"  - {f}" for f in files[:10])

    kind = "issue" if action in ("create_issue", "issue") else "pr"

    return f"""You are a senior engineering lead building an action plan for a GitHub {kind.upper()}.
Based on this code review, produce a structured plan. Return ONLY valid JSON — no markdown, no preamble.

Review summary:
- Category: {category}
- Risk: {risk} — {risk_reason}
- Summary: {summary}

Issues found:
{issues_text or '(none)'}

Improvements:
{improvements_text or '(none)'}

Files changed:
{files_text or '(none)'}

Diff snippet:
{diff_snippet[:2000]}

Return this EXACT JSON schema:
{{
  "rationale": "<why a {kind} is needed, citing specific evidence>",
  "scope": "<which files/components are in scope>",
  "risks": ["<risk 1>", "<risk 2>"],
  "suggested_title": "<concise, specific title for the {kind}>",
  "required_sections": {json_sections(kind)},
  "acceptance_criteria": ["<criterion 1>", "<criterion 2>"],
  "test_plan_required": <true|false>,
  "risk": "<low|medium|high>"
}}"""


def json_sections(kind: str) -> str:
    import json
    if kind == "issue":
        return json.dumps(["Title", "Problem description", "Evidence", "Acceptance criteria", "Risk level"])
    return json.dumps(["Title", "Summary", "Files affected", "Behavior change", "Test plan", "Risk level"])


def instruction_planning_prompt(instruction: str, kind: str, diff_snippet: str, files: list) -> str:
    import json
    files_text = "\n".join(f"  - {f}" for f in files[:10])

    return f"""You are a senior engineering lead. A developer gave this instruction:
"{instruction}"

They want to create a GitHub {kind.upper()}.
{f'Current diff context:{chr(10)}{diff_snippet[:2000]}' if diff_snippet else ''}
{f'Files in repo:{chr(10)}{files_text}' if files else ''}

Build a structured action plan. Return ONLY valid JSON — no markdown, no preamble.

{{
  "rationale": "<why this {kind} is needed based on the instruction>",
  "scope": "<which files/areas are affected>",
  "risks": ["<risk 1>"],
  "suggested_title": "<concise title derived from the instruction>",
  "required_sections": {json_sections(kind)},
  "acceptance_criteria": ["<what done looks like — be specific>"],
  "test_plan_required": <true|false>,
  "risk": "<low|medium|high>"
}}"""


def issue_draft_from_plan_prompt(plan, review_result=None) -> str:
    ac_text = "\n".join(f"- {c}" for c in plan.acceptance_criteria) if plan.acceptance_criteria else "(none specified)"
    risks_text = "\n".join(f"- {r}" for r in plan.risks) if plan.risks else "(none)"

    diff_snippet = ""
    if review_result and review_result.diff:
        diff_snippet = review_result.diff[:2000]

    issues_text = ""
    if review_result and review_result.issues:
        issues_text = "\n".join(
            f"- [{i.get('severity','?').upper()}] {i.get('file','?')}: {i.get('description','')} — Evidence: {i.get('evidence','')}"
            for i in review_result.issues
        )

    instruction_block = f"\nInstruction: {plan.instruction}" if plan.instruction else ""

    return f"""You are drafting a GitHub Issue. Follow the plan exactly.
Write professional GitHub Markdown. Do NOT wrap in JSON.
Start with "TITLE: <title>" on the first line, then the body.{instruction_block}

Plan:
- Rationale: {plan.rationale}
- Scope: {plan.scope}
- Risks: {risks_text}
- Category: {plan.review_category}
- Risk level: {plan.review_risk}

Acceptance criteria:
{ac_text}

Issues found (with evidence):
{issues_text or '(derived from instruction)'}

Diff snippet:
{diff_snippet or '(no diff available)'}

Required sections (ALL must be present):
{chr(10).join(f'- {s}' for s in plan.required_sections)}

Write the issue body now. Every section listed above MUST appear.
Use evidence from the diff or instruction. Do not fabricate specifics."""


def pr_draft_from_plan_prompt(plan, review_result=None) -> str:
    ac_text = "\n".join(f"- {c}" for c in plan.acceptance_criteria) if plan.acceptance_criteria else "(none specified)"
    risks_text = "\n".join(f"- {r}" for r in plan.risks) if plan.risks else "(none)"

    diff_snippet = ""
    files_text = ""
    if review_result:
        diff_snippet = review_result.diff[:2000] if review_result.diff else ""
        files_text = "\n".join(f"  - {fc.path}" for fc in (review_result.files or []))

    instruction_block = f"\nInstruction: {plan.instruction}" if plan.instruction else ""

    return f"""You are drafting a GitHub Pull Request. Follow the plan exactly.
Write professional GitHub Markdown. Do NOT wrap in JSON.
Start with "TITLE: <title>" on the first line, then the body.{instruction_block}

Plan:
- Rationale: {plan.rationale}
- Scope: {plan.scope}
- Risks:
{risks_text}
- Category: {plan.review_category}
- Risk level: {plan.review_risk}
- Test plan required: {plan.test_plan_required}

Files changed:
{files_text or '(see diff)'}

Diff snippet:
{diff_snippet or '(no diff available)'}

Required sections (ALL must be present):
{chr(10).join(f'- {s}' for s in plan.required_sections)}

Acceptance criteria:
{ac_text}

Write the PR body now. Every section listed above MUST appear.
Include a test plan section even if brief. Reference actual files."""


def reflection_prompt(
    draft_title: str,
    draft_body: str,
    plan_action: str,
    required_sections: list,
    missing_sections: list,
    test_plan_required: bool,
    acceptance_criteria: list,
    review_risk: str,
) -> str:
    import json
    sections_text = json.dumps(required_sections)
    missing_text = json.dumps(missing_sections)
    ac_text = "\n".join(f"- {c}" for c in acceptance_criteria) if acceptance_criteria else "(none)"

    return f"""You are a critical reviewer checking a GitHub {plan_action.upper()} draft for quality.
Return ONLY valid JSON — no markdown, no preamble.

Draft title: {draft_title}

Draft body:
{draft_body[:3000]}

Required sections: {sections_text}
Already identified as missing: {missing_text}
Test plan required: {test_plan_required}
Risk level: {review_risk}

Acceptance criteria to verify:
{ac_text}

Check for:
1. Unsupported claims (statements without evidence, code quotes, or file references)
2. Vague language ("some issues", "various problems", "might cause issues")
3. Missing test plan (if required)
4. Missing acceptance criteria
5. Policy violations

Return this EXACT JSON:
{{
  "verdict": "<PASS|FAIL>",
  "findings": ["<specific finding 1>", "<specific finding 2>"],
  "unsupported_claims": ["<claim without evidence>"],
  "vague_language": ["<vague phrase found>"],
  "revision_notes": "<actionable 1-3 sentence guidance on what to fix>",
  "quality_score": <1-10>
}}

Be strict but fair. PASS only if all required sections present, no major vague claims, and evidence is cited."""
