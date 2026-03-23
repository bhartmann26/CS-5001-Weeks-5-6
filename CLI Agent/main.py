#!/usr/bin/env python3
"""
GitHub AI Agent — CLI
Powered by Ollama llama3.2:3b (fully local)

Week 7 Extension: MCP for Tooling + A2A for Agent Communication
  --mode direct   -> original Week 5/6 behavior (direct Python calls)
  --mode protocol -> MCP tool servers + A2A agent servers

Multi-agent architecture:
  [Reviewer]   — analyzes code changes (ReviewAgent)
  [Planner]    — validates scope, decides action (PlannerAgent)
  [Writer]     — drafts Issue / PR content (WriterAgent)
  [Critic]     — reflects on draft quality (CriticAgent)
  [Gatekeeper] — enforces human approval, publishes (GatekeeperAgent)

Commands:
  review    — analyze git diff (Task 1)
  draft     — plan + write + reflect + gate a new Issue or PR (Task 2)
  approve   — approve or reject a pending draft (Task 2)
  improve   — critique + improve an existing Issue or PR (Task 3)
  create    — [legacy] direct create from review result
"""

import os
import sys
import argparse

from agent.reviewer import ReviewAgent
from agent.creator import CreatorAgent
from agent.improver import ImproverAgent
from patterns.planner import PlannerAgent
from patterns.writer import WriterAgent
from patterns.critic import CriticAgent
from patterns.gatekeeper import GatekeeperAgent

from utils.console import Console
from utils.git import GitClient
from utils.ollama import OllamaClient
from utils.github import GitHubClient


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _is_protocol_mode(args) -> bool:
    return getattr(args, "mode", "direct") == "protocol"

def _make_ollama() -> OllamaClient:
    return OllamaClient()


def _require_ollama(ollama: OllamaClient):
    if not ollama.health_check():
        Console.error("Ollama is not running. Start it with: ollama serve")
        sys.exit(1)


def _prompt_token():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        return input("\n  GitHub token (leave blank to skip): ").strip() or None
    except (KeyboardInterrupt, EOFError):
        return None


