import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.tools.registry import execute_tool, get_tool_specs


def test_get_tool_specs_has_three_tools():
    specs = get_tool_specs()
    names = {s["name"] for s in specs}
    assert names == {"get_weather", "search_flights", "calculate_travel_budget"}


def test_calculate_travel_budget_execute():
    raw = execute_tool(
        "calculate_travel_budget",
        "8000000, 2400000, 900000, 2",
    )
    data = json.loads(raw)
    assert data["remaining_vnd"] == 8000000 - 2400000 - 1800000
    assert data["feasible"] is True


def test_calculate_travel_budget_keyword_style():
    """LLM (Gemini) hay in Action: calculate_travel_budget(a=1, b=2, ...)."""
    raw = execute_tool(
        "calculate_travel_budget",
        "total_budget_vnd=8000000, flight_cost_vnd=1250000, hotel_per_night_vnd=900000, num_nights=2",
    )
    data = json.loads(raw)
    assert "error" not in data
    assert data["remaining_vnd"] == 8000000 - 1250000 - 1800000


def test_search_flights_keyword_style():
    raw = execute_tool(
        "search_flights",
        "origin=HAN, destination=DAD, departure_date=2026-04-20",
    )
    data = json.loads(raw)
    assert "error" not in data or "duffel" in data.get("error", "").lower()


def test_unknown_tool():
    raw = execute_tool("fake_tool", "")
    data = json.loads(raw)
    assert "error" in data
