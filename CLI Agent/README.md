# 🤖 GitHub AI Agent

A personalized, fully local AI agent for GitHub repository management.
Powered by **Ollama llama3.2:3b** — no cloud AI, no pip dependencies.

---

## Architecture — Four Patterns

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Multi-Agent System                           │
│                                                                     │
│  [Reviewer]   ──► analyzes git diff, files, commits                │
│  [Planner]    ──► validates scope, decides action, makes Plan       │
│  [Writer]     ──► drafts Issue/PR body guided by Plan               │
│  [Critic]     ──► reflects on draft quality (Reflection artifact)   │
│  [Gatekeeper] ──► enforces human approval, publishes to GitHub      │
└─────────────────────────────────────────────────────────────────────┘

Pattern: Planning   → PlannerAgent produces structured Plan before drafting
Pattern: Tool Use   → real git diff, file reads, GitHub API (no fabrication)
Pattern: Reflection → CriticAgent checks evidence, sections, test plans
Pattern: Multi-agent→ 5 identifiable roles, each with scoped responsibility
```

---

## File Structure

```
github-ai-agent/
├── main.py                      ← CLI entry (review/draft/approve/improve)
│
├── agent/
│   ├── reviewer.py              ← [Reviewer] git diff analysis (Task 1) — UNCHANGED
│   ├── creator.py               ← [Legacy] direct create flow — UNCHANGED
│   ├── improver.py              ← [Reviewer+Writer] improve existing Issue/PR — UNCHANGED
│   ├── planner.py               ← [Planner] Planning pattern — NEW
│   ├── writer.py                ← [Writer] Plan-driven drafting — NEW
│   ├── critic.py                ← [Critic] Reflection pattern + ReflectionArtifact — NEW
│   └── gatekeeper.py            ← [Gatekeeper] approval gate + draft persistence — NEW
│
├── prompts/
│   └── templates.py             ← All prompt templates (orig + planning/reflection) — EXTENDED
│
├── utils/
│   ├── git.py                   ← git diff/log/stats — UNCHANGED
│   ├── ollama.py                ← Ollama HTTP client — UNCHANGED
│   ├── github.py                ← GitHub REST API — UNCHANGED
│   └── console.py               ← ANSI terminal + agent_log() — EXTENDED
│
└── .agent_draft.json            ← Persisted draft for `approve` command (auto-created)
    .agent_log.jsonl             ← Audit log of all agent actions (auto-created)
```

---

## Quick Start

```bash
# 1. Install Ollama + pull model
curl https://ollama.ai/install.sh | sh
ollama pull llama3.2:3b
ollama serve

# 2. Run (Python 3.11+, no pip install needed)
python main.py --help
```

---

## Task 1 — Review Changes

```bash
# Review current branch vs base
python main.py review --base main

# Review a commit range
python main.py review --range HEAD~3..HEAD

# Review staged + working changes
python main.py review --staged

# Dry-run (no action prompts)
python main.py review --dry-run
```

**What happens:**
```
[Reviewer] Reading git diff…
[Reviewer] Listing changed files…
[Reviewer] Sending to Ollama…

▶ AI Analysis Report
  [FEATURE]  ● MEDIUM

  Summary: …
  Risk Reason: …

  Issues Found (2):
    [WARNING] auth/login.py — Missing rate limiting
    Evidence: +def login(user, pwd): return db.check(user, pwd)

▶ Agent Decision
  ▶ CREATE ISSUE

  Justification: auth/login.py adds login endpoint (line +47) without
  rate limiting or brute-force protection…

[Planner] Proceed to draft a Issue from this review? [y/N]:
```

---

## Task 2 — Draft and Create Issue or PR

### From code review (review-first path):
```bash
python main.py draft issue
python main.py draft pr --base main
```

### From explicit instruction (no diff needed):
```bash
python main.py draft issue --instruction "Add rate limiting to login endpoint"
python main.py draft pr   --instruction "Refactor duplicated pricing logic"
```

**Pipeline output:**
```
[Planner]    Scope validated. Action: ISSUE
[Planner]    Rationale: auth/login.py adds endpoint without rate limiting…
[Planner]    Required sections: Title, Problem description, Evidence, Acceptance criteria, Risk level
[Planner]    Risk identified: High-risk auth modification without tests
[Writer]     Drafting ISSUE from plan…
[Writer]     Draft issue created: "Security: Missing rate limiting on login endpoint"
[Critic]     Reflecting on ISSUE draft…
[Gatekeeper] Reflection verdict: PASS
[Gatekeeper] Presenting draft for human review…

══════════════════════════════════════════
── DRAFT ISSUE ──
══════════════════════════════════════════
Title: Security: Missing rate limiting on login endpoint
...full body...

  ⚠  HUMAN APPROVAL REQUIRED
  ? Approve and publish this issue? [y/N]: y
[Gatekeeper] Creating Issue...
[Gatekeeper] GitHub API call successful.
✓ Issue #42 created: https://github.com/org/repo/issues/42
```

### When reflection FAILS:
```
[Gatekeeper] Reflection verdict: FAIL – Missing sections: Test plan
[Writer]     Revision required (round 1). Redrafting…
[Critic]     Reflecting on ISSUE draft… (round 2)
[Gatekeeper] Reflection verdict: PASS
```

### Deferred approval (two-step):
```bash
# Step 1: draft (saves to .agent_draft.json)
python main.py draft issue --instruction "Add input validation"

# Step 2: approve separately
python main.py approve --yes --owner myorg --repo-name myrepo --token ghp_xxx
python main.py approve --no    # safe abort
```

**On --no:**
```
[Gatekeeper] Draft rejected. No changes made.
```

---

## Task 3 — Improve Existing Issue or PR

```bash
python main.py improve issue --number 42 --owner myorg --repo-name myrepo
python main.py improve pr    --number 17 --context "Add security section"
```

**Output:**
```
[Reviewer] Issue lacks acceptance criteria.
[Reviewer] Vague language detected: "some issues", "various problems"
[Writer]   Proposed improved structured version.
[Gatekeeper] Reflection verdict: PASS.

Side-by-side:
  Before title: "Login broken"
  After  title: "Bug: Login endpoint returns 500 when password contains special chars"

  ⚠  HUMAN APPROVAL REQUIRED — review carefully, nothing changes until you confirm
  ? Apply changes to issue #42? [y/N]:
```

---

## Draft Artifact Schema

**Issue must include:**
- Title
- Problem description
- Evidence (code/file references)
- Acceptance criteria
- Risk level

**PR must include:**
- Title
- Summary
- Files affected
- Behavior change
- Test plan
- Risk level

The **Reflection artifact** checks every section is present. If missing → FAIL → Writer revises.

---

## Audit Log

Every agent action is appended to `.agent_log.jsonl`:
```json
{"ts": "2025-01-15T10:23:44", "event": "created_issue", "kind": "issue",
 "title": "Security: Missing rate limiting", "reflection_verdict": "PASS",
 "result": {"number": 42, "html_url": "https://github.com/..."}}
```

---

## Zero Dependencies

- Python 3.11+ stdlib only
- `git` in PATH
- `ollama` running locally (`ollama serve`)
- GitHub Personal Access Token (classic) with `repo` scope for publish actions. Store it in a `GITHUB_TOKEN` environment variable, pass it via `--token`, or enter it when prompted in the terminal.

---

## License

MIT
