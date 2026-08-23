"""Remotive public API.

Categories are configurable in config.yaml (see RemotiveConfig) - this used
to be hardcoded to `category=software-dev`, which silently made Remotive
tech-only regardless of what profiles were loaded. Non-technical profiles
(content, customer-support, hr, writing...) never got a single match from
this source. Now it pulls every category listed in cfg.remotive.categories
and de-duplicates by job id.
"""

from __future__ import annotations

import requests

from ..config import AppConfig, KeywordsConfig
from ..models import JobListing
from .base import DEFAULT_TIMEOUT, is_ai_related, is_senior, report

NAME = "Remotive"
API_URL = "https://remotive.com/api/remote-jobs"


def fetch(cfg: AppConfig, prefilter: KeywordsConfig) -> list[JobListing]:
    jobs: list[JobListing] = []
    seen_ids: set[int] = set()

    for category in cfg.remotive.categories:
        try:
            resp = requests.get(
                API_URL,
                params={"category": category, "limit": 100},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            for item in resp.json().get("jobs", []):
                job_id = item.get("id")
                if job_id is not None and job_id in seen_ids:
                    continue
                title = item.get("title", "")
                if not (
                    is_senior(title, prefilter) or is_ai_related(title, prefilter)
                ):
                    continue
                if job_id is not None:
                    seen_ids.add(job_id)
                jobs.append(
                    JobListing(
                        source=NAME,
                        title=title,
                        company=item.get("company_name", ""),
                        url=item.get("url", ""),
                        description=item.get("description", "") or "",
                        tags=item.get("tags", []) or [],
                        salary=item.get("salary", ""),
                        location=item.get("candidate_required_location", "Remote"),
                    )
                )
        except requests.RequestException as exc:
            print(f"{NAME} ({category}): error - {exc}")

    report(NAME, jobs)
    return jobs
