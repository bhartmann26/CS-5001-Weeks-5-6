"""
A2A Reviewer Agent Server — analyzes git changes via A2A protocol.

Accepts tasks:
  - "review_changes": analyze git diff and return ReviewResult

Uses MCP client internally to call git tools.
Uses Ollama for AI analysis.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_a2a import A2AServer, skill, agent, run_server, TaskStatus, TaskState
from mcp_servers.mcp_client import MCPToolClient
from utils.ollama import OllamaClient
from prompts.templates import analysis_prompt


@agent(
    name="Reviewer Agent",
    description="Analyzes git diffs, identifies issues, categorizes changes, and recommends actions.",
    version="2.0.0",
)
class ReviewerAgentServer(A2AServer):

    def __init__(self, mcp_client: MCPToolClient = None, ollama: OllamaClient = None):
        super().__init__()
        self.mcp = mcp_client or MCPToolClient()
        self.ollama = ollama or OllamaClient()

    @skill(
        name="Review Changes",
        description="Analyze git diff, identify issues, categorize changes, assess risk",
        tags=["review", "diff", "analysis"],
    )
    def review_changes(self, commit_range="", include_staged=False, include_untracked=False):
        """Analyze git changes and produce a review result."""
        pass  # Logic is in handle_task

    def handle_task(self, task):
        """Process incoming A2A tasks."""
        message_data = task.message or {}
        content = message_data.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)

        try:
            # Parse parameters from the message text (JSON expected)
            params = {}
            try:
                params = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                pass

            commit_range = params.get("commit_range", "")
            include_staged = params.get("include_staged", False)

            # ── 1. Gather data via MCP tools ──────────────────────────────
            branch = self.mcp.call_git_tool("git_current_branch")

            diff = self.mcp.call_git_tool("git_diff", {"commit_range": commit_range})
            if include_staged:
                staged = self.mcp.call_git_tool("git_staged_diff")
                if staged and staged.strip():
                    diff = (diff or "") + "\n\n--- STAGED CHANGES ---\n\n" + staged

            if not diff or not diff.strip():
                task.artifacts = [{"parts": [{"type": "text", "text": json.dumps({"status": "no_changes"})}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
                return task

            files = self.mcp.call_git_tool("git_files_changed", {"commit_range": commit_range})
            commits = self.mcp.call_git_tool("git_recent_commits", {"n": 8, "commit_range": commit_range})
            stats = self.mcp.call_git_tool("git_diff_stats", {
                "diff_text": diff,
                "files_json": files,
            })

            # ── 2. Build prompt and run AI analysis ───────────────────────
            files_summary = "\n".join(
                f"  {f.get('status_label','?').upper():10} {f['path']}" for f in files
            )
            commits_summary = "\n".join(
                f"  {c['hash']} {c['subject']} ({c['author']}, {c['time']})" for c in commits
            )

            prompt = analysis_prompt(
                diff=diff,
                files_summary=files_summary,
                branch=branch,
                recent_commits=commits_summary,
            )

            analysis = self.ollama.generate_json(prompt)

            # ── 3. Build review result ────────────────────────────────────
            review_result = {
                "category": analysis.get("category", "unknown"),
                "risk": analysis.get("risk", "unknown"),
                "risk_reason": analysis.get("risk_reason", ""),
                "summary": analysis.get("summary", ""),
                "issues": analysis.get("issues", []),
                "improvements": analysis.get("improvements", []),
                "recommendation": analysis.get("recommendation", {}).get("action", "no_action"),
                "justification": analysis.get("recommendation", {}).get("justification", ""),
                "suggested_title": analysis.get("recommendation", {}).get("suggested_title", ""),
                "labels": analysis.get("recommendation", {}).get("labels", []),
                "stats": stats,
                "diff": diff[:5000],  # Truncate for A2A message size
                "files": files,
                "branch": branch,
            }

            task.artifacts = [{"parts": [{"type": "text", "text": json.dumps(review_result)}]}]
            task.status = TaskStatus(state=TaskState.COMPLETED)

        except Exception as e:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"type": "text", "text": f"Review failed: {e}"}},
            )

        return task


if __name__ == "__main__":
    port = int(os.environ.get("REVIEWER_PORT", "5001"))
    server = ReviewerAgentServer()
    print(f"[A2A] Reviewer Agent starting on port {port}")
    run_server(server, port=port)
