"""
A2A Orchestrator Client — coordinates all agent servers via A2A protocol.

Architecture:
  1. Orchestrator calls MCP tool servers for data gathering (git, github)
  2. Orchestrator sends gathered data to A2A agent servers for processing
  3. A2A agents do AI work (Ollama) and return results

This avoids nested subprocess issues (A2A subprocess → MCP subprocess).
"""

import sys
import os
import json
import time
import subprocess
import atexit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_a2a import A2AClient
from mcp_servers.mcp_client import MCPToolClient
from utils.console import Console


# Agent port assignments
AGENT_PORTS = {
    "reviewer": 5001,
    "planner": 5002,
    "writer": 5003,
    "critic": 5004,
    "gatekeeper": 5005,
}

# Path to agent server scripts
_A2A_DIR = os.path.dirname(os.path.abspath(__file__))
_CLI_DIR = os.path.dirname(_A2A_DIR)


class A2AOrchestrator:
    """
    Orchestrates multi-agent pipelines via A2A protocol.
    Uses MCP for tool access, A2A for agent communication.
    """

    def __init__(
        self,
        repo_path: str = ".",
        github_token: str = "",
        github_owner: str = "",
        github_repo: str = "",
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.github_token = github_token
        self.github_owner = github_owner
        self.github_repo = github_repo
        self._processes: list[subprocess.Popen] = []
        self._clients: dict[str, A2AClient] = {}

        # MCP client for tool access (called from orchestrator, not from agents)
        self.mcp = MCPToolClient(
            repo_path=self.repo_path,
            github_token=self.github_token,
            github_owner=self.github_owner,
            github_repo=self.github_repo,
        )

        atexit.register(self.shutdown)

    # ── Server lifecycle ───────────────────────────────────────────────────

    def start_servers(self):
        """Start all A2A agent servers as background processes."""
        Console.agent_log("A2A", "Starting agent servers...")

        server_scripts = {
            "reviewer": os.path.join(_A2A_DIR, "reviewer_server.py"),
            "planner": os.path.join(_A2A_DIR, "planner_server.py"),
            "writer": os.path.join(_A2A_DIR, "writer_server.py"),
            "critic": os.path.join(_A2A_DIR, "critic_server.py"),
            "gatekeeper": os.path.join(_A2A_DIR, "gatekeeper_server.py"),
        }

        env = os.environ.copy()
        env["PYTHONPATH"] = _CLI_DIR + os.pathsep + env.get("PYTHONPATH", "")
        env["GIT_REPO_PATH"] = self.repo_path

        for name, script in server_scripts.items():
            port = AGENT_PORTS[name]
            env[f"{name.upper()}_PORT"] = str(port)

            proc = subprocess.Popen(
                [sys.executable, script],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=_CLI_DIR,
            )
            self._processes.append(proc)
            Console.agent_log("A2A", f"  {name.capitalize()} agent → port {port} (PID {proc.pid})")

        Console.agent_log("A2A", "Waiting for servers to be ready...")
        time.sleep(4)

        for name, port in AGENT_PORTS.items():
            url = f"http://localhost:{port}"
            try:
                self._clients[name] = A2AClient(url)
                Console.agent_log("A2A", f"  ✓ Connected to {name}")
            except Exception as e:
                Console.agent_log("A2A", f"  ✗ Could not connect to {name}: {e}", level="warn")

    def shutdown(self):
        """Stop all agent server processes."""
        for proc in self._processes:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._processes.clear()
        self._clients.clear()

    def _send_task(self, agent_name: str, params: dict) -> dict:
        """Send a task to an A2A agent and parse the result."""
        client = self._clients.get(agent_name)
        if not client:
            raise RuntimeError(f"No A2A client for agent: {agent_name}")

        response = client.ask(json.dumps(params))

        if response is None:
            return {"status": "no_response"}

        response_str = str(response)

        # Try direct JSON parse
        try:
            return json.loads(response_str)
        except (json.JSONDecodeError, TypeError):
            pass

        # Try extracting JSON from within the text
        start = response_str.find("{")
        end = response_str.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(response_str[start:end + 1])
            except (json.JSONDecodeError, TypeError):
                pass

        return {"raw_response": response_str[:500]}

    # ── MCP Tool Helpers ───────────────────────────────────────────────────

    def _gather_git_data(self, commit_range: str = "", include_staged: bool = False) -> dict:
        """Use MCP tools to gather all git data needed for review."""
        Console.agent_log("MCP", "Gathering git data via MCP tools...")

        branch = self.mcp.call_git_tool("git_current_branch")
        Console.agent_log("MCP", f"  Branch: {branch}")

        diff = self.mcp.call_git_tool("git_diff", {"commit_range": commit_range})
        if include_staged:
            staged = self.mcp.call_git_tool("git_staged_diff")
            if staged and staged.strip():
                diff = (diff or "") + "\n\n--- STAGED ---\n\n" + staged

        if not diff or not diff.strip():
            return {"status": "no_changes"}

        Console.agent_log("MCP", f"  Diff: {len(diff)} chars")

        files = self.mcp.call_git_tool("git_files_changed", {"commit_range": commit_range})
        Console.agent_log("MCP", f"  Files: {len(files) if files else 0}")

        commits = self.mcp.call_git_tool("git_recent_commits", {"n": 8, "commit_range": commit_range})
        stats = self.mcp.call_git_tool("git_diff_stats", {
            "diff_text": diff,
            "files_json": files or [],
        })

        return {
            "diff": diff,
            "branch": branch,
            "files": files or [],
            "commits": commits or [],
            "stats": stats or {},
        }

    # ── Pipeline: Review ───────────────────────────────────────────────────

    def review(self, commit_range: str = "", include_staged: bool = False, include_untracked: bool = False) -> dict:
        """Run review: MCP gathers data → A2A Reviewer analyzes."""

        # Step 1: MCP tools gather git data
        git_data = self._gather_git_data(commit_range=commit_range, include_staged=include_staged)

        if git_data.get("status") == "no_changes":
            return {"status": "no_changes"}

        # Step 2: Send to Reviewer agent via A2A
        Console.agent_log("A2A", "Sending data to Reviewer agent for analysis...")
        result = self._send_task("reviewer", git_data)
        return result

    # ── Pipeline: Draft ────────────────────────────────────────────────────

    def draft(
        self,
        kind: str,
        instruction: str = "",
        commit_range: str = "",
        include_staged: bool = False,
        base_branch: str = "main",
        as_draft_pr: bool = False,
    ) -> dict:
        """MCP gathers → A2A: Reviewer → Planner → Writer → Critic → Gatekeeper"""
        review_result = None

        if not instruction:
            Console.agent_log("A2A", "No instruction — running review first...")
            review_result = self.review(commit_range=commit_range, include_staged=include_staged)

            if review_result.get("status") == "no_changes":
                Console.error("No changes found. Use --instruction to draft without a diff.")
                return {"status": "no_changes"}

        # [Planner]
        Console.agent_log("A2A", "Sending planning task to Planner agent...")
        if review_result and not instruction:
            plan = self._send_task("planner", {"review_result": review_result})
        else:
            plan = self._send_task("planner", {
                "instruction": instruction,
                "kind": kind,
                "diff": review_result.get("diff", "") if review_result else "",
                "files": [f["path"] if isinstance(f, dict) else f for f in (review_result or {}).get("files", [])],
            })

        if plan.get("action") == "no_action":
            Console.agent_log("Planner", "Plan yielded no_action. Nothing to draft.")
            return {"status": "no_action"}

        Console.agent_log("Planner", f"Scope validated. Action: {plan.get('action', '?').upper()}")

        # [Writer]
        Console.agent_log("A2A", "Sending draft task to Writer agent...")
        draft = self._send_task("writer", {
            "plan": plan,
            "review_result": review_result,
        })

        if not draft or not draft.get("title"):
            Console.agent_log("Writer", "Draft generation failed.", level="error")
            return {"status": "draft_failed"}

        Console.agent_log("Writer", f"Draft created: \"{draft.get('title')}\"")

        # [Critic] — reflection loop (max 2 rounds)
        reflection = None
        for round_num in range(1, 3):
            Console.agent_log("A2A", f"Sending reflection task to Critic (round {round_num})...")
            reflection = self._send_task("critic", {"draft": draft, "plan": plan})

            if reflection.get("verdict") == "PASS" and reflection.get("passes_policy", True):
                Console.agent_log("Critic", "Reflection verdict: PASS", level="success")
                break

            Console.agent_log("Critic", f"Reflection verdict: FAIL – {reflection.get('revision_notes', '')[:120]}", level="warn")

            if round_num < 2:
                Console.agent_log("Writer", f"Revision required. Redrafting...")
                draft = self._send_task("writer", {
                    "plan": plan,
                    "review_result": review_result,
                    "reflection_notes": reflection.get("revision_notes", ""),
                })
            else:
                Console.agent_log("Critic", "Max reflection rounds reached.", level="warn")

        # [Gatekeeper] — save draft for approval
        Console.agent_log("A2A", "Sending gate task to Gatekeeper agent...")
        gate_result = self._send_task("gatekeeper", {
            "action": "gate",
            "draft": draft,
            "reflection": reflection or {},
            "head_branch": review_result.get("branch", "") if review_result else "",
            "base_branch": base_branch,
            "as_draft_pr": as_draft_pr,
        })

        return {
            "status": "awaiting_approval",
            "draft": draft,
            "reflection": reflection,
            "gate_result": gate_result,
        }

    # ── Pipeline: Approve ──────────────────────────────────────────────────

    def approve(self, yes: bool, head_branch: str = "", base_branch: str = "main") -> dict:
        """Approve or reject via A2A Gatekeeper + MCP GitHub tools."""
        draft_file = os.path.join(_CLI_DIR, ".agent_draft.json")
        if not os.path.exists(draft_file):
            return {"status": "error", "message": "No pending draft found."}

        with open(draft_file) as f:
            saved = json.load(f)

        draft = saved.get("draft", {})

        if not yes:
            result = self._send_task("gatekeeper", {"action": "reject", "draft": draft})
            return result

        # Publish via MCP GitHub tools (called from orchestrator)
        try:
            if draft.get("kind") == "issue":
                pub = self.mcp.call_github_tool("github_create_issue", {
                    "title": draft.get("title", ""),
                    "body": draft.get("body", ""),
                    "labels": draft.get("labels", []),
                })
            else:
                pub = self.mcp.call_github_tool("github_create_pr", {
                    "title": draft.get("title", ""),
                    "body": draft.get("body", ""),
                    "head": saved.get("head_branch", head_branch),
                    "base": saved.get("base_branch", base_branch),
                    "draft": saved.get("as_draft_pr", False),
                })

            # Clean up draft file
            try:
                os.remove(draft_file)
            except Exception:
                pass

            return {"status": "published", "result": pub}

        except Exception as e:
            return {"status": "error", "message": f"Publish failed: {e}"}

    # ── Pipeline: Improve ──────────────────────────────────────────────────

    def improve(self, number: int, kind: str, context: str = "") -> dict:
        """Improve existing issue/PR: MCP fetches → Ollama improves."""
        Console.agent_log("MCP", f"Fetching {kind} #{number} via MCP GitHub tools...")

        try:
            if kind == "issue":
                item = self.mcp.call_github_tool("github_get_issue", {"number": number})
            else:
                item = self.mcp.call_github_tool("github_get_pr", {"number": number})
        except Exception as e:
            return {"status": "error", "message": f"Failed to fetch {kind} #{number}: {e}"}

        original_title = item.get("title", "")
        original_body = item.get("body", "") or ""

        from prompts.templates import improve_issue_prompt, improve_pr_prompt
        from utils.ollama import OllamaClient

        ollama = OllamaClient()
        original_full = f"Title: {original_title}\n\n{original_body}"

        if kind == "issue":
            prompt = improve_issue_prompt(original=original_full, context=context)
        else:
            prompt = improve_pr_prompt(original=original_full, context=context)

        improved_raw = ollama.generate(prompt, temperature=0.3, max_tokens=1800)

        improved_title = original_title
        improved_body = improved_raw
        for line in improved_raw.splitlines():
            if line.startswith("IMPROVED TITLE:"):
                improved_title = line.replace("IMPROVED TITLE:", "").strip()
                rest = improved_raw[improved_raw.index(line) + len(line):]
                improved_body = rest.lstrip("\n")
                break

        return {
            "status": "improvement_ready",
            "number": number,
            "kind": kind,
            "original_title": original_title,
            "original_body": original_body,
            "improved_title": improved_title,
            "improved_body": improved_body,
        }
