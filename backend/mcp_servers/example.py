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
    # North America monthly snapshots
    ("north america", "jan"): {"revenue": 3980000, "units": 14200, "growth": "+7%"},
    ("north america", "feb"): {"revenue": 4120000, "units": 14900, "growth": "+8%"},
    ("north america", "mar"): {"revenue": 4400000, "units": 15900, "growth": "+9%"},
    ("north america", "apr"): {"revenue": 4600000, "units": 16500, "growth": "+11%"},
    ("north america", "may"): {"revenue": 4720000, "units": 17000, "growth": "+13%"},
    ("north america", "jun"): {"revenue": 4880000, "units": 17500, "growth": "+14%"},
    # Canada monthly snapshots
    ("canada", "jan"): {"revenue": 3100000, "units": 10100, "growth": "+4%"},
    ("canada", "feb"): {"revenue": 3250000, "units": 10600, "growth": "+5%"},
    ("canada", "mar"): {"revenue": 3450000, "units": 11300, "growth": "+6%"},
    ("canada", "apr"): {"revenue": 3320000, "units": 10900, "growth": "+2%"},
    ("canada", "may"): {"revenue": 3360000, "units": 11200, "growth": "+3%"},
    ("canada", "jun"): {"revenue": 3420000, "units": 11350, "growth": "+4%"},
    # Latin America monthly snapshots
    ("latin america", "jan"): {"revenue": 2480000, "units": 9000, "growth": "+9%"},
    ("latin america", "feb"): {"revenue": 2530000, "units": 9300, "growth": "+11%"},
    ("latin america", "mar"): {"revenue": 2590000, "units": 9700, "growth": "+12%"},
    ("latin america", "apr"): {"revenue": 2720000, "units": 10100, "growth": "+9%"},
    ("latin america", "may"): {"revenue": 2810000, "units": 10400, "growth": "+10%"},
    ("latin america", "jun"): {"revenue": 2870000, "units": 10500, "growth": "+11%"},
    # Quarter aliases retained for backward compatibility
    ("north america", "q1"): {"revenue": 12500000, "units": 45000, "growth": "+8%"},
    ("north america", "q2"): {"revenue": 14200000, "units": 51000, "growth": "+13%"},
    ("canada", "q1"): {"revenue": 9800000, "units": 32000, "growth": "+5%"},
    ("canada", "q2"): {"revenue": 10100000, "units": 34000, "growth": "+3%"},
    ("latin america", "q1"): {"revenue": 7600000, "units": 28000, "growth": "+11%"},
    ("latin america", "q2"): {"revenue": 8400000, "units": 31000, "growth": "+10%"},
}

_MOCK_FINANCE = {
    # North America monthly snapshots
    ("north america", "jan"): {"ebitda": 1020000, "margin": "24.9%", "opex": 1340000},
    ("north america", "feb"): {"ebitda": 1060000, "margin": "25.3%", "opex": 1360000},
    ("north america", "mar"): {"ebitda": 1120000, "margin": "26.5%", "opex": 1400000},
    ("north america", "apr"): {"ebitda": 1230000, "margin": "26.0%", "opex": 1390000},
    ("north america", "may"): {"ebitda": 1270000, "margin": "26.9%", "opex": 1400000},
    ("north america", "jun"): {"ebitda": 1300000, "margin": "27.2%", "opex": 1420000},
    # Canada monthly snapshots
    ("canada", "jan"): {"ebitda": 680000, "margin": "20.8%", "opex": 920000},
    ("canada", "feb"): {"ebitda": 700000, "margin": "21.3%", "opex": 930000},
    ("canada", "mar"): {"ebitda": 720000, "margin": "22.1%", "opex": 950000},
    ("canada", "apr"): {"ebitda": 740000, "margin": "22.2%", "opex": 940000},
    ("canada", "may"): {"ebitda": 760000, "margin": "22.8%", "opex": 950000},
    ("canada", "jun"): {"ebitda": 780000, "margin": "23.1%", "opex": 960000},
    # Latin America monthly snapshots
    ("latin america", "jan"): {"ebitda": 470000, "margin": "18.9%", "opex": 690000},
    ("latin america", "feb"): {"ebitda": 500000, "margin": "19.7%", "opex": 700000},
    ("latin america", "mar"): {"ebitda": 530000, "margin": "20.5%", "opex": 710000},
    ("latin america", "apr"): {"ebitda": 580000, "margin": "20.8%", "opex": 715000},
    ("latin america", "may"): {"ebitda": 600000, "margin": "21.4%", "opex": 720000},
    ("latin america", "jun"): {"ebitda": 620000, "margin": "21.9%", "opex": 725000},
    # Quarter aliases retained for backward compatibility
    ("north america", "q1"): {"ebitda": 3200000, "margin": "25.6%", "opex": 4100000},
    ("north america", "q2"): {"ebitda": 3800000, "margin": "26.7%", "opex": 4200000},
    ("canada", "q1"): {"ebitda": 2100000, "margin": "21.4%", "opex": 2800000},
    ("canada", "q2"): {"ebitda": 2300000, "margin": "22.7%", "opex": 2850000},
    ("latin america", "q1"): {"ebitda": 1500000, "margin": "19.7%", "opex": 2100000},
    ("latin america", "q2"): {"ebitda": 1800000, "margin": "21.4%", "opex": 2150000},
}

