"""
MCP Client — calls MCP tool functions defined in the MCP server modules.

Uses in-process invocation of @mcp.tool() decorated functions for reliability
on Windows (stdio transport has async subprocess issues on Windows).

The MCP tool definitions remain in mcp_git_server.py and mcp_github_server.py
using FastMCP and @mcp.tool() decorators — this client imports and calls them.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MCPToolClient:
    """Calls MCP tool functions defined in the MCP server modules."""

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

        # Set env vars that MCP servers read
        os.environ["GIT_REPO_PATH"] = self.repo_path
        if github_token:
            os.environ["GITHUB_TOKEN"] = github_token
        if github_owner:
            os.environ["GITHUB_OWNER"] = github_owner
        if github_repo:
            os.environ["GITHUB_REPO"] = github_repo

        # Import MCP tool modules (they register @mcp.tool() functions)
        import mcp_servers.mcp_git_server as git_server
        import mcp_servers.mcp_github_server as github_server

        # Map tool names to the actual @mcp.tool() functions
        self._git_tools = {
            "git_current_branch": git_server.git_current_branch,
            "git_diff": git_server.git_diff,
            "git_staged_diff": git_server.git_staged_diff,
            "git_files_changed": git_server.git_files_changed,
            "git_recent_commits": git_server.git_recent_commits,
            "git_diff_stats": git_server.git_diff_stats,
            "git_untracked_files": git_server.git_untracked_files,
            "git_remote_url": git_server.git_remote_url,
        }

        self._github_tools = {
            "github_get_issue": github_server.github_get_issue,
            "github_create_issue": github_server.github_create_issue,
            "github_update_issue": github_server.github_update_issue,
            "github_get_pr": github_server.github_get_pr,
            "github_create_pr": github_server.github_create_pr,
            "github_update_pr": github_server.github_update_pr,
            "github_verify_token": github_server.github_verify_token,
            "github_list_branches": github_server.github_list_branches,
        }

    def call_git_tool(self, tool_name: str, arguments: dict = None) -> any:
        """Call an MCP git tool by name."""
        func = self._git_tools.get(tool_name)
        if not func:
            raise ValueError(f"Unknown git tool: {tool_name}. Available: {list(self._git_tools.keys())}")
        return func(**(arguments or {}))

    def call_github_tool(self, tool_name: str, arguments: dict = None) -> any:
        """Call an MCP github tool by name."""
        func = self._github_tools.get(tool_name)
        if not func:
            raise ValueError(f"Unknown github tool: {tool_name}. Available: {list(self._github_tools.keys())}")
        return func(**(arguments or {}))

    def list_git_tools(self) -> list[str]:
        """List available MCP git tools."""
        return list(self._git_tools.keys())

    def list_github_tools(self) -> list[str]:
        """List available MCP github tools."""
        return list(self._github_tools.keys())
