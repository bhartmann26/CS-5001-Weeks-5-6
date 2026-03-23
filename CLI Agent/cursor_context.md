# Context for Cursor: GitHub AI Agent A2A + Ollama Protocol Integration

## Objective
Convert our existing CLI-based GitHub Review Agent (which uses direct Python function calls) into a protocol-based system using:
1. **MCP (Model Context Protocol)** for tool servers (Git & GitHub APIs).
2. **A2A (Google's Agent2Agent Protocol) using the `python-a2a` package** for agent communication.

## Current State (Updated)
We have successfully implemented the MCP servers and A2A Agent Servers (`Reviewer`, `Planner`, `Writer`, `Critic`, `Gatekeeper`). The orchestrator (`a2a_agents/orchestrator.py`) starts these on ports 5001-5005.

**Fixed:** Agent servers were crashing on startup because `A2AServer` requires a `url` for the agent card. All 5 agents now pass `url=f"http://localhost:{port}"` in `super().__init__()`. The orchestrator connection check, wait time (6s), and response parsing have also been improved. Windows console encoding is handled for ✓/✗ symbols.

**Note:** Runs can be slow (Ollama + llama3.2:3b on large diffs). If results show "unknown" for category/risk/summary, check that Ollama is returning valid JSON matching the expected schema.

## Reference Article Provided by User
The user found an implementation guide that perfectly describes how to handle A2A with Ollama:
[Medium Article: Ollama Implementation of A2A (Googles Agent2Agent Protocol)](https://medium.com/@CorticalFlow/googles-agent2agent-a2a-protocol-implementation-with-ollama-integration-27f1c9f2d4d3)

### Key Learnings from the Article to Apply:
1. **Message Format**: A2A expects messages to be formatted with an `id`, `role`, and `parts` array. Inside `parts`, there must be `{"type": "text", "content": "..."}`.
2. **Handling Prompts**: Instead of just tossing a string, the agent needs to carefully parse the incoming A2A `parts` list, concatenate the `text` types, and build the Ollama prompt.
3. **Sending Responses**: The agent MUST wrap the Ollama response inside an A2A-compliant message structure before marking the task as `completed` and returning it.

## Where to Focus
Look at **`a2a_agents/reviewer_server.py`** and **`a2a_agents/orchestrator.py`**.

In `reviewer_server.py` (`handle_task` method), the agent attempts to read `task.message` and then dump its JSON response into `task.artifacts` and `task.status.message`. This is likely not compliant with the strict A2A Protocol schema for message passing as demonstrated in the Medium article.

In `orchestrator.py` (`_send_task` method), the orchestrator gets the `response` object from `client.ask()` and tries to cast it to `str()` or access `response.message.get("content", {})`. This parsing logic needs to match whatever the agent explicitly returns based on standard A2A behavior.

### Next Steps for Cursor
1. Review the Medium article content (included in this repository context or accessible via the URL).
2. Refactor `reviewer_server.py` to properly parse incoming A2A `parts` and format outgoing Ollama JSON responses as A2A-compliant messages.
3. Clean up `orchestrator.py` so it correctly reads the `parts` array from the `response` object returned by `A2AClient.ask()`.
4. Apply this pattern to the other agents (`planner`, `writer`, `critic`, `gatekeeper`).
