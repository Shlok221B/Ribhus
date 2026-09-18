#!/usr/bin/env python3
"""Tiny MCP demo server for Ribhus (`ribhus mcp` / local tests).

Run standalone:
  uv run python examples/mcp_demo_server.py
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("ribhus-demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back (useful to verify MCP wiring)."""
    return f"echo: {message}"


@mcp.tool()
def greeter(name: str = "friend") -> str:
    """Return a short Ribhus-flavoured greeting."""
    return f"Namaste, {name} — the Ribhus are crafting."


if __name__ == "__main__":
    mcp.run()
