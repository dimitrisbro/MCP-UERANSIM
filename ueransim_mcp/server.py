"""UERANSIM MCP Server entry point.

Imports docker_tools and k8s_tools as side effects so their @mcp.tool()
decorators register all 24 tools with the shared FastMCP instance in app.py.
"""

from .app import mcp
from . import docker_tools, k8s_tools  # noqa: F401 — registers all tools


def start_server():
    mcp.run()


if __name__ == "__main__":
    start_server()
