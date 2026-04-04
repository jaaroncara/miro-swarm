"""Quick smoke-test for the MCP Manager integration.

Mirrors the real deployment: the MCPManager lives on a background daemon
thread with its own event loop, and the call_tool_sync calls come from the
main thread (no running event loop), exactly as in an OASIS simulation step
or a Flask request handler.
"""

import asyncio
import os
import sys
import threading
import time

# Env overrides (so we don't need a .env change for this test)
os.environ['MCP_SERVER_ENABLED'] = 'true'
os.environ['MCP_SERVER_CMD'] = 'python3'
os.environ['MCP_SERVER_ARGS'] = 'mcp_servers/example.py'

# Ensure the backend package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.utils.mcp_manager import MCPManager, shutdown_mcp_manager


def main():
    # ---------------------------------------------------------------
    # 1. Boot the MCPManager on a daemon thread (same as _start_mcp_server)
    # ---------------------------------------------------------------
    mgr = MCPManager()
    ready = threading.Event()

    def _daemon():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(mgr.connect())
        ready.set()
        loop.run_forever()  # keep processing coroutines

    t = threading.Thread(target=_daemon, daemon=True)
    t.start()
    ready.wait(timeout=15)

    assert mgr.is_connected, "Failed to connect to MCP server"
    print(f"Connected: {mgr.is_connected}")
    print(f"Tools: {[t.name for t in mgr.get_tools()]}")
    print()

    # ---------------------------------------------------------------
    # 2. OpenAI schema generation
    # ---------------------------------------------------------------
    schemas = mgr.get_openai_tools_schema()
    for s in schemas:
        fn = s["function"]
        props = list(fn["parameters"].get("properties", {}).keys())
        print(f"OpenAI schema: {fn['name']} -> {props}")
    print()

    # ---------------------------------------------------------------
    # 3. ReACT description
    # ---------------------------------------------------------------
    desc = mgr.get_react_tools_description()
    print(f"ReACT description:\n{desc}")
    print()

    # ---------------------------------------------------------------
    # 4. Synchronous tool calls (main thread — no event loop)
    # ---------------------------------------------------------------
    result1 = mgr.call_tool_sync("add", {"a": 5, "b": 3})
    print(f"call_tool_sync (add):\n{result1}")

    result2 = mgr.call_tool_sync("lookup_business_data", {"dataset": "sales", "region": "North America", "quarter": "Q1"})
    print(f"\ncall_tool_sync (lookup_business_data):\n{result2}")

    # ---------------------------------------------------------------
    # 5. Cleanup
    # ---------------------------------------------------------------
    # Submit disconnect to the daemon loop
    asyncio.run_coroutine_threadsafe(mgr.disconnect(), mgr._loop).result(timeout=10)
    print("\nShutdown OK — all tests passed!")


if __name__ == "__main__":
    main()
