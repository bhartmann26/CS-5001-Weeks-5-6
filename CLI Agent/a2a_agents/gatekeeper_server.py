"""
A2A Gatekeeper Agent Server — enforces human approval and publishes to GitHub.

Accepts tasks:
  - "gate": present draft + reflection, request approval decision
  - "publish": actually create the issue/PR on GitHub (after approval)

Uses MCP client to call GitHub tools for publishing.
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_a2a import A2AServer, skill, agent, run_server, TaskStatus, TaskState
from mcp_servers.mcp_client import MCPToolClient


DRAFT_FILE = ".agent_draft.json"
LOG_FILE = ".agent_log.jsonl"


@agent(
    name="Gatekeeper Agent",
    description="Enforces human approval before any GitHub action. Publishes issues and PRs after approval.",
    version="2.0.0",
)
class GatekeeperAgentServer(A2AServer):

    def __init__(self, mcp_client: MCPToolClient = None):
        super().__init__()
        self.mcp = mcp_client

    @skill(
        name="Gate Draft",
        description="Show draft and reflection to user, save for approval",
        tags=["approval", "safety"],
    )
    def gate(self, draft, reflection):
        """Gate a draft for human approval."""
        pass

    @skill(
        name="Publish",
        description="Create issue or PR on GitHub after approval",
        tags=["publish", "github"],
    )
    def publish(self, draft, head_branch="", base_branch="main"):
        """Publish approved draft to GitHub."""
        pass

    def handle_task(self, task):
        message_data = task.message or {}
        content = message_data.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)

        try:
            params = json.loads(text) if text else {}
            action = params.get("action", "gate")

            if action == "gate":
                result = self._gate(params)
            elif action == "publish":
                result = self._publish(params)
            elif action == "save_draft":
                result = self._save_draft(params)
            elif action == "reject":
                result = self._reject(params)
            else:
                result = {"error": f"Unknown action: {action}"}

            task.artifacts = [{"parts": [{"type": "text", "text": json.dumps(result)}]}]
            task.status = TaskStatus(state=TaskState.COMPLETED)

        except Exception as e:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"type": "text", "text": f"Gatekeeper error: {e}"}},
            )

        return task

    def _gate(self, params: dict) -> dict:
        """Save draft for approval and return it for display."""
        draft = params.get("draft", {})
        reflection = params.get("reflection", {})
        head_branch = params.get("head_branch", "")
        base_branch = params.get("base_branch", "main")
        as_draft_pr = params.get("as_draft_pr", False)

        # Save draft locally
        data = {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "draft": draft,
            "reflection": reflection,
            "head_branch": head_branch,
            "base_branch": base_branch,
            "as_draft_pr": as_draft_pr,
        }
        try:
            with open(DRAFT_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

        return {
            "status": "awaiting_approval",
            "draft": draft,
            "reflection": reflection,
            "reflection_passed": reflection.get("verdict") == "PASS" and reflection.get("passes_policy", True),
        }

    def _publish(self, params: dict) -> dict:
        """Publish an approved draft to GitHub via MCP tools."""
        if not self.mcp:
            return {"error": "No MCP client configured — cannot publish"}

        draft = params.get("draft", {})
        head_branch = params.get("head_branch", "")
        base_branch = params.get("base_branch", "main")
        as_draft_pr = params.get("as_draft_pr", False)

        try:
            if draft.get("kind") == "issue":
                result = self.mcp.call_github_tool("github_create_issue", {
                    "title": draft.get("title", ""),
                    "body": draft.get("body", ""),
                    "labels": draft.get("labels", []),
                })
                self._log_event("created_issue", draft, result)
                self._clear_draft()
                return {"status": "published", "type": "issue", "result": result}

            else:  # PR
                if not head_branch:
                    return {"error": "Head branch is required for PRs"}

                result = self.mcp.call_github_tool("github_create_pr", {
                    "title": draft.get("title", ""),
                    "body": draft.get("body", ""),
                    "head": head_branch,
                    "base": base_branch,
                    "draft": as_draft_pr,
                })
                self._log_event("created_pr", draft, result)
                self._clear_draft()
                return {"status": "published", "type": "pr", "result": result}

        except Exception as e:
            self._log_event("failed", draft, {"error": str(e)})
            return {"error": f"GitHub API call failed: {e}"}

    def _save_draft(self, params: dict) -> dict:
        """Save draft for deferred approval."""
        return self._gate(params)

    def _reject(self, params: dict) -> dict:
        """Reject a draft safely."""
        draft = params.get("draft", {})
        self._log_event("rejected", draft, {})
        self._clear_draft()
        return {"status": "rejected", "message": "Draft rejected. No changes made."}

    def _clear_draft(self):
        try:
            if os.path.exists(DRAFT_FILE):
                os.remove(DRAFT_FILE)
        except Exception:
            pass

    def _log_event(self, event: str, draft: dict, result: dict):
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "kind": draft.get("kind", "unknown"),
            "title": draft.get("title", ""),
            "result": result or {},
        }
        try:
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    port = int(os.environ.get("GATEKEEPER_PORT", "5005"))
    server = GatekeeperAgentServer()
    print(f"[A2A] Gatekeeper Agent starting on port {port}")
    run_server(server, port=port)
