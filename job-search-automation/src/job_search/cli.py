"""Pipeline orchestration: fetch -> dedupe -> (filter -> score -> report) per profile.

Fetching hits public APIs/RSS feeds, so it's done exactly once per run and
shared across every profile — each profile just applies its own keyword
filter and LLM scoring on top of the same fetched listings, then gets its
own CSV/Markdown report under profiles/output/<profile-name>/.
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
from functools import reduce
from pathlib import Path

from .config import (
    AppConfig,
    KeywordsConfig,
    ProfileConfig,
    load_config,
    load_profile,
    load_profiles,
)
from .fetchers import fetch_all
from .filters import passes_filter
from .models import JobListing
from .reports import write_csv_report, write_markdown_report
from .scoring import OllamaClient, ProgressFn
from .telegram import send_profile_digest


def _emit(on_progress: ProgressFn | None, message: str) -> None:
    if on_progress is not None:
        on_progress(message)


def deduplicate(jobs: list[JobListing]) -> list[JobListing]:
    seen: set[str] = set()
    unique: list[JobListing] = []
    for job in jobs:
        if job.url:
            if job.url in seen:
                continue
            seen.add(job.url)
        unique.append(job)
    return unique


def _merged_prefilter(profiles: list[ProfileConfig]) -> KeywordsConfig:
    """Union of every profile's seniority/ai keywords, used as the cheap
    fetch-time prefilter so no profile's matches get dropped before the
    full per-profile filter even runs."""
    return reduce(
        lambda acc, kw: acc.merge(kw), (p.keywords for p in profiles), KeywordsConfig()
    )


def run_for_profile(
    cfg: AppConfig,
    profile: ProfileConfig,
    unique_jobs: list[JobListing],
    client: OllamaClient,
    on_progress: ProgressFn | None = None,
) -> list[JobListing]:
    """Filter, score and rank the shared fetched listings for one profile."""
    filtered = [
        copy.deepcopy(j) for j in unique_jobs if passes_filter(j, profile.keywords)
    ]
    print(f"\n[{profile.name}] {len(filtered)} listings passed keyword filtering")
    _emit(on_progress, f"[{profile.name}] {len(filtered)} listings passed keyword filtering")
    if not filtered:
        return []

    print(
        f"[{profile.name}] Scoring with {cfg.ollama.model} (timeout {cfg.ollama.timeout}s)..."
    )
    for i, job in enumerate(filtered, 1):
        print(
            f"[{profile.name}] [{i}/{len(filtered)}] {job.title[:40]} @ {job.company[:20]}"
        )
        _emit(
            on_progress,
            f"[{profile.name}] Scoring {i}/{len(filtered)}: {job.title} @ {job.company}",
        )
        client.score_job(job, profile.profile)
        if (job.score or 0) >= cfg.scoring.min_score_to_keep:
            client.draft_outreach(job, profile.profile)
        time.sleep(0.5)

    kept = [j for j in filtered if (j.score or 0) >= cfg.scoring.min_score_to_keep]
    kept.sort(key=lambda j: j.income_score or 0, reverse=True)
    _emit(on_progress, f"[{profile.name}] {len(kept)} listings kept after scoring")
    return kept


def run(
    cfg: AppConfig,
    profiles: list[ProfileConfig],
    on_progress: ProgressFn | None = None,
) -> dict[str, list[JobListing]]:
    """Run the full pipeline for every given profile. Returns {profile_name: kept_jobs}."""
    client = OllamaClient(cfg, on_progress=on_progress)
    print("Checking Ollama connection...")
    _emit(on_progress, "Checking Ollama connection...")
    if not client.check_connection():
        sys.exit(1)

    print("\nFetching job listings...")
    _emit(on_progress, "Fetching job listings from all providers...")
    prefilter = _merged_prefilter(profiles)
    all_jobs = fetch_all(cfg, prefilter)
    unique = deduplicate(all_jobs)
    print(f"\n{len(all_jobs)} listings fetched, {len(unique)} unique")
    _emit(on_progress, f"{len(all_jobs)} listings fetched, {len(unique)} unique")

    results: dict[str, list[JobListing]] = {}
    for profile in profiles:
        results[profile.name] = run_for_profile(
            cfg, profile, unique, client, on_progress=on_progress
        )
    return results


def write_reports(
    cfg: AppConfig,
    profile: ProfileConfig,
    kept: list[JobListing],
    on_progress: ProgressFn | None = None,
) -> None:
    csv_path = profile.csv_path(cfg.output_base_dir)
    md_path = profile.md_path(cfg.output_base_dir)
    write_csv_report(kept, csv_path)
    write_markdown_report(kept, md_path)
    print(
        f"\n[{profile.name}] {len(kept)} listings saved to:\n  - {csv_path}\n  - {md_path}"
    )
    _emit(on_progress, f"[{profile.name}] Report saved ({len(kept)} listings)")
    send_profile_digest(profile, kept, md_path)
    _emit(on_progress, f"[{profile.name}] Digest sent to Telegram")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch, score and report high-value remote job listings, per candidate profile."
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "-p",
        "--profile",
        action="append",
        dest="profile_names",
        help="Name of a single profile to run (matches profiles/<n>.yaml). "
        "Repeat for several. Omit to run every profile in profiles/.",
    )
    parser.add_argument(
        "--profiles-dir",
        default="profiles",
        help="Directory containing profile YAML files (default: ./profiles)",
    )
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        profiles_dir = Path(args.profiles_dir)
        if args.profile_names:
            profiles = [
                load_profile(profiles_dir / f"{name}.yaml")
                for name in args.profile_names
            ]
        else:
            profiles = load_profiles(profiles_dir)
    except FileNotFoundError as exc:
        print(f"\nError: {exc}")
        sys.exit(1)

    results = run(cfg, profiles)

    for profile in profiles:
        kept = results.get(profile.name, [])
        if not kept:
            print(f"\n[{profile.name}] No relevant listings found.")
            continue

        write_reports(cfg, profile, kept)

        if cfg.database.url:
            from . import db

            saved = db.save_jobs(kept, cfg.database, profile.name)
            print(f"[{profile.name}] {saved} rows upserted into Postgres")


if __name__ == "__main__":
    main()
