"""
MCP Client Wrapper — connects to MCP tool servers via stdio transport.

Provides a simple synchronous interface for agents to call MCP tools:
  client = MCPToolClient()
  result = client.call("git_diff", {"commit_range": "HEAD~3..HEAD"})

Manages lifecycle of MCP server subprocesses.
"""

import asyncio
import json
import os
import sys
from typing import Optional

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Path to this package's directory
_SERVERS_DIR = os.path.dirname(os.path.abspath(__file__))
_CLI_DIR = os.path.dirname(_SERVERS_DIR)


class MCPToolClient:
    """Synchronous wrapper around MCP stdio clients for git and github tool servers."""

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

        # Cached tool listings
        self._git_tools: list[str] = []
        self._github_tools: list[str] = []

    def _git_env(self) -> dict:
        env = os.environ.copy()
        env["GIT_REPO_PATH"] = self.repo_path
        env["PYTHONPATH"] = _CLI_DIR + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def _github_env(self) -> dict:
        env = os.environ.copy()
        env["GITHUB_TOKEN"] = self.github_token
        env["GITHUB_OWNER"] = self.github_owner
        env["GITHUB_REPO"] = self.github_repo
        env["PYTHONPATH"] = _CLI_DIR + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def _git_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(_SERVERS_DIR, "mcp_git_server.py")],
            env=self._git_env(),
        )

    def _github_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(_SERVERS_DIR, "mcp_github_server.py")],
            env=self._github_env(),
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def call_git_tool(self, tool_name: str, arguments: dict = None) -> any:
        """Call a git MCP tool and return the parsed result."""
        return self._run_async(self._call_tool(self._git_params(), tool_name, arguments or {}))

    def call_github_tool(self, tool_name: str, arguments: dict = None) -> any:
        """Call a github MCP tool and return the parsed result."""
        return self._run_async(self._call_tool(self._github_params(), tool_name, arguments or {}))

    def list_git_tools(self) -> list[str]:
        """List available git MCP tools."""
        if not self._git_tools:
            self._git_tools = self._run_async(self._list_tools(self._git_params()))
        return self._git_tools

    def list_github_tools(self) -> list[str]:
        """List available github MCP tools."""
        if not self._github_tools:
            self._github_tools = self._run_async(self._list_tools(self._github_params()))
        return self._github_tools

    # ── Async internals ────────────────────────────────────────────────────

    async def _call_tool(self, params: StdioServerParameters, tool_name: str, arguments: dict) -> any:
        """Connect to an MCP server, call a tool, return the result."""
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(tool_name, arguments=arguments)

                # Extract text content from result
                if result.content:
                    for block in result.content:
                        if isinstance(block, types.TextContent):
                            # Try to parse as JSON, otherwise return raw text
                            try:
                                return json.loads(block.text)
                            except (json.JSONDecodeError, TypeError):
                                return block.text
                return None

    async def _list_tools(self, params: StdioServerParameters) -> list[str]:
        """Connect to an MCP server and list available tools."""
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]

    @staticmethod
    def _run_async(coro):
        """Run an async coroutine from synchronous code."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already in an async context — use a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)
