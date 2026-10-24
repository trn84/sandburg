"""Placeholder MCP server for disabled Sandburg services.

The Claude Code plugin always connects all services. So that a disabled service
doesn't show up there as a connection error, this server answers in its place
with a single tool that explains how to enable the service.

Usage: sandburg-disabled-mcp <service> <ENABLE_VARIABLE>
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer


def build(service: str, env_var: str) -> MCPServer:
    message = (
        f"The Sandburg service '{service}' is disabled. To enable it, set the "
        f"environment variable {env_var}=1 on the pod (on RunPod in the template under "
        "Environment Variables) and restart the pod."
    )
    server = MCPServer(name=f"sandburg-{service}-disabled", instructions=message)

    @server.tool(name=f"{service}_status")
    def status() -> str:
        """Shows that this service is disabled and how to enable it."""
        return message

    return server


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: sandburg-disabled-mcp <service> <ENABLE_VARIABLE>")
    build(sys.argv[1], sys.argv[2]).run("stdio")


if __name__ == "__main__":
    main()
