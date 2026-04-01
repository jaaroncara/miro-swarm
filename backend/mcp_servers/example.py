"""
Example MCP Server
A lightweight demonstration MCP server that exposes two tools:

  - lookup_sales_data: Returns mock quarterly sales figures for a region.
  - calculator: Performs basic arithmetic and statistical calculations.

Usage (stdio transport — this is how MCPManager launches it):
    python -m mcp_servers.example

Or directly:
    python backend/mcp_servers/example.py
"""

from mcp.server.fastmcp import FastMCP
import math
import os
import statistics
from typing import List
from langchain_tavily import TavilySearch

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

mcp = FastMCP("example-tools")


# ---------- Tool 1: Sales Database Lookup ----------

_MOCK_SALES = {
    ("north america", "q1"): {"revenue": 12500000, "units": 45000, "growth": "+8%"},
    ("north america", "q2"): {"revenue": 14200000, "units": 51000, "growth": "+13%"},
    ("canada", "q1"): {"revenue": 9800000, "units": 32000, "growth": "+5%"},
    ("canada", "q2"): {"revenue": 10100000, "units": 34000, "growth": "+3%"},
    ("latin america", "q1"): {"revenue": 7600000, "units": 28000, "growth": "+11%"},
    ("latin america", "q2"): {"revenue": 8400000, "units": 31000, "growth": "+10%"},
}


@mcp.tool()
def lookup_sales_data(region: str, quarter: str) -> str:
    """
    Query the sales database for revenue, units sold, and YoY growth.

    Args:
        region: Geographic region (e.g. "North America", "Canada", "Latin America")
        quarter: Fiscal quarter (e.g. "Q1", "Q2")
    """
    key = (region.lower().strip(), quarter.lower().strip())
    data = _MOCK_SALES.get(key)
    if data is None:
        return f"No sales data found for region='{region}', quarter='{quarter}'."
    return (
        f"Sales data for {region} {quarter}:\n"
        f"  Revenue:  ${data['revenue']:,}\n"
        f"  Units:    {data['units']:,}\n"
        f"  YoY Growth: {data['growth']}"
    )


# ---------- Tool 2: Calculator ----------

@mcp.tool()
def add(a: float, b: float) -> str:
    """
    Add two numbers.
    """
    return str(a + b)

@mcp.tool()
def subtract(a: float, b: float) -> str:
    """
    Subtract the second number from the first.
    """
    return str(a - b)

@mcp.tool()
def multiply(a: float, b: float) -> str:
    """
    Multiply two numbers.
    """
    return str(a * b)

@mcp.tool()
def divide(a: float, b: float) -> str:
    """
    Divide the first number by the second.
    """
    if b == 0:
        return "Error: Division by zero."
    return str(a / b)

@mcp.tool()
def calculate_standard_deviation(numbers: List[float]) -> str:
    """
    Calculate the standard deviation of a list of numbers.
    """
    if len(numbers) < 2:
        return "Error: Standard deviation requires at least two data points."
    return str(statistics.stdev(numbers))

@mcp.tool()
def calculate_min(numbers: List[float]) -> str:
    """
    Find the minimum value in a list of numbers.
    """
    if not numbers:
        return "Error: List is empty."
    return str(min(numbers))

@mcp.tool()
def calculate_max(numbers: List[float]) -> str:
    """
    Find the maximum value in a list of numbers.
    """
    if not numbers:
        return "Error: List is empty."
    return str(max(numbers))

@mcp.tool()
def calculate_average(numbers: List[float]) -> str:
    """
    Calculate the average (mean) of a list of numbers.
    """
    if not numbers:
        return "Error: List is empty."
    return str(statistics.mean(numbers))

@mcp.tool()
def calculate_mode(numbers: List[float]) -> str:
    """
    Calculate the mode of a list of numbers.
    """
    if not numbers:
        return "Error: List is empty."
    try:
        return str(statistics.mode(numbers))
    except statistics.StatisticsError:
        return "Error: No unique mode."
    
@mcp.tool()
def basic_news_search(query):
    """Search the web for recent news using the Tavily Web Search API."""
    tavily = TavilySearch(max_results=2, topic="news", tavily_api_key=TAVILY_API_KEY)
    return {"messages": tavily.invoke(query)}
    
@mcp.tool()
def basic_web_search(query):
    """Search the web for general topics using the Tavily Web Search API."""
    tavily = TavilySearch(max_results=2, topic="general", tavily_api_key=TAVILY_API_KEY)
    return {"messages": tavily.invoke(query)}

if __name__ == "__main__":
    mcp.run(transport="stdio")