_MOCK_MARKETING = {
    # North America monthly snapshots
    ("north america", "jan"): {"campaigns": 4, "reach": "14M", "engagement": "4.0%"},
    ("north america", "feb"): {"campaigns": 4, "reach": "15M", "engagement": "4.1%"},
    ("north america", "mar"): {"campaigns": 4, "reach": "16M", "engagement": "4.4%"},
    ("north america", "apr"): {"campaigns": 5, "reach": "17M", "engagement": "4.5%"},
    ("north america", "may"): {"campaigns": 5, "reach": "17M", "engagement": "4.8%"},
    ("north america", "jun"): {"campaigns": 5, "reach": "18M", "engagement": "5.0%"},
    # Canada monthly snapshots
    ("canada", "jan"): {"campaigns": 2, "reach": "3.8M", "engagement": "3.3%"},
    ("canada", "feb"): {"campaigns": 3, "reach": "4.0M", "engagement": "3.5%"},
    ("canada", "mar"): {"campaigns": 3, "reach": "4.2M", "engagement": "3.7%"},
    ("canada", "apr"): {"campaigns": 3, "reach": "4.6M", "engagement": "3.8%"},
    ("canada", "may"): {"campaigns": 3, "reach": "4.7M", "engagement": "3.9%"},
    ("canada", "jun"): {"campaigns": 4, "reach": "4.8M", "engagement": "4.0%"},
    # Latin America monthly snapshots
    ("latin america", "jan"): {"campaigns": 2, "reach": "5.6M", "engagement": "4.9%"},
    ("latin america", "feb"): {"campaigns": 2, "reach": "6.0M", "engagement": "5.0%"},
    ("latin america", "mar"): {"campaigns": 2, "reach": "6.4M", "engagement": "5.3%"},
    ("latin america", "apr"): {"campaigns": 2, "reach": "7.1M", "engagement": "5.2%"},
    ("latin america", "may"): {"campaigns": 3, "reach": "7.3M", "engagement": "5.4%"},
    ("latin america", "jun"): {"campaigns": 3, "reach": "7.6M", "engagement": "5.6%"},
    # Quarter aliases retained for backward compatibility
    ("north america", "q1"): {"campaigns": 12, "reach": "45M", "engagement": "4.2%"},
    ("north america", "q2"): {"campaigns": 15, "reach": "52M", "engagement": "4.8%"},
    ("canada", "q1"): {"campaigns": 8, "reach": "12M", "engagement": "3.5%"},
    ("canada", "q2"): {"campaigns": 10, "reach": "14M", "engagement": "3.9%"},
    ("latin america", "q1"): {"campaigns": 6, "reach": "18M", "engagement": "5.1%"},
    ("latin america", "q2"): {"campaigns": 8, "reach": "22M", "engagement": "5.4%"},
}

