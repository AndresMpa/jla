"""Jobicy public API (https://jobicy.com/api/v2/remote-jobs).

Free, no API key. Another general remote-jobs board (not tech-only) with
industries like Marketing, Customer Service, HR, Education, Writing.
`industries` / `geo` are configurable in config.yaml (JobicyConfig) - an
empty industries list fetches every industry in one call.
"""

from __future__ import annotations

import requests

from ..config import AppConfig, KeywordsConfig
from ..models import JobListing
from .base import DEFAULT_TIMEOUT, is_ai_related, is_senior, report

NAME = "Jobicy"
API_URL = "https://jobicy.com/api/v2/remote-jobs"


def _fetch_one(
    industry: str | None, geo: str, prefilter: KeywordsConfig
) -> list[JobListing]:
    jobs: list[JobListing] = []
    params: dict[str, str | int] = {"count": 50}
    if industry:
        params["industry"] = industry
    if geo:
        params["geo"] = geo

    resp = requests.get(API_URL, params=params, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    for item in resp.json().get("jobs", []):
        title = item.get("jobTitle", "")
        if not (is_senior(title, prefilter) or is_ai_related(title, prefilter)):
            continue
        jobs.append(
            JobListing(
                source=NAME,
                title=title,
                company=item.get("companyName", ""),
                url=item.get("url", ""),
                description=item.get("jobDescription", "")
                or item.get("jobExcerpt", "")
                or "",
                tags=[item.get("jobIndustry", "")] if item.get("jobIndustry") else [],
                salary=(
                    f"{item.get('salaryCurrency', '')} "
                    f"{item.get('annualSalaryMin', '')}-{item.get('annualSalaryMax', '')}"
                    if item.get("annualSalaryMin")
                    else ""
                ),
                location=item.get("jobGeo", "Remote") or "Remote",
            )
        )
    return jobs


def fetch(cfg: AppConfig, prefilter: KeywordsConfig) -> list[JobListing]:
    jobs: list[JobListing] = []
    industries: list[str | None] = list(cfg.jobicy.industries) or [None]

    for industry in industries:
        try:
            jobs.extend(_fetch_one(industry, cfg.jobicy.geo, prefilter))
        except requests.RequestException as exc:
            label = industry or "all"
            print(f"{NAME} ({label}): error - {exc}")

    report(NAME, jobs)
    return jobs
