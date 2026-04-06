import json
import os
import re
from typing import Any, Dict, Optional

import requests

from src.tools.demo_fallback import demo_travel_apis_enabled, mock_flights

DUFFEL_OFFER_REQUESTS_URL = "https://api.duffel.com/air/offer_requests"
DUFFEL_VERSION = "v2"


def _duffel_token() -> str:
    return os.getenv("DUFFEL_API_TOKEN", "").strip()


def _strip_wrapping_quotes(value: str) -> str:
    s = value.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1].strip()
    return s


def _normalize_iata(code: str) -> str:
    return _strip_wrapping_quotes(str(code)).strip().upper()


def _normalize_departure_date(value: str) -> str:
    return _strip_wrapping_quotes(str(value)).strip()


def _validate_iata(code: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", code))


def _validate_departure_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


def search_flights(origin: str, destination: str, departure_date: str) -> str:
    """
    Duffel API: IATA codes (e.g. HAN, DAD, SGN), departure_date YYYY-MM-DD.
    Returns top offers with a simplified shape used by the app UI/agent.
    """
    token = _duffel_token()
    if not token:
        if demo_travel_apis_enabled():
            return mock_flights(origin, destination, departure_date)
        return json.dumps(
            {
                "error": "Missing DUFFEL_API_TOKEN",
                "hint": "https://duffel.com/air (create API token) — hoặc DEMO_TRAVEL_APIS=1 trong .env để demo không cần Duffel.",
            },
            ensure_ascii=False,
        )

    origin = _normalize_iata(origin)
    destination = _normalize_iata(destination)
    departure_date = _normalize_departure_date(departure_date)

    if not _validate_iata(origin) or not _validate_iata(destination) or not _validate_departure_date(departure_date):
        return json.dumps(
            {
                "error": "Invalid flight search inputs",
                "expected": {
                    "origin": "IATA code (e.g. HAN)",
                    "destination": "IATA code (e.g. DAD)",
                    "departure_date": "YYYY-MM-DD",
                },
                "received": {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": departure_date,
                },
            },
            ensure_ascii=False,
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Duffel-Version": DUFFEL_VERSION,
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "data": {
            "slices": [
                {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": departure_date,
                }
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
            "max_connections": 2,
        }
    }

    try:
        r = requests.post(DUFFEL_OFFER_REQUESTS_URL, headers=headers, json=payload, timeout=30)
        if r.status_code >= 400:
            details = None
            try:
                err_json = r.json()
                if isinstance(err_json, dict):
                    details = [
                        {
                            "field": ((e.get("source") or {}).get("field") or ""),
                            "message": e.get("message") or e.get("title") or "",
                            "code": e.get("code") or "",
                        }
                        for e in (err_json.get("errors") or [])
                    ]
            except ValueError:
                details = None
            return json.dumps(
                {
                    "error": "Duffel flight search failed",
                    "status": r.status_code,
                    "body": r.text[:2000],
                    "validation_errors": details,
                },
                ensure_ascii=False,
            )
        data = r.json()
    except requests.RequestException as e:
        return json.dumps({"error": "Duffel request failed", "detail": str(e)}, ensure_ascii=False)

    offers = []
    raw_offers = (data.get("data") or {}).get("offers") or []
    for item in raw_offers[:5]:
        slices = item.get("slices") or []
        first_slice = slices[0] if slices else {}
        segs = first_slice.get("segments") or []
        first_seg = segs[0] if segs else {}
        last_seg = segs[-1] if segs else {}
        offers.append(
            {
                "price": item.get("total_amount"),
                "currency": item.get("total_currency", "USD"),
                "departure_at": (first_seg.get("departing_at") or first_slice.get("departing_at")),
                "arrival_at": (last_seg.get("arriving_at") or first_slice.get("arriving_at")),
                "carrier_code": ((first_seg.get("marketing_carrier") or {}).get("iata_code") or ""),
                "number_of_stops": max(0, len(segs) - 1),
            }
        )

    if not offers:
        return json.dumps(
            {
                "message": "No offers returned for the selected route/date.",
                "raw_meta": bool((data.get("meta") or {})),
            },
            ensure_ascii=False,
        )

    return json.dumps({"offers": offers, "source": "duffel"}, ensure_ascii=False)