_MOCK_CONSUMER = {
    # North America monthly snapshots
    ("north america", "jan"): {
        "active_users": 2400000,
        "churn_rate": "2.3%",
        "nps": 66,
    },
    ("north america", "feb"): {
        "active_users": 2480000,
        "churn_rate": "2.1%",
        "nps": 67,
    },
    ("north america", "mar"): {
        "active_users": 2620000,
        "churn_rate": "2.0%",
        "nps": 69,
    },
    ("north america", "apr"): {
        "active_users": 2700000,
        "churn_rate": "1.9%",
        "nps": 70,
    },
    ("north america", "may"): {
        "active_users": 2810000,
        "churn_rate": "1.8%",
        "nps": 71,
    },
    ("north america", "jun"): {
        "active_users": 2890000,
        "churn_rate": "1.7%",
        "nps": 72,
    },
    # Canada monthly snapshots
    ("canada", "jan"): {"active_users": 820000, "churn_rate": "2.5%", "nps": 61},
    ("canada", "feb"): {"active_users": 850000, "churn_rate": "2.4%", "nps": 62},
    ("canada", "mar"): {"active_users": 880000, "churn_rate": "2.3%", "nps": 63},
    ("canada", "apr"): {"active_users": 900000, "churn_rate": "2.3%", "nps": 64},
    ("canada", "may"): {"active_users": 920000, "churn_rate": "2.2%", "nps": 65},
    ("canada", "jun"): {"active_users": 940000, "churn_rate": "2.1%", "nps": 66},
    # Latin America monthly snapshots
    ("latin america", "jan"): {
        "active_users": 1150000,
        "churn_rate": "3.3%",
        "nps": 57,
    },
    ("latin america", "feb"): {
        "active_users": 1200000,
        "churn_rate": "3.1%",
        "nps": 58,
    },
    ("latin america", "mar"): {
        "active_users": 1250000,
        "churn_rate": "3.0%",
        "nps": 59,
    },
    ("latin america", "apr"): {
        "active_users": 1320000,
        "churn_rate": "3.0%",
        "nps": 60,
    },
    ("latin america", "may"): {
        "active_users": 1380000,
        "churn_rate": "2.9%",
        "nps": 61,
    },
    ("latin america", "jun"): {
        "active_users": 1430000,
        "churn_rate": "2.8%",
        "nps": 62,
    },
    # Quarter aliases retained for backward compatibility
    ("north america", "q1"): {"active_users": 2500000, "churn_rate": "2.1%", "nps": 68},
    ("north america", "q2"): {"active_users": 2800000, "churn_rate": "1.8%", "nps": 71},
    ("canada", "q1"): {"active_users": 850000, "churn_rate": "2.4%", "nps": 62},
    ("canada", "q2"): {"active_users": 920000, "churn_rate": "2.2%", "nps": 65},
    ("latin america", "q1"): {"active_users": 1200000, "churn_rate": "3.1%", "nps": 58},
    ("latin america", "q2"): {"active_users": 1400000, "churn_rate": "2.9%", "nps": 61},
}

