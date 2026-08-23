"""Data models shared across the package."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class JobListing:
    """A single job posting, enriched in-place as it moves through the pipeline."""

    source: str
    title: str
    company: str
    url: str
    description: str
    tags: list[str] = field(default_factory=list)
    salary: str | None = None
    location: str = ""
    posted_date: str = ""

    # Populated by the scoring stage
    fit_score: int | None = None
    income_score: int | None = None
    score: int | None = None
    reasoning: str | None = None
    outreach_draft: str | None = None

    @property
    def haystack(self) -> str:
        """Lowercase blob used for keyword matching.

        Tags are supposed to be a flat list of strings, but several public
        APIs used by the fetchers don't reliably match their own docs (e.g.
        Himalayas documents locationRestrictions as objects but sometimes
        returns plain strings) - so tags occasionally arrive as nested
        lists or contain non-string items. Flatten/stringify defensively
        here rather than trusting every fetcher to get this right, so one
        odd listing from one provider can't crash the whole run.
        """
        return " ".join(
            [
                self.title.lower(),
                self.company.lower(),
                self.description.lower(),
                " ".join(_flatten_to_strs(self.tags)).lower(),
            ]
        )


def _flatten_to_strs(items: object) -> list[str]:
    """Recursively flatten a possibly-nested, possibly-mixed-type iterable
    into a flat list of strings. Non-iterables and None entries are
    coerced/skipped safely."""
    if items is None:
        return []
    if isinstance(items, str):
        return [items]
    if isinstance(items, (list, tuple, set)):
        out: list[str] = []
        for item in items:
            out.extend(_flatten_to_strs(item))
        return out
    return [str(items)]
