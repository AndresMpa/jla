"""Telegram delivery for each profile's job digest.

Talks to the Telegram Bot API directly over HTTPS — no extra dependency,
`requests` is already required by the rest of the package.

Design mirrors the rest of the config: one bot token shared by the whole
deployment (TELEGRAM_BOT_TOKEN env var — same pattern as OLLAMA_URL/
DATABASE_URL), one chat_id per profile (profiles/<n>.yaml ->
telegram.chat_id) so each person's digest lands in their own chat. A bot
token is a deployment secret, not per-candidate data, so it does not live
in profiles/*.yaml.

Create a bot via @BotFather to get a token, then message your bot once and
hit https://api.telegram.org/bot<token>/getUpdates to read back your
chat_id.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import requests

from .config import ProfileConfig
from .models import JobListing

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_LEN = 4096  # Telegram's hard limit per sendMessage call
SUMMARY_JOB_LIMIT = 10  # how many jobs to list inline before pointing at the file


class _JobLike(Protocol):
    """Structural type covering both JobListing and db.JobRecord — the single-job
    send path is used from the API against rows read back from Postgres, which
    aren't JobListing instances but share the same field names."""

    url: str
    salary: str | None
    location: str
    reasoning: str | None
    tags: list[str]
    score: int | None


def _bot_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def _build_summary(profile: ProfileConfig, jobs: list[JobListing]) -> str:
    """Short plain-text digest for the chat message; the full report goes
    along as an attached file, so this only needs to be a teaser."""
    plural = "" if len(jobs) == 1 else "es"
    lines = [f"\U0001f4b0 {profile.name}: {len(jobs)} new match{plural}", ""]
    for j in jobs[:SUMMARY_JOB_LIMIT]:
        lines.append(f"[{j.score}/10] {j.title} @ {j.company}\n{j.url}")
    if len(jobs) > SUMMARY_JOB_LIMIT:
        lines.append(
            f"\n…and {len(jobs) - SUMMARY_JOB_LIMIT} more in the attached report."
        )
    return "\n\n".join(lines)[:MAX_MESSAGE_LEN]


def _build_job_message(job: _JobLike) -> str:
    """Single-offer message, in the fixed format the UI's "send to Telegram"
    button always uses:

        Link; LINK
        Salary: SALARY

        Country/Remote: COUNTRY/REMOTE
        Why it matches: CARD_DESCRIPTION

        Skill needed: SKILLS []
        Matched percentage N/10
    """
    salary = job.salary or "Not specified"
    location = job.location or "Remote"
    why_it_matches = job.reasoning or "-"
    skills = ", ".join(job.tags) if job.tags else "-"
    score = job.score if job.score is not None else "-"
    return (
        f"Link; {job.url}\n"
        f"Salary: {salary}\n\n"
        f"Country/Remote: {location}\n"
        f"Why it matches: {why_it_matches}\n\n"
        f"Skill needed: [{skills}]\n"
        f"Matched percentage {score}/10"
    )[:MAX_MESSAGE_LEN]


class TelegramSendError(Exception):
    """Raised when a single-offer send can't go out — reason is user-facing
    (e.g. surfaced as an HTTP 400/502 by the API), unlike the digest sender's
    silent no-ops, since this is a direct button click that needs feedback."""


def send_job_to_profile(profile: ProfileConfig, job: _JobLike) -> None:
    """Sends one job offer to `profile`'s own Telegram chat — the only path the
    UI uses to deliver an offer, so each profile's owner only ever gets that
    profile's offers, in their own chat.

    Raises TelegramSendError with a user-facing reason instead of returning a
    bool, since a manual button click needs to explain a failure, not just log it.
    """
    if not profile.telegram.enabled:
        raise TelegramSendError(f"Telegram isn't enabled for profile '{profile.name}'")
    if not profile.telegram.chat_id:
        raise TelegramSendError(
            f"Profile '{profile.name}' has no Telegram chat_id configured"
        )
    token = _bot_token()
    if not token:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN is not set")

    base = f"{TELEGRAM_API_BASE}/bot{token}"
    try:
        resp = requests.post(
            f"{base}/sendMessage",
            data={
                "chat_id": profile.telegram.chat_id,
                "text": _build_job_message(job),
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise TelegramSendError(f"Telegram API request failed: {exc}") from exc


def send_document_to_profile(
    profile: ProfileConfig, file_bytes: bytes, filename: str, caption: str
) -> None:
    """Sends an arbitrary file (e.g. a tailored CV PDF, see cv.py) to
    `profile`'s Telegram chat. Same auth/config checks as
    send_job_to_profile, kept separate since a document upload needs
    `files=` instead of `data=` on the Telegram API call."""
    if not profile.telegram.enabled:
        raise TelegramSendError(f"Telegram isn't enabled for profile '{profile.name}'")
    if not profile.telegram.chat_id:
        raise TelegramSendError(
            f"Profile '{profile.name}' has no Telegram chat_id configured"
        )
    token = _bot_token()
    if not token:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN is not set")

    base = f"{TELEGRAM_API_BASE}/bot{token}"
    try:
        resp = requests.post(
            f"{base}/sendDocument",
            data={"chat_id": profile.telegram.chat_id, "caption": caption[:1024]},
            files={"document": (filename, file_bytes, "application/pdf")},
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise TelegramSendError(f"Telegram API request failed: {exc}") from exc


def send_profile_digest(
    profile: ProfileConfig, jobs: list[JobListing], md_path: Path
) -> bool:
    """Sends `profile`'s digest to its configured Telegram chat, if wired up.

    Returns True only if a message was actually sent. Every "not configured"
    case (disabled, no chat_id, no bot token, nothing to send) is a silent
    no-op — this must never be why a run fails. Network/API errors are
    caught and logged the same way, so a Telegram outage can't take down a
    scan that otherwise completed fine.
    """
    if not profile.telegram.enabled:
        return False
    if not profile.telegram.chat_id:
        print(f"[{profile.name}] Telegram enabled but no chat_id set — skipping")
        return False
    if not jobs:
        return False
    token = _bot_token()
    if not token:
        print(
            f"[{profile.name}] Telegram enabled but TELEGRAM_BOT_TOKEN is not set — skipping"
        )
        return False

    chat_id = profile.telegram.chat_id
    base = f"{TELEGRAM_API_BASE}/bot{token}"

    try:
        resp = requests.post(
            f"{base}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": _build_summary(profile, jobs),
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()

        if md_path.exists():
            with md_path.open("rb") as f:
                resp = requests.post(
                    f"{base}/sendDocument",
                    data={
                        "chat_id": chat_id,
                        "caption": f"{profile.name} — full digest",
                    },
                    files={"document": (md_path.name, f, "text/markdown")},
                    timeout=60,
                )
                resp.raise_for_status()

        print(f"[{profile.name}] Telegram digest sent to chat {chat_id}")
        return True
    except requests.RequestException as exc:
        print(f"[{profile.name}] Telegram send failed: {exc}")
        return False