_MOCK_PAID_MEDIA = {
    # North America monthly snapshots
    ("north america", "jan"): {"spend": 470000, "cpa": "$33", "roas": "2.3x"},
    ("north america", "feb"): {"spend": 500000, "cpa": "$32", "roas": "2.4x"},
    ("north america", "mar"): {"spend": 530000, "cpa": "$31", "roas": "2.5x"},
    ("north america", "apr"): {"spend": 570000, "cpa": "$30", "roas": "2.6x"},
    ("north america", "may"): {"spend": 600000, "cpa": "$28", "roas": "2.8x"},
    ("north america", "jun"): {"spend": 630000, "cpa": "$27", "roas": "2.9x"},
    # Canada monthly snapshots
    ("canada", "jan"): {"spend": 190000, "cpa": "$25", "roas": "2.0x"},
    ("canada", "feb"): {"spend": 200000, "cpa": "$24", "roas": "2.1x"},
    ("canada", "mar"): {"spend": 210000, "cpa": "$23", "roas": "2.2x"},
    ("canada", "apr"): {"spend": 225000, "cpa": "$23", "roas": "2.2x"},
    ("canada", "may"): {"spend": 235000, "cpa": "$22", "roas": "2.3x"},
    ("canada", "jun"): {"spend": 240000, "cpa": "$21", "roas": "2.4x"},
    # Latin America monthly snapshots
    ("latin america", "jan"): {"spend": 125000, "cpa": "$19", "roas": "2.9x"},
    ("latin america", "feb"): {"spend": 132000, "cpa": "$18", "roas": "3.0x"},
    ("latin america", "mar"): {"spend": 143000, "cpa": "$17", "roas": "3.2x"},
    ("latin america", "apr"): {"spend": 160000, "cpa": "$17", "roas": "3.3x"},
    ("latin america", "may"): {"spend": 168000, "cpa": "$16", "roas": "3.5x"},
    ("latin america", "jun"): {"spend": 172000, "cpa": "$15", "roas": "3.6x"},
    # Quarter aliases retained for backward compatibility
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
    "supply_chain": {
        ("north america", "jan"): {
            "fill_rate": "95.1%",
            "stockout_rate": "4.3%",
            "avg_lead_time_days": 6.2,
        },
        ("north america", "feb"): {
            "fill_rate": "95.4%",
            "stockout_rate": "4.0%",
            "avg_lead_time_days": 6.0,
        },
        ("north america", "mar"): {
            "fill_rate": "95.8%",
            "stockout_rate": "3.8%",
            "avg_lead_time_days": 5.9,
        },
        ("north america", "apr"): {
            "fill_rate": "96.0%",
            "stockout_rate": "3.6%",
            "avg_lead_time_days": 5.8,
        },
        ("north america", "may"): {
            "fill_rate": "96.2%",
            "stockout_rate": "3.5%",
            "avg_lead_time_days": 5.7,
        },
        ("north america", "jun"): {
            "fill_rate": "96.4%",
            "stockout_rate": "3.4%",
            "avg_lead_time_days": 5.6,
        },
        ("canada", "jan"): {
            "fill_rate": "94.2%",
            "stockout_rate": "5.1%",
            "avg_lead_time_days": 7.0,
        },
        ("canada", "feb"): {
            "fill_rate": "94.4%",
            "stockout_rate": "4.9%",
            "avg_lead_time_days": 6.9,
        },
        ("canada", "mar"): {
            "fill_rate": "94.6%",
            "stockout_rate": "4.8%",
            "avg_lead_time_days": 6.8,
        },
        ("canada", "apr"): {
            "fill_rate": "94.8%",
            "stockout_rate": "4.7%",
            "avg_lead_time_days": 6.7,
        },
        ("canada", "may"): {
            "fill_rate": "95.0%",
            "stockout_rate": "4.6%",
            "avg_lead_time_days": 6.6,
        },
        ("canada", "jun"): {
            "fill_rate": "95.1%",
            "stockout_rate": "4.5%",
            "avg_lead_time_days": 6.5,
        },
        ("latin america", "jan"): {
            "fill_rate": "92.3%",
            "stockout_rate": "6.8%",
            "avg_lead_time_days": 8.1,
        },
        ("latin america", "feb"): {
            "fill_rate": "92.7%",
            "stockout_rate": "6.5%",
            "avg_lead_time_days": 7.9,
        },
        ("latin america", "mar"): {
            "fill_rate": "93.0%",
            "stockout_rate": "6.2%",
            "avg_lead_time_days": 7.7,
        },
        ("latin america", "apr"): {
            "fill_rate": "93.3%",
            "stockout_rate": "6.0%",
            "avg_lead_time_days": 7.6,
        },
        ("latin america", "may"): {
            "fill_rate": "93.6%",
            "stockout_rate": "5.8%",
            "avg_lead_time_days": 7.4,
        },
        ("latin america", "jun"): {
            "fill_rate": "93.9%",
            "stockout_rate": "5.6%",
            "avg_lead_time_days": 7.3,
        },
    },
    "support": {
        ("north america", "jan"): {
            "ticket_volume": 42000,
            "first_response_mins": 18,
            "csat": "88%",
        },
        ("north america", "feb"): {
            "ticket_volume": 41000,
            "first_response_mins": 17,
            "csat": "89%",
        },
        ("north america", "mar"): {
            "ticket_volume": 40500,
            "first_response_mins": 16,
            "csat": "89%",
        },
        ("north america", "apr"): {
            "ticket_volume": 39800,
            "first_response_mins": 15,
            "csat": "90%",
        },
        ("north america", "may"): {
            "ticket_volume": 39200,
            "first_response_mins": 14,
            "csat": "91%",
        },
        ("north america", "jun"): {
            "ticket_volume": 38800,
            "first_response_mins": 14,
            "csat": "91%",
        },
        ("canada", "jan"): {
            "ticket_volume": 12500,
            "first_response_mins": 20,
            "csat": "85%",
        },
        ("canada", "feb"): {
            "ticket_volume": 12300,
            "first_response_mins": 19,
            "csat": "86%",
        },
        ("canada", "mar"): {
            "ticket_volume": 12100,
            "first_response_mins": 19,
            "csat": "86%",
        },
        ("canada", "apr"): {
            "ticket_volume": 11900,
            "first_response_mins": 18,
            "csat": "87%",
        },
        ("canada", "may"): {
            "ticket_volume": 11750,
            "first_response_mins": 18,
            "csat": "87%",
        },
        ("canada", "jun"): {
            "ticket_volume": 11600,
            "first_response_mins": 17,
            "csat": "88%",
        },
        ("latin america", "jan"): {
            "ticket_volume": 16200,
            "first_response_mins": 27,
            "csat": "82%",
        },
        ("latin america", "feb"): {
            "ticket_volume": 16000,
            "first_response_mins": 26,
            "csat": "82%",
        },
        ("latin america", "mar"): {
            "ticket_volume": 15800,
            "first_response_mins": 25,
            "csat": "83%",
        },
        ("latin america", "apr"): {
            "ticket_volume": 15600,
            "first_response_mins": 24,
            "csat": "84%",
        },
        ("latin america", "may"): {
            "ticket_volume": 15400,
            "first_response_mins": 23,
            "csat": "84%",
        },
        ("latin america", "jun"): {
            "ticket_volume": 15200,
            "first_response_mins": 22,
            "csat": "85%",
        },
    },
}


