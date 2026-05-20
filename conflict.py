# MCP hub: local tools + external servers (GitHub npx, Postman HTTP).
# Run directly: python conflict.py

import os
import shutil
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from fastmcp.server import create_proxy

load_dotenv()

mcp = FastMCP("IntegrationHub")


@mcp.tool()
def hub_ping():
    """Check that this hub is running."""
    return "pong from hub"


@mcp.tool()
def hub_echo(message: str):
    """Echo text back."""
    return message


EXTERNAL_SERVERS = [
    {
        "namespace": "github",
        "connection": "stdio",
        "package": "@modelcontextprotocol/server-github",
        "env_keys": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    },
    {
        "namespace": "postman",
        "connection": "http",
        "url": "https://mcp.postman.com/mcp",
        "env_keys": ["POSTMAN_API_KEY"],
    },
    {
        "namespace": "brave",
        "connection": "stdio",
        "package": "@modelcontextprotocol/server-brave-search",
        "env_keys": ["BRAVE_API_KEY"],
    }
]


def has_required_env(env_keys):
    if not env_keys:
        return True
    for key in env_keys:
        if not os.getenv(key):
            return False
    return True


def build_env_for_subprocess(env_keys):
    env = os.environ.copy()
    for key in env_keys:
        value = os.getenv(key)
        if value:
            env[key] = value
    return env


def make_transport(server):
    connection = server.get("connection", "stdio")

    if connection == "http":
        api_key = os.getenv(server["env_keys"][0])
        return StreamableHttpTransport(
            url=server["url"],
            auth=api_key,
        )

    return StdioTransport(
        command="npx",
        args=["-y", server["package"]],
        env=build_env_for_subprocess(server.get("env_keys", [])),
    )


def mount_external_servers():
    for server in EXTERNAL_SERVERS:
        name = server["namespace"]
        env_keys = server.get("env_keys", [])

        if not has_required_env(env_keys):
            keys = ", ".join(env_keys) if env_keys else "n/a"
            print(f"Skipping {name} — set these in .env: {keys}")
            continue

        try:
            label = server.get("package") or server.get("url", "remote")
            print(f"Mounting {name} ({label})...")
            transport = make_transport(server)
            proxy = create_proxy(transport, name=name)
            mcp.mount(proxy, namespace=name)
            print(f"Mounted {name} — tools start with {name}_")
        except Exception as err:
            print(f"Failed to mount {name}: {err}")


if __name__ == "__main__":
    if shutil.which("npx") is None:
        print("Error: npx not found. Install Node.js (needed for GitHub MCP).")
        sys.exit(1)

    mount_external_servers()
    print("Starting integration hub...")
    mcp.run()
