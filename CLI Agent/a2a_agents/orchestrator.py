"""
A2A Orchestrator Client — coordinates all agent servers via A2A protocol.

Used by main.py in 'protocol' mode to route CLI commands through A2A.
Starts agent servers as background processes and communicates via A2A client.
"""

import sys
import os
import json
import time
import subprocess
import signal
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
    Manages server lifecycle and routes tasks between agents.
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

        # MCP client (shared config)
        self.mcp = MCPToolClient(
            repo_path=self.repo_path,
            github_token=self.github_token,
            github_owner=self.github_owner,
            github_repo=self.github_repo,
        )

        # Register cleanup
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
        if self.github_token:
            env["GITHUB_TOKEN"] = self.github_token
        if self.github_owner:
            env["GITHUB_OWNER"] = self.github_owner
        if self.github_repo:
            env["GITHUB_REPO"] = self.github_repo

        for name, script in server_scripts.items():
            port = AGENT_PORTS[name]
            env[f"{name.upper()}_PORT"] = str(port)

            proc = subprocess.Popen(
                [sys.executable, script],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                cwd=_CLI_DIR,
            )
            self._processes.append(proc)
            Console.agent_log("A2A", f"  {name.capitalize()} agent → port {port} (PID {proc.pid})")

        # Wait for servers to start
        Console.agent_log("A2A", "Waiting for servers to be ready...")
        time.sleep(3)

        # Create A2A clients
        for name, port in AGENT_PORTS.items():
            url = f"http://localhost:{port}"
            try:
                self._clients[name] = A2AClient(url)
                Console.agent_log("A2A", f"  Connected to {name}: {self._clients[name].agent_card.name}")
            except Exception as e:
                Console.agent_log("A2A", f"  Warning: Could not connect to {name}: {e}", level="warn")

    def shutdown(self):
        """Stop all agent server processes."""
        for proc in self._processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._processes.clear()
        self._clients.clear()

    def _send_task(self, agent_name: str, params: dict) -> dict:
        """Send a task to an agent and return the result."""
        client = self._clients.get(agent_name)
        if not client:
            raise RuntimeError(f"No A2A client for agent: {agent_name}")

        response = client.ask(json.dumps(params))

        # Parse response — may be a string or have artifacts
        if response is None:
            return {"raw_response": "null", "status": "no_response"}

        response_str = str(response)
        try:
            return json.loads(response_str)
        except (json.JSONDecodeError, TypeError):
            # Try to find JSON object within the response text
            start = response_str.find("{")
            end = response_str.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(response_str[start:end + 1])
                except (json.JSONDecodeError, TypeError):
                    pass
            return {"raw_response": response_str[:500]}

    # ── Pipeline: Review ───────────────────────────────────────────────────

    def review(self, commit_range: str = "", include_staged: bool = False, include_untracked: bool = False) -> dict:
        """Run the review pipeline via A2A: [Reviewer]"""
        Console.agent_log("A2A", "Sending review task to Reviewer agent...")

        result = self._send_task("reviewer", {
            "commit_range": commit_range,
            "include_staged": include_staged,
            "include_untracked": include_untracked,
        })

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
        """
        Run the full draft pipeline via A2A:
        [Reviewer?] → [Planner] → [Writer] → [Critic] → revision loop → [Gatekeeper]
        """
        review_result = None

        # If no instruction, run review first
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
            Console.agent_log("A2A", f"Sending reflection task to Critic agent (round {round_num})...")
            reflection = self._send_task("critic", {"draft": draft, "plan": plan})

            if reflection.get("verdict") == "PASS" and reflection.get("passes_policy", True):
                Console.agent_log("Gatekeeper", "Reflection verdict: PASS", level="success")
                break

            Console.agent_log("Gatekeeper", f"Reflection verdict: FAIL – {reflection.get('revision_notes', '')[:120]}", level="warn")

            if round_num < 2:
                Console.agent_log("Writer", f"Revision required (round {round_num}). Redrafting...")
                draft = self._send_task("writer", {
                    "plan": plan,
                    "review_result": review_result,
                    "reflection_notes": reflection.get("revision_notes", ""),
                })
            else:
                Console.agent_log("Gatekeeper", "Max reflection rounds reached.", level="warn")

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
        """Approve or reject a pending draft."""
        draft_file = os.path.join(_CLI_DIR, ".agent_draft.json")
        if not os.path.exists(draft_file):
            return {"status": "error", "message": "No pending draft found."}

        with open(draft_file) as f:
            saved = json.load(f)

        draft = saved.get("draft", {})

        if not yes:
            result = self._send_task("gatekeeper", {"action": "reject", "draft": draft})
            return result

        result = self._send_task("gatekeeper", {
            "action": "publish",
            "draft": draft,
            "head_branch": saved.get("head_branch", head_branch),
            "base_branch": saved.get("base_branch", base_branch),
            "as_draft_pr": saved.get("as_draft_pr", False),
        })
        return result

    # ── Pipeline: Improve ──────────────────────────────────────────────────

    def improve(self, number: int, kind: str, context: str = "") -> dict:
        """Improve an existing issue or PR. Uses MCP tools directly for GitHub fetch."""
        Console.agent_log("A2A", f"Fetching {kind} #{number} via MCP GitHub tools...")

        try:
            if kind == "issue":
                item = self.mcp.call_github_tool("github_get_issue", {"number": number})
            else:
                item = self.mcp.call_github_tool("github_get_pr", {"number": number})
        except Exception as e:
            return {"status": "error", "message": f"Failed to fetch {kind} #{number}: {e}"}

        original_title = item.get("title", "")
        original_body = item.get("body", "") or ""

        # Use Writer agent to generate improvement
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
