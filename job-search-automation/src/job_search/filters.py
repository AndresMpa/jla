"""Cheap keyword filtering, applied before the (expensive) LLM scoring stage."""

from __future__ import annotations

from .config import KeywordsConfig
from .fetchers.base import matches_any
from .models import JobListing


def passes_filter(job: JobListing, keywords: KeywordsConfig) -> bool:
    """Reject non-technical, low-value, or off-target postings early.

    `keywords` comes from a single profile (profiles/<name>.yaml) — each
    profile keeps its own target/exclude/tech lists.
    """
    haystack = job.haystack

    # `tech` is an optional extra gate for profiles that care about a
    # specific stack (e.g. "python", "react"). A profile that leaves it
    # empty (non-technical roles: content, HR, customer success...) isn't
    # opting out of tech jobs, it simply has no tech requirement - so an
    # empty list must NOT reject every listing. matches_any(haystack, [])
    # is always False, which used to make `not matches_any(...)` always
    # True and silently drop 100% of listings for these profiles.
    if keywords.tech and not matches_any(haystack, keywords.tech):
        return False
    if matches_any(haystack, keywords.exclude):
        return False
    if not (
        matches_any(haystack, keywords.seniority) or matches_any(haystack, keywords.ai)
    ):
        return False
    return matches_any(haystack, keywords.target)
