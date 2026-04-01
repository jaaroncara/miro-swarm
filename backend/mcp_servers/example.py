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


# ---------- Tool 1: Business Database Lookup ----------

_MOCK_SALES = {
    ("north america", "q1"): {"revenue": 12500000, "units": 45000, "growth": "+8%"},
    ("north america", "q2"): {"revenue": 14200000, "units": 51000, "growth": "+13%"},
    ("canada", "q1"): {"revenue": 9800000, "units": 32000, "growth": "+5%"},
    ("canada", "q2"): {"revenue": 10100000, "units": 34000, "growth": "+3%"},
    ("latin america", "q1"): {"revenue": 7600000, "units": 28000, "growth": "+11%"},
    ("latin america", "q2"): {"revenue": 8400000, "units": 31000, "growth": "+10%"},
}

_MOCK_FINANCE = {
    ("north america", "q1"): {"ebitda": 3200000, "margin": "25.6%", "opex": 4100000},
    ("north america", "q2"): {"ebitda": 3800000, "margin": "26.7%", "opex": 4200000},
    ("canada", "q1"): {"ebitda": 2100000, "margin": "21.4%", "opex": 2800000},
    ("canada", "q2"): {"ebitda": 2300000, "margin": "22.7%", "opex": 2850000},
    ("latin america", "q1"): {"ebitda": 1500000, "margin": "19.7%", "opex": 2100000},
    ("latin america", "q2"): {"ebitda": 1800000, "margin": "21.4%", "opex": 2150000},
}

_MOCK_MARKETING = {
    ("north america", "q1"): {"campaigns": 12, "reach": "45M", "engagement": "4.2%"},
    ("north america", "q2"): {"campaigns": 15, "reach": "52M", "engagement": "4.8%"},
    ("canada", "q1"): {"campaigns": 8, "reach": "12M", "engagement": "3.5%"},
    ("canada", "q2"): {"campaigns": 10, "reach": "14M", "engagement": "3.9%"},
    ("latin america", "q1"): {"campaigns": 6, "reach": "18M", "engagement": "5.1%"},
    ("latin america", "q2"): {"campaigns": 8, "reach": "22M", "engagement": "5.4%"},
}

_MOCK_CONSUMER = {
    ("north america", "q1"): {"active_users": 2500000, "churn_rate": "2.1%", "nps": 68},
    ("north america", "q2"): {"active_users": 2800000, "churn_rate": "1.8%", "nps": 71},
    ("canada", "q1"): {"active_users": 850000, "churn_rate": "2.4%", "nps": 62},
    ("canada", "q2"): {"active_users": 920000, "churn_rate": "2.2%", "nps": 65},
    ("latin america", "q1"): {"active_users": 1200000, "churn_rate": "3.1%", "nps": 58},
    ("latin america", "q2"): {"active_users": 1400000, "churn_rate": "2.9%", "nps": 61},
}

_MOCK_PAID_MEDIA = {
    ("north america", "q1"): {"spend": 1500000, "cpa": "$32", "roas": "2.4x"},
    ("north america", "q2"): {"spend": 1800000, "cpa": "$28", "roas": "2.8x"},
    ("canada", "q1"): {"spend": 600000, "cpa": "$24", "roas": "2.1x"},
    ("canada", "q2"): {"spend": 700000, "cpa": "$22", "roas": "2.3x"},
    ("latin america", "q1"): {"spend": 400000, "cpa": "$18", "roas": "3.1x"},
    ("latin america", "q2"): {"spend": 500000, "cpa": "$16", "roas": "3.5x"},
}

_DATASETS = {
    "sales": _MOCK_SALES,
    "finance": _MOCK_FINANCE,
    "marketing": _MOCK_MARKETING,
    "consumer": _MOCK_CONSUMER,
    "paid_media": _MOCK_PAID_MEDIA,
}


@mcp.tool()
async def lookup_business_data(dataset: str, region: str, quarter: str) -> str:
    """
    Query business datasets for metrics across various domains.

    Args:
        dataset: The dataset to query (e.g., "sales", "finance", "marketing", "consumer", "paid_media")
        region: Geographic region (e.g. "North America", "Canada", "Latin America")
        quarter: Fiscal quarter (e.g. "Q1", "Q2")
    """
    key = (region.lower().strip(), quarter.lower().strip())
    dataset_key = dataset.lower().strip()
    
    target_dataset = _DATASETS.get(dataset_key)
    if target_dataset is None:
        return f"Error: Dataset '{dataset}' not found. Available datasets: {', '.join(_DATASETS.keys())}"
        
    data = target_dataset.get(key)
    if data is None:
        return f"No {dataset} data found for region='{region}', quarter='{quarter}'."
        
    result = f"{dataset.replace('_', ' ').title()} data for {region} {quarter}:\n"
    for k, v in data.items():
        # Add basic formatting for currency/numbers if applicable
        if isinstance(v, (int, float)) and any(term in k for term in ["revenue", "spend", "ebitda", "opex"]):
            result += f"  {k.replace('_', ' ').title()}: ${v:,}\n"
        elif isinstance(v, (int, float)):
            result += f"  {k.replace('_', ' ').title()}: {v:,}\n"
        else:
            result += f"  {k.replace('_', ' ').title()}: {v}\n"
            
    return result


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
