"""Himalayas.app public JSON API (https://himalayas.app/docs/remote-jobs-api).

Free, no API key, no auth. Unlike remoteok/remotive/weworkremotely, this
feed isn't tech-skewed - it covers marketing, HR, customer support,
education, writing, etc. across worldwide-remote and region-restricted
roles, which is exactly what non-technical profiles need.

We pull a few pages of the plain "browse" feed (most-recently-updated
first) rather than the /search endpoint, so this stays useful for any
profile without needing per-keyword round trips per profile.
"""

from __future__ import annotations

import requests

from ..config import AppConfig, KeywordsConfig
from ..models import JobListing
from .base import DEFAULT_TIMEOUT, is_ai_related, is_senior, report

NAME = "Himalayas"
API_URL = "https://himalayas.app/jobs/api"
PAGE_LIMIT = 20
MAX_PAGES = 5  # 5 * 20 = 100 most-recently-updated jobs, refreshed daily anyway


def fetch(cfg: AppConfig, prefilter: KeywordsConfig) -> list[JobListing]:
    jobs: list[JobListing] = []
    cursor: str | None = None

    try:
        for _ in range(MAX_PAGES):
            params: dict[str, str | int] = {"limit": PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor

            resp = requests.get(API_URL, params=params, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("jobs", []):
                title = item.get("title", "")
                if not (
                    is_senior(title, prefilter) or is_ai_related(title, prefilter)
                ):
                    continue

                locations = item.get("locationRestrictions") or []
                location = (
                    ", ".join(loc.get("name", "") for loc in locations)
                    if locations
                    else "Worldwide"
                )
                min_salary = item.get("minSalary")
                max_salary = item.get("maxSalary")
                currency = item.get("currency") or ""
                salary = (
                    f"{currency} {min_salary}-{max_salary}"
                    if min_salary and max_salary
                    else ""
                )

                jobs.append(
                    JobListing(
                        source=NAME,
                        title=title,
                        company=item.get("companyName", ""),
                        url=item.get("applicationLink", ""),
                        description=item.get("description", "")
                        or item.get("excerpt", "")
                        or "",
                        tags=item.get("categories", []) or [],
                        salary=salary,
                        location=location,
                    )
                )

            cursor = data.get("nextCursor")
            if not cursor:
                break
    except requests.RequestException as exc:
        print(f"{NAME}: error - {exc}")

    report(NAME, jobs)
    return jobs
