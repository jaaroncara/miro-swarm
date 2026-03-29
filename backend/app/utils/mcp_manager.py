"""
MCP (Model Context Protocol) Manager
Singleton that manages a local MCP server subprocess via stdio transport.

Provides:
- Lifecycle management: start/stop the MCP server subprocess
- Tool catalog: discover available tools and convert to OpenAI-compatible schemas
- Tool execution: call tools with concurrency protection for parallel OASIS agents
- Report-agent helpers: plain-text descriptions for the ReACT string-parsing loop
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from ..config import Config
from .logger import get_logger

logger = get_logger('mirofish.mcp_manager')


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_instance: Optional['MCPManager'] = None
_instance_lock: Optional[asyncio.Lock] = None  # created lazily inside the running event loop


async def get_mcp_manager() -> 'MCPManager':
    """Return the global MCPManager, creating it on first call."""
    global _instance, _instance_lock
    if _instance_lock is None:
        _instance_lock = asyncio.Lock()
    async with _instance_lock:
        if _instance is None:
            _instance = MCPManager()
        if not _instance.is_connected:
            await _instance.connect()
        return _instance


def get_mcp_manager_sync() -> Optional['MCPManager']:
    """Non-async accessor — returns the cached instance or *None*."""
    return _instance


async def shutdown_mcp_manager() -> None:
    """Shut down the global MCP manager (call at app teardown)."""
    global _instance
    if _instance is not None:
        await _instance.disconnect()
        _instance = None


# ---------------------------------------------------------------------------
# OpenAI-compatible schema helpers
# ---------------------------------------------------------------------------

def _mcp_schema_to_openai_tool(tool) -> Dict[str, Any]:
    """
    Convert an MCP Tool object to the OpenAI function-calling schema.

    MCP tools expose ``name``, ``description``, and ``inputSchema`` (JSON Schema).
    We wrap that into the ``{"type": "function", "function": {...}}`` format
    expected by the OpenAI Chat Completions API.
    """
    input_schema = tool.inputSchema if hasattr(tool, 'inputSchema') else {}
    # Ensure we have a valid JSON Schema object
    if not isinstance(input_schema, dict):
        input_schema = {}

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": input_schema or {"type": "object", "properties": {}},
        },
    }


def _mcp_tools_to_react_description(tools) -> str:
    """
    Render MCP tools as a plain-text block suitable for injection into
    the ReACT prompt used by the report agent.

    Example output::

        - mcp__lookup_sales_data: Query the sales database for metrics.
          Parameters: region (string), quarter (string)
    """
    parts: list[str] = []
    for tool in tools:
        input_schema = tool.inputSchema if hasattr(tool, 'inputSchema') else {}
        props = (input_schema or {}).get("properties", {})
        if props:
            param_strs = []
            for pname, pschema in props.items():
                ptype = pschema.get("type", "any")
                pdesc = pschema.get("description", "")
                param_strs.append(f"{pname} ({ptype}): {pdesc}" if pdesc else f"{pname} ({ptype})")
            params_line = f"  Parameters: {', '.join(param_strs)}"
        else:
            params_line = "  Parameters: (none)"
        parts.append(f"- mcp__{tool.name}: {tool.description or '(no description)'}")
        parts.append(params_line)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# MCPManager
# ---------------------------------------------------------------------------

class MCPManager:
    """
    Manages a single MCP server subprocess over stdio transport.

    The manager is safe for concurrent use: an ``asyncio.Semaphore`` gates
    how many tool calls can be in-flight at once (defaults to 5).
    """

    def __init__(
        self,
        server_cmd: Optional[str] = None,
        server_args: Optional[List[str]] = None,
        timeout: Optional[int] = None,
        max_concurrent: int = 5,
    ):
        self._server_cmd = server_cmd or Config.MCP_SERVER_CMD
        self._server_args = server_args if server_args is not None else list(Config.MCP_SERVER_ARGS)
        self._timeout = timeout or Config.MCP_TOOL_CALL_TIMEOUT
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # MCP SDK objects (populated on connect)
        self._session: Any = None
        self._stdio_transport: Any = None  # context manager wrapper
        self._tools: List[Any] = []        # list of mcp.types.Tool
        self._tools_by_name: Dict[str, Any] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # event loop owning the session

        self.is_connected = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Launch the MCP server subprocess and initialise the session."""
        if self.is_connected:
            return

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise ImportError(
                "The 'mcp' package is required for MCP tool support. "
                "Install with: pip install mcp"
            )

        cmd = self._server_cmd
        args = self._server_args

        if not cmd:
            raise ValueError(
                "MCP_SERVER_CMD is not configured.  Set MCP_SERVER_CMD and "
                "MCP_SERVER_ARGS in your .env to point to a local MCP server."
            )

        logger.info(f"Starting MCP server: {cmd} {' '.join(args)}")

        server_params = StdioServerParameters(
            command=cmd,
            args=args,
            env={**os.environ},  # inherit the host env
        )

        # ``stdio_client`` returns an async context-manager that yields
        # (read_stream, write_stream).  We need to keep the CM alive for
        # the lifetime of the manager, so we enter it manually.
        self._stdio_cm = stdio_client(server_params)
        streams = await self._stdio_cm.__aenter__()
        read_stream, write_stream = streams

        self._session = ClientSession(read_stream, write_stream)
        await self._session.__aenter__()
        await self._session.initialize()

        # Discover tools
        result = await self._session.list_tools()
        self._tools = result.tools
        self._tools_by_name = {t.name: t for t in self._tools}

        self.is_connected = True
        self._loop = asyncio.get_running_loop()
        logger.info(
            f"MCP connected — {len(self._tools)} tool(s) available: "
            f"{[t.name for t in self._tools]}"
        )

    async def disconnect(self) -> None:
        """Tear down the MCP session and server subprocess."""
        if not self.is_connected:
            return

        try:
            if self._session is not None:
                await self._session.__aexit__(None, None, None)
            if self._stdio_cm is not None:
                await self._stdio_cm.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning(f"Error during MCP disconnect: {exc}")
        finally:
            self._session = None
            self._stdio_cm = None
            self._tools = []
            self._tools_by_name = {}
            self._loop = None
            self.is_connected = False
            logger.info("MCP disconnected")

    # ------------------------------------------------------------------
    # Tool catalog
    # ------------------------------------------------------------------

    def get_tools(self) -> List[Any]:
        """Return the raw MCP tool objects."""
        return list(self._tools)

    def get_openai_tools_schema(self) -> List[Dict[str, Any]]:
        """Return tool definitions as OpenAI-compatible function schemas."""
        return [_mcp_schema_to_openai_tool(t) for t in self._tools]

    def get_react_tools_description(self) -> str:
        """Return a plain-text block describing MCP tools (for the ReACT prompt)."""
        return _mcp_tools_to_react_description(self._tools)

    def has_tools(self) -> bool:
        return len(self._tools) > 0

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        Execute a single MCP tool and return the text result.

        Concurrency is bounded by the internal semaphore so that many
        OASIS agents can safely issue tool calls in parallel.

        Args:
            name: Tool name (must match a tool in the catalog).
            arguments: JSON-serialisable arguments dict.

        Returns:
            The concatenated text content returned by the tool.

        Raises:
            ValueError: If the tool name is unknown.
            TimeoutError: If the tool does not respond within the timeout.
        """
        if not self.is_connected:
            raise RuntimeError("MCPManager is not connected. Call connect() first.")

        if name not in self._tools_by_name:
            raise ValueError(
                f"Unknown MCP tool '{name}'. Available: {list(self._tools_by_name)}"
            )

        async with self._semaphore:
            logger.info(f"MCP call_tool: {name}({json.dumps(arguments, ensure_ascii=False)[:200]})")
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool(name, arguments),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                msg = f"MCP tool '{name}' timed out after {self._timeout}s"
                logger.warning(msg)
                raise TimeoutError(msg)

            # Concatenate text content blocks
            text_parts = []
            for block in result.content:
                if hasattr(block, 'text'):
                    text_parts.append(block.text)
                elif hasattr(block, 'data'):
                    text_parts.append(f"[binary data: {len(block.data)} bytes]")

            output = "\n".join(text_parts) if text_parts else "(empty result)"
            logger.debug(f"MCP result for {name}: {output[:300]}")
            return output

    def call_tool_sync(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        Synchronous wrapper around ``call_tool`` for use in non-async contexts
        (e.g. the report agent's ReACT loop or OASIS simulation step).

        If the MCP session lives on a *different* event loop (typical when the
        manager was bootstrapped in a daemon thread), we use
        ``run_coroutine_threadsafe`` to dispatch the call there.
        """
        coro = self.call_tool(name, arguments)

        # Fast path: no loop running → we can block directly
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is None:
            # No event loop in the current thread — safe to block
            if self._loop is not None and self._loop.is_running():
                future = asyncio.run_coroutine_threadsafe(coro, self._loop)
                return future.result(timeout=self._timeout + 5)
            return asyncio.get_event_loop().run_until_complete(coro)

        # There IS a running loop.  Dispatch to the session's own loop if it
        # differs, or await inline if they're the same (caller must await).
        if self._loop is not None and self._loop is not running_loop:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=self._timeout + 5)

        # Same loop — we can't block; the caller must be async and should use
        # call_tool() directly.  As a fallback, raise an informative error.
        raise RuntimeError(
            "call_tool_sync() called from the same event loop that owns the "
            "MCP session.  Use 'await mgr.call_tool(...)' instead."
        )
