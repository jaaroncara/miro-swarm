"""
Example MCP Server
A lightweight demonstration MCP server that exposes two tools:

  - lookup_sales_data: Returns mock quarterly sales figures for a region.
  - get_weather: Returns mock weather data for a city.

Usage (stdio transport — this is how MCPManager launches it):
    python -m mcp_servers.example

Or directly:
    python backend/mcp_servers/example.py
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("example-tools")


# ---------- Tool 1: Sales Database Lookup ----------

_MOCK_SALES = {
    ("north america", "q1"): {"revenue": 12_500_000, "units": 45_000, "growth": "+8%"},
    ("north america", "q2"): {"revenue": 14_200_000, "units": 51_000, "growth": "+13%"},
    ("europe", "q1"): {"revenue": 9_800_000, "units": 32_000, "growth": "+5%"},
    ("europe", "q2"): {"revenue": 10_100_000, "units": 34_000, "growth": "+3%"},
    ("asia", "q1"): {"revenue": 7_600_000, "units": 28_000, "growth": "+11%"},
    ("asia", "q2"): {"revenue": 8_400_000, "units": 31_000, "growth": "+10%"},
}


@mcp.tool()
def lookup_sales_data(region: str, quarter: str) -> str:
    """
    Query the sales database for revenue, units sold, and YoY growth.

    Args:
        region: Geographic region (e.g. "North America", "Europe", "Asia")
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


# ---------- Tool 2: Weather Lookup ----------

_MOCK_WEATHER = {
    "new york": {"temp_c": 22, "condition": "Partly cloudy", "humidity": "58%"},
    "london": {"temp_c": 15, "condition": "Overcast", "humidity": "72%"},
    "tokyo": {"temp_c": 28, "condition": "Sunny", "humidity": "65%"},
    "portland": {"temp_c": 18, "condition": "Rainy", "humidity": "85%"},
}


@mcp.tool()
def get_weather(city: str) -> str:
    """
    Get current weather conditions for a city.

    Args:
        city: City name (e.g. "New York", "London", "Tokyo")
    """
    data = _MOCK_WEATHER.get(city.lower().strip())
    if data is None:
        return f"No weather data available for '{city}'."
    return (
        f"Weather in {city}:\n"
        f"  Temperature: {data['temp_c']}°C\n"
        f"  Condition:   {data['condition']}\n"
        f"  Humidity:    {data['humidity']}"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