@mcp.tool()
async def lookup_business_data(dataset: str, region: str, quarter: str) -> str:
    """For finance, marketing & sales agents: Query business metrics (revenue, ROI, engagement, NPS).

    Args:
        dataset: The dataset to query (e.g., "sales", "finance", "marketing", "consumer", "paid_media", "supply_chain", "support")
        region: Geographic region (e.g. "North America", "Canada", "Latin America")
        quarter: Time period token (e.g. "Q1", "Q2", "Jan", "Feb", "Mar", "Apr", "May", "Jun")
    """
    key = (region.lower().strip(), quarter.lower().strip())
    dataset_key = dataset.lower().strip()

    target_dataset = _DATASETS.get(dataset_key)
    if target_dataset is None:
        return f"Error: Dataset '{dataset}' not found. Available datasets: {', '.join(_DATASETS.keys())}"

    data = target_dataset.get(key)
    if data is None:
        return f"No {dataset} data found for region='{region}', period='{quarter}'."

    result = f"{dataset.replace('_', ' ').title()} data for {region} {quarter}:\n"
    for k, v in data.items():
        # Add basic formatting for currency/numbers if applicable
        if isinstance(v, (int, float)) and any(
            term in k for term in ["revenue", "spend", "ebitda", "opex"]
        ):
            result += f"  {k.replace('_', ' ').title()}: ${v:,}\n"
        elif isinstance(v, (int, float)):
            result += f"  {k.replace('_', ' ').title()}: {v:,}\n"
        else:
            result += f"  {k.replace('_', ' ').title()}: {v}\n"

    return result


# ---------- Tool 2: Calculator ----------


@mcp.tool()
def add(a: float, b: float) -> str:
    """For analyst and finance agents: Add two numbers together."""
    return str(a + b)


@mcp.tool()
def subtract(a: float, b: float) -> str:
    """For analyst and finance agents: Subtract the second number from the first."""
    return str(a - b)


@mcp.tool()
def multiply(a: float, b: float) -> str:
    """For analyst and finance agents: Multiply two numbers."""
    return str(a * b)


@mcp.tool()
def divide(a: float, b: float) -> str:
    """For analyst and finance agents: Divide the first number by the second."""
    if b == 0:
        return "Error: Division by zero."
    return str(a / b)


@mcp.tool()
def calculate_standard_deviation(numbers: List[float]) -> str:
    """For analyst and finance agents: Calculate the standard deviation of numbers."""
    if len(numbers) < 2:
        return "Error: Standard deviation requires at least two data points."
    return str(statistics.stdev(numbers))


@mcp.tool()
def calculate_min(numbers: List[float]) -> str:
    """For analyst and finance agents: Find the minimum value in a list of numbers."""
    if not numbers:
        return "Error: List is empty."
    return str(min(numbers))


@mcp.tool()
def calculate_max(numbers: List[float]) -> str:
    """For analyst and finance agents: Find the maximum value in a list of numbers."""
    if not numbers:
        return "Error: List is empty."
    return str(max(numbers))


@mcp.tool()
def calculate_average(numbers: List[float]) -> str:
    """For analyst and finance agents: Calculate the average (mean) of a list of numbers."""
    if not numbers:
        return "Error: List is empty."
    return str(statistics.mean(numbers))


@mcp.tool()
def calculate_mode(numbers: List[float]) -> str:
    """For analyst and finance agents: Calculate the mode of a list of numbers."""
    if not numbers:
        return "Error: List is empty."
    try:
        return str(statistics.mode(numbers))
    except statistics.StatisticsError:
        return "Error: No unique mode."


@mcp.tool()
def basic_news_search(query):
    """For research and planning agents: Search the web for recent news articles and current events.

    Uses the Tavily Web Search API.
    """
    tavily = TavilySearch(max_results=2, topic="news", tavily_api_key=TAVILY_API_KEY)
    return {"messages": tavily.invoke(query)}


@mcp.tool()
def basic_web_search(query):
    """For research and planning agents: Search the web for general topics and web content.

    Uses the Tavily Web Search API.
    """
    tavily = TavilySearch(max_results=2, topic="general", tavily_api_key=TAVILY_API_KEY)
    return {"messages": tavily.invoke(query)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
