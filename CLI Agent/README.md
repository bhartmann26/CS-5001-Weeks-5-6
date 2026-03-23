# 🤖 GitHub AI Agent

A personalized, fully local AI agent for GitHub repository management.
Powered by **Ollama llama3.2:3b** — no cloud AI required.

**Week 7 Extension:** MCP for Tooling + A2A for Agent-to-Agent Communication.

---

## Architecture

### Direct Mode (Week 5/6 — Original)

```
CLI (main.py) ──► Python agent classes ──► utils (git, github, ollama)
```

### Protocol Mode (Week 7 — MCP + A2A)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  CLI (main.py --mode protocol)                                              │
│       │                                                                     │
│       ▼                                                                     │
│  A2A Orchestrator (HTTP/JSON-RPC)                                           │
│       │    sends tasks to ──►  A2A Agent Servers (5 servers, ports 5001-5005)│
│       │                            │                                        │
│       │                            ▼                                        │
│       │                      MCP Client (stdio transport)                   │
│       │                            │                                        │
│       │                            ▼                                        │
│       │                      MCP Tool Servers (git + github)                │
│       │                                                                     │
│  Agents: [Reviewer] [Planner] [Writer] [Critic] [Gatekeeper]               │
└──────────────────────────────────────────────────────────────────────────────┘
```

| Pattern      | Implementation                                                  |
|-------------|----------------------------------------------------------------|
| Planning    | PlannerAgent produces structured Plan before drafting           |
| Tool Use    | MCP servers wrap git + GitHub API (real tools, no fabrication)  |
| Reflection  | CriticAgent checks evidence, sections, test plans               |
| Multi-agent | 5 roles communicate via A2A protocol (JSON-RPC over HTTP)       |

---

## File Structure

```
CLI Agent/
├── main.py                      ← CLI entry (review/draft/approve/improve)
│
├── agent/
│   ├── reviewer.py              ← [Reviewer] git diff analysis (Task 1)
│   ├── creator.py               ← [Legacy] direct create flow
│   └── improver.py              ← [Reviewer+Writer] improve existing Issue/PR
│
├── patterns/
│   ├── planner.py               ← [Planner] Planning pattern
│   ├── writer.py                ← [Writer] Plan-driven drafting
│   ├── critic.py                ← [Critic] Reflection pattern
│   └── gatekeeper.py            ← [Gatekeeper] approval gate + publishing
│
├── prompts/
│   └── templates.py             ← All prompt templates
│
├── utils/
│   ├── git.py                   ← git diff/log/stats
│   ├── ollama.py                ← Ollama HTTP client
│   ├── github.py                ← GitHub REST API
│   └── console.py               ← ANSI terminal + agent_log()
│
├── mcp_servers/                 ← [WEEK 7 — NEW] MCP Tool Servers
│   ├── mcp_git_server.py        ← Git tools exposed via MCP (FastMCP + stdio)
│   ├── mcp_github_server.py     ← GitHub API tools exposed via MCP
│   └── mcp_client.py            ← Synchronous MCP client wrapper
│
├── a2a_agents/                  ← [WEEK 7 — NEW] A2A Agent Servers
│   ├── reviewer_server.py       ← Reviewer agent A2A server (port 5001)
│   ├── planner_server.py        ← Planner agent A2A server (port 5002)
│   ├── writer_server.py         ← Writer agent A2A server (port 5003)
│   ├── critic_server.py         ← Critic agent A2A server (port 5004)
│   ├── gatekeeper_server.py     ← Gatekeeper agent A2A server (port 5005)
│   └── orchestrator.py          ← A2A Orchestrator client (manages pipeline)
│
├── requirements.txt             ← [WEEK 7 — NEW] mcp, python-a2a
├── .agent_draft.json            ← Persisted draft (auto-created)
└── .agent_log.jsonl             ← Audit log (auto-created)
```

---

## Quick Start

```bash
# 1. Install Ollama + pull model
curl https://ollama.ai/install.sh | sh
ollama pull llama3.2:3b
ollama serve

# 2. Install dependencies (Week 7)
pip install -r requirements.txt

# 3. Run in direct mode (original behavior)
python main.py --help

# 4. Run in protocol mode (MCP + A2A)
python main.py review --mode protocol
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

## Week 7 — Protocol Mode Examples (MCP + A2A)

All commands accept `--mode protocol` to route through MCP tool servers and A2A agent communication:

```bash
# Review via A2A Reviewer agent + MCP git tools
python main.py review --mode protocol --base main

# Draft via full A2A pipeline: Reviewer → Planner → Writer → Critic → Gatekeeper
python main.py draft issue --mode protocol --instruction "Add rate limiting"

# Improve via A2A + MCP GitHub tools
python main.py improve issue --mode protocol --number 42 --owner myorg --repo-name myrepo
```

**What happens in protocol mode:**
```
[A2A]        Starting agent servers...
[A2A]          Reviewer agent → port 5001
[A2A]          Planner agent  → port 5002
[A2A]          Writer agent   → port 5003
[A2A]          Critic agent   → port 5004
[A2A]          Gatekeeper agent → port 5005
[A2A]        Sending review task to Reviewer agent...
[Reviewer]   Connected via A2A, calling git tools via MCP...
[Planner]    Scope validated. Action: ISSUE
[Writer]     Draft created: "Add rate limiting to login endpoint"
[Gatekeeper] Reflection verdict: PASS
[Gatekeeper] HUMAN APPROVAL REQUIRED
? Approve and publish this issue? [y/N]:
```

---

## Dependencies

- **Python 3.11+**
- `git` in PATH
- `ollama` running locally (`ollama serve`)
- GitHub Personal Access Token (classic) with `repo` scope
- **Week 7**: `pip install -r requirements.txt` (installs `mcp` and `python-a2a`)

---

## License

MIT
