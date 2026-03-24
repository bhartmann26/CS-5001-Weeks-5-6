"""
A2A Reviewer Agent Server — analyzes git changes via A2A protocol.

Receives pre-gathered git data (from MCP at orchestrator level),
runs Ollama AI analysis, returns ReviewResult JSON.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_a2a import A2AServer, skill, agent, run_server, TaskStatus, TaskState
from utils.ollama import OllamaClient
from utils.console import Console
from prompts.templates import analysis_prompt


@agent(
    name="Reviewer Agent",
    description="Analyzes git diffs, identifies issues, categorizes changes, and recommends actions.",
    version="2.0.0",
)
class ReviewerAgentServer(A2AServer):

    def __init__(self, ollama: OllamaClient = None, url: str = None, **kwargs):
        if url:
            kwargs['url'] = url
        super().__init__(**kwargs)
        self.ollama = ollama or OllamaClient()

    @skill(
        name="Review Changes",
        description="Analyze git diff, identify issues, categorize changes, assess risk",
        tags=["review", "diff", "analysis"],
    )
    def review_changes(self):
        pass

    def handle_task(self, task):
        message_data = task.message or {}
        content = message_data.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)

        Console.agent_log("Reviewer", f"[DEBUG] Message type: {type(message_data)}, has content: {'content' in message_data}")
        Console.agent_log("Reviewer", f"[DEBUG] Text preview: {text[:200] if text else '(empty)'}")

        try:
            params = {}
            try:
                params = json.loads(text)
            except (json.JSONDecodeError, TypeError) as e:
                Console.agent_log("Reviewer", f"[DEBUG] JSON parse failed: {e}, trying direct params", level="warn")
                # Sometimes the params come directly in message_data
                params = message_data.copy()

            diff = params.get("diff", "")
            branch = params.get("branch", "unknown")
            files = params.get("files", [])
            commits = params.get("commits", [])
            stats = params.get("stats", {})

            Console.agent_log("Reviewer", f"[DEBUG] Extracted: diff={len(diff)} chars, branch={branch}, files={len(files)}, commits={len(commits)}")

            if not diff or not diff.strip():
                Console.agent_log("Reviewer", "No diff found in params", level="warn")
                result_json = json.dumps({"status": "no_changes", "debug": "empty_diff"})
                task.artifacts = [{"parts": [{"type": "text", "text": result_json}]}]
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message={"role": "agent", "content": {"type": "text", "text": result_json}},
                )
                return task

            # Truncate diff for LLM context window (llama3.2:3b ~4K context)
            max_diff = 12000
            if len(diff) > max_diff:
                diff = diff[:max_diff] + f"\n\n... [truncated, {len(diff)} total chars]"

            files_summary = "\n".join(
                f"  {f.get('status_label', '?').upper():10} {f['path']}"
                for f in files if isinstance(f, dict)
            )
            commits_summary = "\n".join(
                f"  {c['hash']} {c['subject']} ({c['author']}, {c['time']})"
                for c in commits if isinstance(c, dict)
            )

            prompt = analysis_prompt(
                diff=diff,
                files_summary=files_summary,
                branch=branch,
                recent_commits=commits_summary,
            )

            Console.agent_log("Reviewer", f"[DEBUG] Prompt length: {len(prompt)} chars, calling Ollama...")
            analysis = self.ollama.generate_json(prompt)
            Console.agent_log("Reviewer", f"[DEBUG] Ollama response keys: {list(analysis.keys()) if analysis else 'empty'}")

            if not analysis:
                Console.agent_log("Reviewer", "Ollama returned empty dict", level="warn")

            review_result = {
                "category": analysis.get("category", "unknown"),
                "risk": analysis.get("risk", "unknown"),
                "risk_reason": analysis.get("risk_reason", ""),
                "summary": analysis.get("summary", ""),
                "issues": analysis.get("issues", []),
                "improvements": analysis.get("improvements", []),
                "recommendation": analysis.get("recommendation", {}).get("action", "no_action") if isinstance(analysis.get("recommendation"), dict) else analysis.get("recommendation", "no_action"),
                "justification": analysis.get("recommendation", {}).get("justification", "") if isinstance(analysis.get("recommendation"), dict) else "",
                "suggested_title": analysis.get("recommendation", {}).get("suggested_title", "") if isinstance(analysis.get("recommendation"), dict) else "",
                "labels": analysis.get("recommendation", {}).get("labels", []) if isinstance(analysis.get("recommendation"), dict) else [],
                "stats": stats,
                "diff": params.get("diff", "")[:5000],
                "files": files,
                "branch": branch,
            }

            result_json = json.dumps(review_result)
            task.artifacts = [{"parts": [{"type": "text", "text": result_json}]}]
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                message={"role": "agent", "content": {"type": "text", "text": result_json}},
            )

        except Exception as e:
            error_msg = f"Reviewer agent error: {type(e).__name__}: {str(e)}"
            Console.error(error_msg)
            error_json = json.dumps({"error": error_msg, "status": "failed", "traceback": str(e)})
            task.artifacts = [{"parts": [{"type": "text", "text": error_json}]}]
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"type": "text", "text": error_json}},
            )

        return task


if __name__ == "__main__":
    port = int(os.environ.get("REVIEWER_PORT", "5001"))
    url = f"http://localhost:{port}"
    server = ReviewerAgentServer(url=url)
    print(f"[A2A] Reviewer Agent starting on port {port}")
    run_server(server, port=port)
