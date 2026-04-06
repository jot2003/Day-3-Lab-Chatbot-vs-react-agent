import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.tools.budget import calculate_travel_budget
from src.tools.flights import search_flights
from src.tools.weather import get_weather

ToolFn = Callable[..., str]

_REGISTRY: Dict[str, Tuple[ToolFn, List[str]]] = {
    "get_weather": (get_weather, ["city"]),
    "search_flights": (search_flights, ["origin", "destination", "departure_date"]),
    "calculate_travel_budget": (
        calculate_travel_budget,
        ["total_budget_vnd", "flight_cost_vnd", "hotel_per_night_vnd", "num_nights"],
    ),
}

TOOL_NAMES = list(_REGISTRY.keys())


def get_tool_specs() -> List[Dict[str, Any]]:
    """Schemas for ReAct system prompt (name + description + argument names)."""
    return [
        {
            "name": "get_weather",
            "description": (
                "Lấy thời tiết hiện tại và vài mốc dự báo (OpenWeatherMap). "
                "Tham số: city — tên thành phố tiếng Anh hoặc 'Da Nang, VN', ví dụ: Da Nang"
            ),
            "args": ["city"],
        },
        {
            "name": "search_flights",
            "description": (
                "Tìm vé máy bay (Duffel API). "
                "origin, destination: mã IATA 3 chữ (HAN, DAD, SGN). "
                "departure_date: YYYY-MM-DD (ngày khởi hành)."
            ),
            "args": ["origin", "destination", "departure_date"],
        },
        {
            "name": "calculate_travel_budget",
            "description": (
                "Tính tiền còn lại sau khi trừ vé và phòng khách sạn. "
                "total_budget_vnd, flight_cost_vnd, hotel_per_night_vnd là số VND; "
                "num_nights là số đêm ở lại (số nguyên)."
            ),
            "args": ["total_budget_vnd", "flight_cost_vnd", "hotel_per_night_vnd", "num_nights"],
        },
    ]


def _split_args(arg_string: str) -> List[str]:
    """Split top-level commas; respect double-quoted segments."""
    parts: List[str] = []
    buf: List[str] = []
    in_quotes = False
    for ch in arg_string:
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "," and not in_quotes:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _normalize_tool_arg_tokens(arg_string: str, param_names: List[str]) -> Tuple[List[str], Optional[str]]:
    """
    Hỗ trợ cả:
    - positional: HAN, DAD, 2026-04-15
    - keyword: origin=HAN, destination=DAD, departure_date=2026-04-15
    """
    parts = _split_args(arg_string) if arg_string.strip() else []
    if not parts and not param_names:
        return [], None
    if not parts:
        return [], "empty arguments"

    # Keyword-only: mọi mẩu đều có '=' → gom dict rồi sắp theo param_names
    if all("=" in p for p in parts):
        kv: Dict[str, str] = {}
        for p in parts:
            k, _, v = p.partition("=")
            kv[k.strip()] = v.strip()
        if all(k in kv for k in param_names):
            return [kv[k] for k in param_names], None

    # Positional: bỏ prefix tham_số= nếu LLM vẫn in kiểu keyword
    if len(parts) != len(param_names):
        return (
            [],
            f"expected {len(param_names)} args, got {len(parts)}; "
            f"use either {', '.join(param_names)} or name=value for each",
        )

    cleaned: List[str] = []
    for i, p in enumerate(parts):
        p = p.strip()
        key = param_names[i]
        lower_prefix = key.lower() + "="
        if p.lower().startswith(lower_prefix):
            p = p.split("=", 1)[1].strip()
        elif "=" in p and p.split("=", 1)[0].strip() == key:
            p = p.split("=", 1)[1].strip()
        cleaned.append(p)
    return cleaned, None


def execute_tool(name: str, arg_string: str) -> str:
    if name not in _REGISTRY:
        return json.dumps({"error": f"Unknown tool: {name}", "known": TOOL_NAMES}, ensure_ascii=False)

    fn, param_names = _REGISTRY[name]
    values, norm_err = _normalize_tool_arg_tokens(arg_string, param_names)

    if norm_err:
        return json.dumps(
            {
                "error": norm_err,
                "tool": name,
                "expected_params": param_names,
                "hint": f'Ví dụ: {name}(a, b) hoặc {name}(a=a, b=b) theo đúng tên: {", ".join(param_names)}',
            },
            ensure_ascii=False,
        )

    kwargs = {k: _parse_value(v) for k, v in zip(param_names, values)}
    try:
        return fn(**kwargs)
    except Exception as e:
        return json.dumps({"error": str(e), "tool": name}, ensure_ascii=False)