def _parse_owner_repo(args):
    if getattr(args, "owner", None) and getattr(args, "repo_name", None):
        return args.owner, args.repo_name
    try:
        import subprocess, re
        out = subprocess.check_output(
            ["git", "-C", getattr(args, "repo", "."), "remote", "get-url", "origin"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        m = re.search(r"github\.com[:/](.+?)/(.+?)(?:\.git)?$", out)
        if m:
            return m.group(1), m.group(2)
    except Exception:
        pass
    owner = input("  GitHub owner/user: ").strip()
    repo_name = input("  Repository name: ").strip()
    return owner, repo_name


def _make_github(args) -> GitHubClient:
    token = getattr(args, "token", None) or _prompt_token()
    if not token:
        Console.error("GitHub token is required.")
        sys.exit(1)
    owner, repo_name = _parse_owner_repo(args)
    return GitHubClient(token=token, owner=owner, repo=repo_name)


# ── Command: review ───────────────────────────────────────────────────────────

def cmd_review(args):
    """
    Task 1: Analyze git changes.
    [Reviewer] runs diff analysis.
    [Planner]  optionally continues to plan next action.
    """
    git = GitClient(args.repo)
    ollama = _make_ollama()
    Console.header("GitHub AI Agent — Code Review")
    _require_ollama(ollama)

    # [Reviewer]
    reviewer = ReviewAgent(git=git, ollama=ollama)
    result = reviewer.review(
        commit_range=args.range,
        include_staged=args.staged,
        include_untracked=args.untracked,
    )

    if not result:
        Console.info("No changes detected. Nothing to review.")
        return

    if args.dry_run:
        Console.info("Dry-run mode — skipping action prompts.")
        return

    if result.recommendation == "no_action":
        Console.agent_log("Planner", "No action required based on review.")
        return

    # Offer to continue to draft
    if result.recommendation in ("create_issue", "create_pr"):
        kind_label = "Issue" if result.recommendation == "create_issue" else "PR"
        Console.blank()
        if Console.confirm(f"[Planner] Proceed to draft a {kind_label} from this review?", default=False):
            _run_draft_pipeline(
                args=args,
                ollama=ollama,
                git=git,
                kind="issue" if result.recommendation == "create_issue" else "pr",
                review_result=result,
                instruction="",
            )


# ── Command: draft ────────────────────────────────────────────────────────────

def cmd_draft(args):
    """
    Task 2: Plan + Write + Reflect + Gate a new Issue or PR.

    Two modes:
      --instruction "..."  → explicit instruction (no diff needed)
      (no instruction)     → runs review first, then drafts from result

    Pipeline: [Planner] → [Writer] → [Critic] → [Gatekeeper]
    """
    git = GitClient(args.repo)
    ollama = _make_ollama()
    Console.header(f"GitHub AI Agent — Draft {args.type.upper()}")
    _require_ollama(ollama)

    review_result = None
    diff = ""
    files = []

    if args.instruction:
        # Explicit instruction path
        Console.agent_log("Planner", f"Explicit instruction received: \"{args.instruction}\"")
        try:
            diff = git.get_diff(getattr(args, "range", None))
            files = [f.path for f in git.get_files_changed(getattr(args, "range", None))]
        except Exception:
            pass
    else:
        # Review-first path
        Console.agent_log("Reviewer", "No instruction provided — running code review first…")
        reviewer = ReviewAgent(git=git, ollama=ollama)
        review_result = reviewer.review(
            commit_range=getattr(args, "range", None),
            include_staged=getattr(args, "staged", False),
        )
        if not review_result:
            Console.error("No changes found. Use --instruction to draft without a diff.")
            sys.exit(1)
        diff = review_result.diff
        files = [f.path for f in review_result.files]

    _run_draft_pipeline(
        args=args,
        ollama=ollama,
        git=git,
        kind=args.type,
        review_result=review_result,
        instruction=args.instruction or "",
        diff=diff,
        files=files,
    )


def _run_draft_pipeline(args, ollama, git, kind, review_result, instruction, diff="", files=None):
    """
    Core multi-agent pipeline:
      [Planner] → [Writer] → [Critic] → (revision loop) → [Gatekeeper]
    """
    files = files or []

    # ── [Planner] ──────────────────────────────────────────────────────────
    planner = PlannerAgent(ollama=ollama, git=git)

    if review_result and not instruction:
        plan = planner.plan_from_review(review_result)
    else:
        plan = planner.plan_from_instruction(
            instruction=instruction,
            kind=kind,
            diff=diff,
            files=files,
        )

    if not plan or not plan.is_valid():
        Console.agent_log("Planner", "Plan yielded no_action. Nothing to draft.")
        return

    # ── [Writer] ───────────────────────────────────────────────────────────
    writer = WriterAgent(ollama=ollama)
    draft = writer.draft(plan=plan, review_result=review_result)

    if not draft:
        Console.agent_log("Writer", "Draft generation failed.", level="error")
        return

    # ── [Critic] — Reflection loop (max 2 rounds) ─────────────────────────
    critic = CriticAgent(ollama=ollama)
    reflection = None
    max_reflection_rounds = 2

    for round_num in range(1, max_reflection_rounds + 1):
        reflection = critic.reflect(draft=draft, plan=plan)

        if reflection.is_pass():
            break

        if round_num < max_reflection_rounds:
            Console.agent_log("Writer", f"Revision required (round {round_num}). Redrafting…")
            revised = writer.redraft(
                plan=plan,
                draft=draft,
                reflection_notes=reflection.revision_notes,
                review_result=review_result,
            )
            if revised:
                draft = revised
            else:
                Console.agent_log("Writer", "Redraft failed. Proceeding with current draft.", level="warn")
                break
        else:
            Console.agent_log(
                "Gatekeeper",
                f"Reflection verdict: FAIL – {reflection.summary()} (max rounds reached)",
                level="warn"
            )

    # ── [Gatekeeper] ───────────────────────────────────────────────────────
    github = None
    try:
        github = _make_github(args)
    except SystemExit:
        Console.agent_log("Gatekeeper", "No GitHub token — draft saved locally only.")

    gatekeeper = GatekeeperAgent(github=github)
    head_branch = ""
    base_branch = getattr(args, "base", "main")
    as_draft_pr = getattr(args, "draft_pr", False)

    if kind == "pr" and review_result:
        head_branch = review_result.branch

    gatekeeper.gate(
        draft=draft,
        reflection=reflection,
        auto_answer=None,
        head_branch=head_branch,
        base_branch=base_branch,
        as_draft_pr=as_draft_pr,
    )


# ── Command: approve ──────────────────────────────────────────────────────────

def cmd_approve(args):
    """
    Approve or reject a pending draft saved by a previous `draft` run.
    [Gatekeeper] enforces the decision.

      agent approve --yes   → publish to GitHub
      agent approve --no    → abort safely, no changes made
    """
    Console.header("GitHub AI Agent — Approve Draft")

    if args.yes and args.no:
        Console.error("Cannot use both --yes and --no")
        sys.exit(1)

    if not args.yes and not args.no:
        Console.error("Must specify --yes or --no")
        sys.exit(1)

    github = None
    if args.yes:
        try:
            github = _make_github(args)
        except SystemExit:
            Console.error("GitHub token required to publish.")
            sys.exit(1)

    gatekeeper = GatekeeperAgent(github=github)
    success = gatekeeper.approve_saved(
        yes=args.yes,
        head_branch=getattr(args, "head", ""),
        base_branch=getattr(args, "base", "main"),
    )

    if args.yes and success:
        Console.agent_log("Gatekeeper", "Creating Pull Request..." if "pr" in str(success) else "Creating Issue...")
        Console.success("Draft approved and published.")
    elif args.no:
        Console.agent_log("Gatekeeper", "Draft rejected. No changes made.")
    elif args.yes and not success:
        sys.exit(1)


# ── Command: improve ──────────────────────────────────────────────────────────

def cmd_improve(args):
    """
    Task 3: Improve an existing GitHub Issue or PR.
    [Reviewer] critiques first, [Writer] proposes improvements.
    [Gatekeeper] gates the update.
    """
    ollama = _make_ollama()
    Console.header(f"GitHub AI Agent — Improve {args.type.upper()} #{args.number}")
    _require_ollama(ollama)

    github = _make_github(args)
    improver = ImproverAgent(ollama=ollama, github=github)
    improver.improve(number=args.number, kind=args.type, context=args.context or "")


# ── Command: create (legacy) ──────────────────────────────────────────────────

def cmd_create(args):
    """Legacy: Direct create using old flow. Kept for backward compatibility."""
    git = GitClient(args.repo)
    ollama = _make_ollama()
    Console.header(f"GitHub AI Agent — Create {args.type.upper()}")
    _require_ollama(ollama)

    github = _make_github(args)
    creator = CreatorAgent(ollama=ollama, github=github, git=git)

    reviewer = ReviewAgent(git=git, ollama=ollama)
    result = reviewer.review(commit_range=args.range, include_staged=args.staged)

    if not result:
        Console.error("No changes found to base the draft on.")
        sys.exit(1)

    if args.type == "issue":
        creator.create_issue(review_result=result, custom_instructions=args.instructions or "")
    else:
        creator.create_pr(review_result=result, base_branch=args.base, custom_instructions=args.instructions or "")


# ── Protocol-mode commands (MCP + A2A) ────────────────────────────────────────


def _make_orchestrator(args):
    """Create and start the A2A orchestrator with MCP clients."""
    from a2a_agents.orchestrator import A2AOrchestrator

    token = getattr(args, "token", None) or os.environ.get("GITHUB_TOKEN", "")
    owner, repo_name = "", ""
    try:
        owner, repo_name = _parse_owner_repo(args)
    except Exception:
        pass

    orchestrator = A2AOrchestrator(
        repo_path=getattr(args, "repo", "."),
        github_token=token,
        github_owner=owner,
        github_repo=repo_name,
    )
    orchestrator.start_servers()
    return orchestrator


def cmd_review_protocol(args):
    """Task 1 via A2A protocol."""
    Console.header("GitHub AI Agent — Code Review [Protocol Mode: MCP + A2A]")
    orch = _make_orchestrator(args)
    try:
        result = orch.review(
            commit_range=getattr(args, "range", "") or "",
            include_staged=getattr(args, "staged", False),
            include_untracked=getattr(args, "untracked", False),
        )

        if result.get("status") == "no_changes":
            Console.info("No changes detected. Nothing to review.")
            return

        # Display review result
        Console.section("AI Analysis Report")
        Console.kv("Category", result.get("category", "unknown"))
        Console.kv("Risk", result.get("risk", "unknown"))
        Console.kv("Summary", result.get("summary", ""))
        Console.kv("Recommendation", result.get("recommendation", "no_action"))
        Console.kv("Justification", result.get("justification", ""))

        if result.get("issues"):
            Console.section(f"Issues Found ({len(result['issues'])})")
            for issue in result["issues"]:
                Console.info(f"  [{issue.get('severity', '?').upper()}] {issue.get('file', '?')} — {issue.get('description', '')}")

    finally:
        orch.shutdown()


def cmd_draft_protocol(args):
    """Task 2 via A2A protocol."""
    Console.header(f"GitHub AI Agent — Draft {args.type.upper()} [Protocol Mode: MCP + A2A]")
    orch = _make_orchestrator(args)
    try:
        result = orch.draft(
            kind=args.type,
            instruction=getattr(args, "instruction", "") or "",
            commit_range=getattr(args, "range", "") or "",
            include_staged=getattr(args, "staged", False),
            base_branch=getattr(args, "base", "main"),
            as_draft_pr=getattr(args, "draft_pr", False),
        )

        if result.get("status") == "awaiting_approval":
            draft = result.get("draft", {})
            Console.blank()
            Console.divider("═")
            Console.kv("Title", draft.get("title", ""))
            Console.kv("Labels", ", ".join(draft.get("labels", [])))
            Console.blank()
            Console.markdown_preview(draft.get("body", ""), max_lines=60)
            Console.divider("═")

            reflection = result.get("reflection", {})
            if reflection.get("verdict") == "PASS":
                Console.agent_log("Gatekeeper", "Reflection verdict: PASS", level="success")
            else:
                Console.agent_log("Gatekeeper", f"Reflection verdict: FAIL – {reflection.get('revision_notes', '')[:120]}", level="warn")

            # Interactive approval
            if Console.confirm(f"Approve and publish this {args.type}?", default=False):
                pub_result = orch.approve(yes=True, base_branch=getattr(args, "base", "main"))
                if pub_result.get("status") == "published":
                    Console.success(f"{args.type.upper()} published successfully!")
                    Console.kv("URL", pub_result.get("result", {}).get("html_url", ""))
                else:
                    Console.error(f"Publish failed: {pub_result.get('error', 'unknown')}")
            else:
                orch.approve(yes=False)
                Console.agent_log("Gatekeeper", "Draft rejected. No changes made.")
        else:
            Console.info(f"Draft result: {result.get('status', 'unknown')}")

    finally:
        orch.shutdown()


def cmd_approve_protocol(args):
    """Approve/reject via A2A protocol."""
    Console.header("GitHub AI Agent — Approve Draft [Protocol Mode: MCP + A2A]")

    if args.yes and args.no:
        Console.error("Cannot use both --yes and --no")
        sys.exit(1)
    if not args.yes and not args.no:
        Console.error("Must specify --yes or --no")
        sys.exit(1)

    orch = _make_orchestrator(args)
    try:
        result = orch.approve(
            yes=args.yes,
            head_branch=getattr(args, "head", ""),
            base_branch=getattr(args, "base", "main"),
        )

        if args.yes and result.get("status") == "published":
            Console.success(f"Published! URL: {result.get('result', {}).get('html_url', '')}")
        elif args.no:
            Console.agent_log("Gatekeeper", "Draft rejected. No changes made.")
        else:
            Console.error(f"Publish failed: {result.get('error', result.get('message', 'unknown'))}")
    finally:
        orch.shutdown()


def cmd_improve_protocol(args):
    """Task 3 via A2A protocol."""
    Console.header(f"GitHub AI Agent — Improve {args.type.upper()} #{args.number} [Protocol Mode: MCP + A2A]")
    orch = _make_orchestrator(args)
    try:
        result = orch.improve(
            number=args.number,
            kind=args.type,
            context=getattr(args, "context", "") or "",
        )

        if result.get("status") == "improvement_ready":
            Console.section("Title Comparison")
            Console.kv("Before", result.get("original_title", ""))
            Console.kv("After", result.get("improved_title", ""))
            Console.blank()
            Console.section("Improved Body")
            Console.markdown_preview(result.get("improved_body", ""), max_lines=60)

            if Console.confirm(f"Apply improvement to {args.type} #{args.number}?", default=False):
                tool_name = "github_update_issue" if args.type == "issue" else "github_update_pr"
                orch.mcp.call_github_tool(tool_name, {
                    "number": args.number,
                    "title": result["improved_title"],
                    "body": result["improved_body"],
                })
                Console.success(f"{args.type.capitalize()} #{args.number} updated!")
            else:
                Console.info("Cancelled. Original unchanged.")
        else:
            Console.error(f"Improvement failed: {result.get('message', 'unknown')}")
    finally:
        orch.shutdown()


# ── Parser ────────────────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="agent",
        description="AI-powered GitHub agent — Planning · Tool Use · Reflection · Multi-agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Multi-agent roles:
  [Reviewer]   analyzes git diff and repository files
  [Planner]    validates scope, decides action, produces structured Plan
  [Writer]     drafts Issue/PR body following the Plan
  [Critic]     reflects on draft — checks evidence, sections, test plans
  [Gatekeeper] enforces human approval before any GitHub action

Examples:

  Task 1 — Review changes:
    python main.py review --base main
    python main.py review --range HEAD~3..HEAD
    python main.py review --staged --dry-run

  Task 2 — Draft from code review:
    python main.py draft issue
    python main.py draft pr --base main

  Task 2 — Draft from explicit instruction:
    python main.py draft issue --instruction "Add rate limiting to login endpoint"
    python main.py draft pr   --instruction "Refactor duplicated pricing logic"

  Task 2 — Approve or reject saved draft:
    python main.py approve --yes --owner myorg --repo-name myrepo --token ghp_xxx
    python main.py approve --no

  Task 3 — Improve existing Issue or PR:
    python main.py improve issue --number 42 --owner myorg --repo-name myrepo
    python main.py improve pr    --number 17 --context "Add security section"

Expected output pattern:
  [Planner]    Scope validated.
  [Writer]     Draft PR created.
  [Gatekeeper] Reflection verdict: FAIL – missing test plan.
  [Writer]     Revision required. Redrafting…
  [Gatekeeper] Reflection verdict: PASS
  [Gatekeeper] HUMAN APPROVAL REQUIRED
  ? Approve and publish this pr? [y/N]: y
  [Gatekeeper] GitHub API call successful.
        """,
    )

    # Shared parent parser
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--repo", default=".", help="Path to local git repo (default: .)")
    shared.add_argument("--token", help="GitHub personal access token")
    shared.add_argument("--owner", help="GitHub owner/org")
    shared.add_argument("--repo-name", dest="repo_name", help="GitHub repository name")
    shared.add_argument(
        "--mode", choices=["direct", "protocol"], default="direct",
        help="Execution mode: 'direct' (original) or 'protocol' (MCP + A2A)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # review
    p_review = sub.add_parser("review", parents=[shared], help="[Reviewer] Analyze git changes (Task 1)")
    p_review.add_argument("--range", metavar="COMMIT_RANGE", help="e.g. main..HEAD or HEAD~3..HEAD")
    p_review.add_argument("--base", default="main", help="Base branch to compare against")
    p_review.add_argument("--staged", action="store_true", help="Include staged changes")
    p_review.add_argument("--untracked", action="store_true", help="List untracked files")
    p_review.add_argument("--dry-run", action="store_true", help="Review only, skip action prompts")
    p_review.set_defaults(func=cmd_review)

    # draft
    p_draft = sub.add_parser(
        "draft", parents=[shared],
        help="[Planner→Writer→Critic→Gatekeeper] Draft Issue or PR (Task 2)"
    )
    p_draft.add_argument("type", choices=["issue", "pr"], help="Type to draft")
    p_draft.add_argument("--instruction", help="Explicit instruction (e.g. 'Add rate limiting to login')")
    p_draft.add_argument("--range", metavar="COMMIT_RANGE")
    p_draft.add_argument("--staged", action="store_true")
    p_draft.add_argument("--base", default="main", help="Base branch for PRs (default: main)")
    p_draft.add_argument("--draft-pr", action="store_true", dest="draft_pr", help="Create as GitHub draft PR")
    p_draft.set_defaults(func=cmd_draft)

    # approve
    p_approve = sub.add_parser(
        "approve", parents=[shared],
        help="[Gatekeeper] Approve or reject a pending draft"
    )
    p_approve.add_argument("--yes", action="store_true", help="Approve and publish to GitHub")
    p_approve.add_argument("--no", action="store_true", help="Reject safely — no changes made")
    p_approve.add_argument("--head", default="", help="Head branch for PRs")
    p_approve.add_argument("--base", default="main", help="Base branch for PRs")
    p_approve.set_defaults(func=cmd_approve)

    # improve
    p_improve = sub.add_parser(
        "improve", parents=[shared],
        help="[Reviewer→Writer→Gatekeeper] Improve existing Issue or PR (Task 3)"
    )
    p_improve.add_argument("type", choices=["issue", "pr"], help="Type to improve")
    p_improve.add_argument("--number", "-n", type=int, required=True, help="Issue or PR number")
    p_improve.add_argument("--context", help="Extra context e.g. 'focus on security implications'")
    p_improve.set_defaults(func=cmd_improve)

    # create (legacy)
    p_create = sub.add_parser("create", parents=[shared], help="[Legacy] Direct create from review")
    p_create.add_argument("type", choices=["issue", "pr"])
    p_create.add_argument("--range", metavar="COMMIT_RANGE")
    p_create.add_argument("--staged", action="store_true")
    p_create.add_argument("--base", default="main")
    p_create.add_argument("--instructions")
    p_create.set_defaults(func=cmd_create)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        # Route to protocol-mode commands if --mode protocol
        if _is_protocol_mode(args):
            protocol_funcs = {
                "review": cmd_review_protocol,
                "draft": cmd_draft_protocol,
                "approve": cmd_approve_protocol,
                "improve": cmd_improve_protocol,
            }
            func = protocol_funcs.get(args.command)
            if func:
                func(args)
            else:
                Console.warning(f"Command '{args.command}' not supported in protocol mode. Using direct mode.")
                args.func(args)
        else:
            args.func(args)
    except KeyboardInterrupt:
        Console.warning("\nAborted.")
        sys.exit(0)
    except Exception as e:
        Console.error(f"Unexpected error: {e}")
        if "--debug" in sys.argv:
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()
