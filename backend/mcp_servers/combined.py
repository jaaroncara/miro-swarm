"""Combined MCP server for business data tools and simulation task tools.

Recommended default entrypoint for OASIS runs:
    python -m mcp_servers.combined
"""

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP


_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import mcp_servers.example as business_tools
import mcp_servers.task_server as task_tools


mcp = FastMCP("combined-tools")


def _register_tool(server: FastMCP, name: str, fn) -> None:
    server.tool(name=name)(fn)


for tool_name, tool_fn in [
    ("lookup_business_data", business_tools.lookup_business_data),
    ("add", business_tools.add),
    ("subtract", business_tools.subtract),
    ("multiply", business_tools.multiply),
    ("divide", business_tools.divide),
    ("calculate_standard_deviation", business_tools.calculate_standard_deviation),
    ("calculate_min", business_tools.calculate_min),
    ("calculate_max", business_tools.calculate_max),
    ("calculate_average", business_tools.calculate_average),
    ("calculate_mode", business_tools.calculate_mode),
    ("basic_news_search", business_tools.basic_news_search),
    ("basic_web_search", business_tools.basic_web_search),
    ("offer_task", task_tools.offer_task),
    ("accept_task", task_tools.accept_task),
    ("decline_task", task_tools.decline_task),
    ("get_task", task_tools.get_task),
    ("list_my_tasks", task_tools.list_my_tasks),
    ("start_task", task_tools.start_task),
    ("block_task", task_tools.block_task),
    ("complete_task", task_tools.complete_task),
    ("save_task_artifact", task_tools.save_task_artifact),
]:
    _register_tool(mcp, tool_name, tool_fn)


if __name__ == "__main__":
    mcp.run(transport="stdio")
