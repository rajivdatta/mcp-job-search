"""Thin client for the JSearch job-search API (RapidAPI).

JSearch aggregates public job postings (including LinkedIn, Indeed, Glassdoor)
via Google for Jobs. Get a key by subscribing to JSearch on RapidAPI:
https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
"""
from __future__ import annotations

import requests

BASE_URL = "https://jsearch.p.rapidapi.com/search"
API_HOST = "jsearch.p.rapidapi.com"

# Allowed JSearch values for "how recently was it posted".
VALID_DATE_POSTED = {"all", "today", "3days", "week", "month"}


def search(query: str, api_key: str, date_posted: str = "week",
           num_pages: int = 1, country: str | None = None) -> list[dict]:
    if date_posted not in VALID_DATE_POSTED:
        raise ValueError(f"date_posted must be one of {sorted(VALID_DATE_POSTED)}")
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": API_HOST}
    params = {
        "query": query,
        "page": "1",
        "num_pages": str(num_pages),
        "date_posted": date_posted,
    }
    if country:
        params["country"] = country
    resp = requests.get(BASE_URL, headers=headers, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json().get("data", []) or []
