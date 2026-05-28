# MCP hub — mounts servers from servers.py. Run: python mcp_hub.py

import os
import shutil
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from fastmcp.server import create_proxy

from servers import EXTERNAL_SERVERS

load_dotenv()

mcp = FastMCP("IntegrationHub")
MOUNT_STATUS = []


@mcp.tool()
def hub_ping():
    """Check that this hub is running."""
    return "pong from hub"


@mcp.tool()
def hub_echo(message: str):
    """Echo text back."""
    return message


def _env_ready(env_keys):
    return all(os.getenv(k) for k in env_keys) if env_keys else True


def _child_env(server):
    env = os.environ.copy()
    for key in server.get("env_unset") or []:
        env.pop(key, None)
    env_keys = server.get("env_keys", [])
    for key in env_keys:
        val = os.getenv(key)
        if val:
            env[key] = val
    for target, source in (server.get("env_map") or {}).items():
        val = os.getenv(source)
        if val:
            env[target] = val
    for key, val in (server.get("env_defaults") or {}).items():
        env.setdefault(key, val)
    return env


def _transport(server):
    if server["connection"] == "http":
        transport = StreamableHttpTransport(url=server["url"])
        env_keys = server.get("env_keys", [])
        token = os.getenv(env_keys[0]) if env_keys else None
        if token:
            transport = StreamableHttpTransport(
                url=server["url"],
                headers={"Authorization": f"Bearer {token}"},
            )
        return transport

    return StdioTransport(
        command="npx",
        args=["-y", server["package"]],
        env=_child_env(server),
    )


def mount_external_servers():
    MOUNT_STATUS.clear()
    MOUNT_STATUS.append(
        {
            "namespace": "hub",
            "title": "Hub (local)",
            "status": "ready",
            "detail": "Local tools always available",
        }
    )

    for s in EXTERNAL_SERVERS:
        name = s["namespace"]
        env_keys = s.get("env_keys", [])
        entry = {
            "namespace": name,
            "title": s.get("title") or name,
            "connection": s.get("connection"),
            "source": s.get("package") or s.get("url", ""),
            "env_keys": env_keys,
        }

        if not _env_ready(env_keys):
            entry["status"] = "skipped"
            entry["detail"] = f"Missing .env: {', '.join(env_keys)}"
            MOUNT_STATUS.append(entry)
            print(f"Skipping {name} — set in .env: {', '.join(env_keys)}")
            continue

        try:
            label = entry["source"]
            print(f"Mounting {name} ({label})...")
            mcp.mount(create_proxy(_transport(s), name=name), namespace=name)
            entry["status"] = "mounted"
            entry["detail"] = f"Tools prefixed with {name}_"
            print(f"Mounted {name}")
        except Exception as err:
            entry["status"] = "failed"
            entry["detail"] = str(err)
            print(f"Failed to mount {name}: {err}")

        MOUNT_STATUS.append(entry)

    return MOUNT_STATUS


if __name__ == "__main__":
    if shutil.which("npx") is None:
        print("Error: npx not found. Install Node.js for stdio MCP servers.")
        sys.exit(1)
    mount_external_servers()
    print("Starting MCP hub...")
    mcp.run()
