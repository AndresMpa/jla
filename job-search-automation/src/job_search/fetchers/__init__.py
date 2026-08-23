"""Fetcher registry.

To add a new provider: write a module exposing `fetch(cfg) -> list[JobListing]`
(see base.py for shared helpers), add a matching boolean field to
ProvidersConfig in config.py, and register it in REGISTRY below. Nothing
else needs to change (open/closed principle).
"""

from __future__ import annotations

from ..config import AppConfig, KeywordsConfig
from ..models import JobListing
from . import (
    arbeitnow,
    greenhouse,
    hackernews,
    himalayas,
    jobicy,
    python_jobs,
    remoteok,
    remotive,
    vuejobs,
    weworkremotely,
    workday,
)

# provider config field name -> fetch function
REGISTRY = {
    "remoteok": remoteok.fetch,
    "remotive": remotive.fetch,
    "weworkremotely": weworkremotely.fetch,
    "python_jobs": python_jobs.fetch,
    "vuejobs": vuejobs.fetch,
    "hackernews": hackernews.fetch,
    "arbeitnow": arbeitnow.fetch,
    "greenhouse": greenhouse.fetch,
    "workday": workday.fetch,
    "himalayas": himalayas.fetch,
    "jobicy": jobicy.fetch,
}


def fetch_all(cfg: AppConfig, prefilter: KeywordsConfig) -> list[JobListing]:
    """Run every provider enabled in config.yaml and return the combined list.

    `prefilter` is the cheap title-only pre-filter (seniority/ai keywords)
    applied inside each fetcher before the full per-profile filtering stage.
    When running multiple profiles in one pass, this is the *union* of every
    profile's seniority/ai keywords, so nothing a profile cares about gets
    dropped before it even reaches the full filter.
    """
    jobs: list[JobListing] = []
    for field_name, fetch_fn in REGISTRY.items():
        if getattr(cfg.providers, field_name):
            jobs.extend(fetch_fn(cfg, prefilter))
    return jobs
