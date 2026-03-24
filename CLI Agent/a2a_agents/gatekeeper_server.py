"""
A2A Gatekeeper Agent Server — enforces approval, saves/loads drafts.

The gatekeeper handles:
  - gate: save a draft for human review
  - reject: reject a pending draft
  - publish: (handled by orchestrator via MCP GitHub tools)
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_a2a import A2AServer, skill, agent, run_server, TaskStatus, TaskState


_CLI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DRAFT_FILE = os.path.join(_CLI_DIR, ".agent_draft.json")


@agent(
    name="Gatekeeper Agent",
    description="Enforces human approval before publishing. Saves drafts locally for review.",
    version="2.0.0",
)
class GatekeeperAgentServer(A2AServer):

<<<<<<< HEAD
    def __init__(self, url: str = None, **kwargs):
        if url:
            kwargs['url'] = url
        super().__init__(**kwargs)
=======
    def __init__(self):
        port = int(os.environ.get("GATEKEEPER_PORT", "5005"))
        super().__init__(url=f"http://localhost:{port}")
>>>>>>> a85e6e12bfdc907914c9af95aec89666dd0a6c03

    @skill(
        name="Gate Draft",
        description="Save a draft for human approval/rejection",
        tags=["gate", "approval", "draft"],
    )
    def gate(self):
        pass

    @skill(
        name="Reject Draft",
        description="Reject a pending draft without publishing",
        tags=["reject", "draft"],
    )
    def reject(self):
        pass

    def handle_task(self, task):
        message_data = task.message or {}
        content = message_data.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)

        try:
            params = json.loads(text) if text else {}
        except (json.JSONDecodeError, TypeError):
            params = {}

        action = params.get("action", "gate")

        try:
            if action == "gate":
                result = self._gate(params)
            elif action == "reject":
                result = self._reject(params)
            else:
                result = {"status": "unknown_action", "action": action}

            result_json = json.dumps(result)
            task.artifacts = [{"parts": [{"type": "text", "text": result_json}]}]
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                message={"role": "agent", "content": {"type": "text", "text": result_json}}
            )

        except Exception as e:
            error_json = json.dumps({"error": str(e), "status": "failed"})
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"type": "text", "text": error_json}},
            )

        return task

    def _gate(self, params: dict) -> dict:
        """Save draft to disk for human review."""
        draft = params.get("draft", {})
        reflection = params.get("reflection", {})

        saved = {
            "draft": draft,
            "reflection": reflection,
            "head_branch": params.get("head_branch", ""),
            "base_branch": params.get("base_branch", "main"),
            "as_draft_pr": params.get("as_draft_pr", False),
        }

        with open(_DRAFT_FILE, "w") as f:
            json.dump(saved, f, indent=2)

        return {"status": "saved", "path": _DRAFT_FILE}

    def _reject(self, params: dict) -> dict:
        """Delete saved draft."""
        if os.path.exists(_DRAFT_FILE):
            os.remove(_DRAFT_FILE)
        return {"status": "rejected"}


if __name__ == "__main__":
    port = int(os.environ.get("GATEKEEPER_PORT", "5005"))
    url = f"http://localhost:{port}"
    server = GatekeeperAgentServer(url=url)
    print(f"[A2A] Gatekeeper Agent starting on port {port}")
    run_server(server, port=port)
