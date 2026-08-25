"""HTTP API for job-search-automation.

Responsibilities:

- GET /jobs                  -> reads scored listings from Postgres, optionally per profile
- GET/PUT /config             -> reads/writes config.yaml, the *system* settings
- GET /profiles                -> lists candidate profiles (profiles/*.yaml)
- GET/PUT/DELETE /profiles/{name} -> reads/writes/removes a single profile
- POST /run                    -> triggers a pipeline run in the background,
                                    for one profile or every profile
- WS /ws/run/status             -> live progress for the run triggered above
- POST /jobs/{id}/send-cv       -> tailors + sends a CV in the background
- WS /ws/jobs/{id}/cv-status    -> live progress for the send-cv above

Run with: uvicorn job_search.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .cli import run as run_pipeline
from .cli import write_reports
from .config import (
    DEFAULT_PROFILES_DIR,
    config_from_dict,
    list_profile_paths,
    load_config,
    load_profile,
    load_profiles,
    profile_from_dict,
    save_config,
    save_profile,
)
from .cv import ResumeIncomplete, build_tailored_cv, render_ats_pdf
from .progress import hub as progress_hub
from .scoring import OllamaClient
from .telegram import (
    TelegramSendError,
    send_document_to_profile,
    send_job_to_profile,
)

CONFIG_PATH = Path("config.yaml")
PROFILES_DIR = DEFAULT_PROFILES_DIR

app = FastAPI(title="job-search-automation API", version="2.0.0")

# The Nuxt app calls this from its own server routes (not the browser), but
# CORS is opened up for convenience when calling the API directly too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _bind_progress_hub() -> None:
    """Captures the running event loop so ProgressHub.publish() - called
    from BackgroundTasks worker threads - can safely deliver messages to
    WebSocket subscribers living on this loop. See progress.py."""
    progress_hub.bind_loop(asyncio.get_running_loop())


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class JobOut(BaseModel):
    id: int
    profile: str
    source: str
    title: str
    company: str
    url: str
    description: str
    tags: list[str]
    salary: str | None
    location: str
    posted_date: str
    fit_score: int | None
    income_score: int | None
    score: int | None
    reasoning: str | None
    outreach_draft: str | None

    model_config = {"from_attributes": True}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/jobs", response_model=list[JobOut])
def list_jobs(
    profile: str | None = None,
    min_score: int | None = None,
    limit: int = 200,
    offset: int = 0,
):
    cfg = load_config(CONFIG_PATH)
    if not cfg.database.url:
        raise HTTPException(500, "database.url is not configured")
    if not db.schema_ready(cfg.database):
        raise HTTPException(
            503, "Database schema not initialized. Call POST /init-db first."
        )
    records = db.fetch_jobs(
        cfg.database, profile=profile, min_score=min_score, limit=limit, offset=offset
    )
    return records


def _load_job_and_profile(job_id: int):
    """Shared lookup used by both /send-telegram and /send-cv: fetch the job
    row and the profile that owns it (job.profile), raising the same
    HTTPExceptions either endpoint would raise on a bad id."""
    cfg = load_config(CONFIG_PATH)
    if not cfg.database.url:
        raise HTTPException(500, "database.url is not configured")
    if not db.schema_ready(cfg.database):
        raise HTTPException(
            503, "Database schema not initialized. Call POST /init-db first."
        )

    job = db.fetch_job(cfg.database, job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} not found")

    profile_path = PROFILES_DIR / f"{job.profile}.yaml"
    if not profile_path.exists():
        raise HTTPException(404, f"Profile '{job.profile}' not found")
    profile = load_profile(profile_path)
    return cfg, job, profile


def _cv_channel(job_id: int) -> str:
    return f"cv:{job_id}"


def _run_cv_generation(job_id: int) -> None:
    """Runs entirely in a BackgroundTask - must never let an exception
    escape (Starlette would just log it as an unhandled "Exception in ASGI
    application" and any open WebSocket would just hang), so every failure
    path publishes a user-facing "error" message instead of raising.

    Progress is streamed rather than polled: every meaningful step
    publishes onto progress_hub's f"cv:{job_id}" channel, which
    GET /ws/jobs/{job_id}/cv-status forwards to the browser as it happens -
    "loading profile", each Ollama request/response (see scoring.py's
    on_progress), PDF rendering, and the Telegram upload.
    """
    channel = _cv_channel(job_id)

    def emit(message: str) -> None:
        progress_hub.publish(channel, {"status": "running", "detail": message})

    emit("Loading job and profile...")
    try:
        cfg, job, profile = _load_job_and_profile(job_id)
    except HTTPException as exc:
        progress_hub.publish(channel, {"status": "error", "detail": str(exc.detail)})
        return

    if not profile.resume.name:
        progress_hub.publish(
            channel,
            {
                "status": "error",
                "detail": (
                    f"Profile '{profile.name}' has no resume data configured. "
                    "Add a `resume:` section to its profiles/<name>.yaml first."
                ),
            },
        )
        return

    client = OllamaClient(cfg)
    try:
        tailored = build_tailored_cv(client, profile.resume, job, on_progress=emit)
        emit("Rendering ATS PDF...")
        pdf_bytes = render_ats_pdf(profile.resume, tailored)
        safe_name = (profile.resume.name or profile.name).replace(" ", "_")
        safe_company = (job.company or "role").replace(" ", "_").replace("/", "-")
        filename = f"{safe_name}_CV_{safe_company}.pdf"
        emit("Uploading tailored CV to Telegram...")
        send_document_to_profile(
            profile,
            pdf_bytes,
            filename,
            caption=f"Tailored CV — {job.title} @ {job.company}",
        )
    except (ResumeIncomplete, TelegramSendError) as exc:
        progress_hub.publish(channel, {"status": "error", "detail": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001 - last-resort net, see docstring
        print(f"[send-cv] job {job_id} failed unexpectedly: {exc}")
        progress_hub.publish(
            channel, {"status": "error", "detail": f"Unexpected error: {exc}"}
        )
        return

    progress_hub.publish(channel, {"status": "done", "detail": "sent"})


@app.post("/jobs/{job_id}/send-telegram")
def send_job_telegram(job_id: int) -> dict[str, str]:
    """Sends one job offer to Telegram — the only path used to deliver an
    offer, so it always goes to the chat_id of the profile that owns the
    job (JobRecord.profile), never a caller-supplied chat.
    """
    _cfg, job, profile = _load_job_and_profile(job_id)

    try:
        send_job_to_profile(profile, job)
    except TelegramSendError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {"status": "sent", "profile": profile.name}


@app.post("/jobs/{job_id}/send-cv")
def send_cv_telegram(job_id: int, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Kicks off CV tailoring + PDF render + Telegram send in the
    background and returns immediately - see WS /ws/jobs/{id}/cv-status
    for live progress and the final result.

    This used to run synchronously (a single Ollama completion, so it
    seemed comparable to one scoring call), but a full tailoring pass -
    Ollama generation + PDF render + a Telegram upload - can take minutes
    on a slow/remote Ollama, long enough that the frontend's HTTP client
    (or an intermediary) gives up and reports "could not reach the
    backend" even though the backend is still working. Backgrounding it
    avoids depending on any client/proxy timeout being longer than however
    long Ollama happens to take.
    """
    # Fails fast (404) for a bad job id before ever touching the background
    # task, so the frontend gets an immediate, specific error instead of
    # only discovering the problem once it opens the WebSocket.
    _load_job_and_profile(job_id)

    # Drop any cached final state from a previous send-cv for this same
    # job_id, so a fresh WS subscriber doesn't immediately replay a stale
    # "done"/"error" from last time before this run has published anything.
    progress_hub.clear(_cv_channel(job_id))
    background_tasks.add_task(_run_cv_generation, job_id)
    return {"status": "started"}


@app.websocket("/ws/jobs/{job_id}/cv-status")
async def ws_cv_status(websocket: WebSocket, job_id: int) -> None:
    """Streams progress for POST /jobs/{id}/send-cv. Each message is JSON:
    {"status": "running" | "done" | "error", "detail": "<step or reason>"}.
    Closes the socket right after a "done" or "error" message - the whole
    exchange is a single job's worth of updates, not an open-ended feed."""
    await websocket.accept()
    channel = _cv_channel(job_id)
    queue = progress_hub.subscribe(channel)
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("status") in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        progress_hub.unsubscribe(channel, queue)


@app.post("/init-db")
def init_database() -> dict[str, str]:
    cfg = load_config(CONFIG_PATH)
    if not cfg.database.url:
        raise HTTPException(500, "database.url is not configured")
    db.init_db(cfg.database)
    return {"status": "initialized"}


# ---------------------------------------------------------------------------
# Settings (config.yaml) — system-wide, not tied to any profile
# ---------------------------------------------------------------------------


@app.get("/config")
def get_config() -> dict[str, Any]:
    return load_config(CONFIG_PATH).to_dict()


@app.put("/config")
def update_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the payload by round-tripping it through AppConfig, then save."""
    try:
        cfg = config_from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Invalid configuration: {exc}") from exc
    save_config(cfg, CONFIG_PATH)
    return cfg.to_dict()


# ---------------------------------------------------------------------------
# Profiles (profiles/<name>.yaml) — one entry per person/role being searched for
# ---------------------------------------------------------------------------


@app.get("/profiles")
def list_profiles() -> list[dict[str, Any]]:
    profiles = []
    for path in list_profile_paths(PROFILES_DIR):
        try:
            profiles.append(load_profile(path).to_dict())
        except (OSError, ValueError) as exc:
            raise HTTPException(
                500, f"Could not read profile {path.name}: {exc}"
            ) from exc
    return profiles


@app.get("/profiles/{name}")
def get_profile(name: str) -> dict[str, Any]:
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(404, f"Profile '{name}' not found")
    return load_profile(path).to_dict()


@app.put("/profiles/{name}")
def update_profile(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create or replace profiles/<name>.yaml. Validated via ProfileConfig."""
    payload = {**payload, "name": name}
    try:
        profile = profile_from_dict(name, payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Invalid profile: {exc}") from exc
    save_profile(profile, PROFILES_DIR)
    return profile.to_dict()


@app.delete("/profiles/{name}")
def delete_profile(name: str) -> dict[str, str]:
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(404, f"Profile '{name}' not found")
    path.unlink()
    return {"status": "deleted", "name": name}


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------

_run_lock = asyncio.Lock()
# Tracks pipeline progress independently of _run_lock: the lock is only
# held once the background task actually starts executing (after the
# HTTP response is sent), so checking _run_lock.locked() right after
# POST /run returns is racy - a fast GET /run/status could see "not
# running" before the task has even begun. This flag is set True before
# scheduling the task and cleared when it finishes, so status is accurate
# from the moment /run responds.
_run_state = {"running": False}


def _load_run_profiles(profile_names: list[str] | None):
    if profile_names:
        return [load_profile(PROFILES_DIR / f"{name}.yaml") for name in profile_names]
    return load_profiles(PROFILES_DIR)


_RUN_CHANNEL = "run"


def _run_and_persist(profiles) -> None:
    cfg = load_config(CONFIG_PATH)

    def emit(message: str) -> None:
        progress_hub.publish(_RUN_CHANNEL, {"status": "running", "detail": message})

    results = run_pipeline(cfg, profiles, on_progress=emit)
    for profile in profiles:
        kept = results.get(profile.name, [])
        if not kept:
            continue
        write_reports(cfg, profile, kept, on_progress=emit)
        if cfg.database.url:
            db.save_jobs(kept, cfg.database, profile.name)


@app.post("/run")
async def trigger_run(
    background_tasks: BackgroundTasks, profile: str | None = None
) -> dict[str, Any]:
    """Runs the pipeline for a single profile (?profile=name) or every profile."""
    if _run_lock.locked() or _run_state["running"]:
        raise HTTPException(409, "A run is already in progress")

    profile_names = [profile] if profile else None
    try:
        profiles = _load_run_profiles(profile_names)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    async def _guarded_run() -> None:
        async with _run_lock:
            try:
                await asyncio.to_thread(_run_and_persist, profiles)
                progress_hub.publish(
                    _RUN_CHANNEL, {"status": "done", "detail": "Run complete"}
                )
            except Exception as exc:  # noqa: BLE001 - last-resort net
                print(f"[run] failed unexpectedly: {exc}")
                progress_hub.publish(
                    _RUN_CHANNEL, {"status": "error", "detail": f"Unexpected error: {exc}"}
                )
            finally:
                _run_state["running"] = False

    # Drop any cached final state from the previous run, so a fresh WS
    # subscriber doesn't immediately replay last run's "done"/"error"
    # before this run has published anything of its own.
    progress_hub.clear(_RUN_CHANNEL)
    _run_state["running"] = True
    background_tasks.add_task(_guarded_run)
    # `profiles` is always a list (FastAPI's automatic response model used
    # to be inferred as dict[str, str] from this function's old return
    # type, so returning a list here raised a ResponseValidationError and
    # silently dropped the background task before it ever ran - the run
    # never started even though the endpoint looked like it accepted it).
    return {"status": "started", "profiles": profile_names or ["all"]}


@app.websocket("/ws/run/status")
async def ws_run_status(websocket: WebSocket) -> None:
    """Streams progress for POST /run: fetching, per-profile filtering,
    each job being scored ("[profile] Scoring i/n: ..."), report writes,
    and the Telegram digest send (see cli.py's on_progress calls). Each
    message is JSON: {"status": "running" | "done" | "error", "detail":
    "<step>"}. Closes right after a "done"/"error" message."""
    await websocket.accept()
    queue = progress_hub.subscribe(_RUN_CHANNEL)
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("status") in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        progress_hub.unsubscribe(_RUN_CHANNEL, queue)
