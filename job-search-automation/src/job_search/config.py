"""Loads and validates config.yaml (system) and profiles/*.yaml (candidates).

config.yaml holds settings that apply to every run: Ollama connection,
which providers are enabled, scoring weights, the database URL. It has
nothing to do with *who* you're searching jobs for.

profiles/*.yaml hold the "who": the free-text candidate profile and the
keyword lists used to filter listings. Each file is one person/role you
want to search for; a run walks every profile in profiles/ (or just the
one passed with --profile) against the same fetched listings.
"""

from __future__ import annotations

import os
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_PROFILES_DIR = Path("profiles")
DEFAULT_OUTPUT_BASE_DIR = Path("profiles/output")


def _detect_ollama_url() -> str:
    """Best-effort default when ollama.url is not set in config.yaml."""
    if os.path.exists("/.dockerenv"):
        try:
            socket.gethostbyname("host.docker.internal")
            return "http://host.docker.internal:11434/api/generate"
        except OSError:
            return "http://172.17.0.1:11434/api/generate"
    return "http://localhost:11434/api/generate"


@dataclass(frozen=True)
class OllamaConfig:
    url: str = field(default_factory=_detect_ollama_url)
    model: str = "qwen2.5:14b"
    timeout: int = 300
    # Hybrid-reasoning models (Qwen3, DeepSeek-R1, ...) emit a long
    # <think>...</think> block before answering unless told not to. That's
    # usually wasted time for a JSON scoring/outreach task, so default to
    # off. Set true to let the model think — slower, occasionally better
    # reasoning quality on ambiguous postings. No-op on models that don't
    # support toggling it.
    think: bool = False


@dataclass(frozen=True)
class KeywordsConfig:
    """Keyword lists used by the (cheap, pre-LLM) filtering stage. Per-profile."""

    target: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    seniority: list[str] = field(default_factory=list)
    ai: list[str] = field(default_factory=list)
    tech: list[str] = field(default_factory=list)

    def merge(self, other: KeywordsConfig) -> KeywordsConfig:
        """Union with another KeywordsConfig, de-duplicated. Used to build a
        single cheap prefilter that covers every loaded profile at fetch time."""
        return KeywordsConfig(
            target=sorted(set(self.target) | set(other.target)),
            exclude=sorted(set(self.exclude) | set(other.exclude)),
            seniority=sorted(set(self.seniority) | set(other.seniority)),
            ai=sorted(set(self.ai) | set(other.ai)),
            tech=sorted(set(self.tech) | set(other.tech)),
        )


@dataclass(frozen=True)
class ProvidersConfig:
    remoteok: bool = True
    remotive: bool = True
    weworkremotely: bool = True
    python_jobs: bool = True
    vuejobs: bool = True
    hackernews: bool = True
    arbeitnow: bool = True
    greenhouse: bool = True
    # Off by default: ships with an empty companies list until real
    # tenant/site values are confirmed per company (see fetchers/workday.py).
    workday: bool = False
    himalayas: bool = True
    jobicy: bool = True


@dataclass(frozen=True)
class WeWorkRemotelyConfig:
    categories: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RemotiveConfig:
    """Remotive categories to pull. Was hardcoded to 'software-dev' only -
    now configurable so non-technical profiles (content, customer-support,
    hr, writing...) can actually get matches. See
    https://remotive.com/api/remote-jobs/categories for the full list."""

    categories: list[str] = field(
        default_factory=lambda: [
            "software-dev",
            "customer-support",
            "writing",
            "hr",
            "all-others",
        ]
    )


@dataclass(frozen=True)
class JobicyConfig:
    """Jobicy is a general (non-tech-only) remote job board. `industries`
    maps to Jobicy's `industry` query param; leave empty to fetch every
    industry. See https://jobicy.com/api/v2/remote-jobs for valid values."""

    industries: list[str] = field(default_factory=list)
    geo: str = ""


@dataclass(frozen=True)
class GreenhouseCompanyConfig:
    name: str
    board_token: str


@dataclass(frozen=True)
class GreenhouseConfig:
    # Verified working in the POC. Add companies here only after confirming
    # their board exists at https://boards.greenhouse.io/<token> - some
    # companies migrate off Greenhouse and the token silently 404s.
    companies: list[GreenhouseCompanyConfig] = field(
        default_factory=lambda: [
            GreenhouseCompanyConfig(name="Celonis", board_token="celonis"),
            GreenhouseCompanyConfig(name="Databricks", board_token="databricks"),
        ]
    )


@dataclass(frozen=True)
class WorkdayCompanyConfig:
    name: str
    tenant: str
    site: str
    wd_server: str = "wd1"


@dataclass(frozen=True)
class WorkdayConfig:
    # Empty until real tenant/site values are confirmed (see
    # fetchers/workday.py for how to read them off a real job link).
    companies: list[WorkdayCompanyConfig] = field(default_factory=list)


@dataclass(frozen=True)
class ScoringConfig:
    min_score_to_keep: int = 6
    fit_weight: float = 0.4
    income_weight: float = 0.6


@dataclass(frozen=True)
class DatabaseConfig:
    # Standard SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@host:5432/jobs
    # Overridable at runtime with the DATABASE_URL env var (handy in Docker
    # Compose where the host differs per environment). Empty = DB disabled;
    # the CLI still writes CSV/Markdown only.
    url: str = ""


@dataclass(frozen=True)
class AppConfig:
    """System-wide settings, loaded from config.yaml. No candidate data lives
    here anymore — see ProfileConfig / profiles/*.yaml for that."""

    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    weworkremotely: WeWorkRemotelyConfig = field(default_factory=WeWorkRemotelyConfig)
    remotive: RemotiveConfig = field(default_factory=RemotiveConfig)
    jobicy: JobicyConfig = field(default_factory=JobicyConfig)
    greenhouse: GreenhouseConfig = field(default_factory=GreenhouseConfig)
    workday: WorkdayConfig = field(default_factory=WorkdayConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    output_base_dir: str = str(DEFAULT_OUTPUT_BASE_DIR)

    def to_dict(self) -> dict[str, Any]:
        """JSON/YAML-serializable view, used by the settings API and save_config()."""
        return asdict(self)


@dataclass(frozen=True)
class ResumeWorkExperienceConfig:
    """One reverse-chronological entry. `end_date` empty/"" or "Present"
    means current role. Dates and employer/title are rendered exactly as
    given here — the CV-tailoring LLM step never touches them, only the
    bullet phrasing (see cv.py)."""

    title: str = ""
    company: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResumeEducationConfig:
    institution: str = ""
    degree: str = ""
    field_of_study: str = ""
    start_date: str = ""
    end_date: str = ""
    details: str = ""


@dataclass(frozen=True)
class ResumeProjectConfig:
    """One entry under "Projects & Communities" - a side project, open-source
    contribution, community/volunteer role, or similar."""

    name: str = ""
    description: str = ""
    url: str = ""


@dataclass(frozen=True)
class ResumeConfig:
    """Structured ATS-resume data, used to render a CV tailored to a
    specific job posting (see cv.py). Kept separate from the free-text
    `profile` field on ProfileConfig, which is written for the job-matching
    LLM prompt, not for a clean, parseable resume document.

    Schema follows standard ATS-resume conventions: reverse-chronological
    work experience with real dates (no tables/columns), a flat skills
    list, standard section headers, single-column layout. Name/email/phone
    are rendered as plain body text at the top of the document rather than
    in a page header/footer, since many ATS parsers ignore header/footer
    regions entirely.
    """

    name: str = ""
    email: str = ""
    phone: str = ""
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    work_experience: list[ResumeWorkExperienceConfig] = field(default_factory=list)
    education: list[ResumeEducationConfig] = field(default_factory=list)
    # "Projects & Communities" section.
    projects_and_communities: list[ResumeProjectConfig] = field(
        default_factory=list
    )


@dataclass(frozen=True)
class TelegramConfig:
    """Reserved for future work: sending each profile's digest via Telegram.
    Not used yet — just keeps the schema stable so profiles don't need to be
    rewritten once that lands."""

    chat_id: str | None = None
    enabled: bool = False


@dataclass(frozen=True)
class ProfileOutputConfig:
    csv_filename: str = "job_matches.csv"
    md_filename: str = "job_matches.md"


@dataclass(frozen=True)
class ProfileConfig:
    """One person/role to search jobs for. Lives in profiles/<name>.yaml."""

    name: str
    profile: str
    keywords: KeywordsConfig = field(default_factory=KeywordsConfig)
    output: ProfileOutputConfig = field(default_factory=ProfileOutputConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    resume: ResumeConfig = field(default_factory=ResumeConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def output_dir(self, base_dir: str | Path = DEFAULT_OUTPUT_BASE_DIR) -> Path:
        return Path(base_dir) / self.name

    def csv_path(self, base_dir: str | Path = DEFAULT_OUTPUT_BASE_DIR) -> Path:
        return self.output_dir(base_dir) / self.output.csv_filename

    def md_path(self, base_dir: str | Path = DEFAULT_OUTPUT_BASE_DIR) -> Path:
        return self.output_dir(base_dir) / self.output.md_filename


def _section(raw: dict[str, Any], key: str, cls):
    return cls(**raw.get(key, {})) if raw.get(key) else cls()


def _greenhouse_section(raw: dict[str, Any]) -> GreenhouseConfig:
    """Nested list of dataclasses needs its own loader - _section() only
    handles flat dicts, and companies is a list[GreenhouseCompanyConfig]."""
    gh_raw = raw.get("greenhouse")
    if not gh_raw:
        return GreenhouseConfig()
    companies = [GreenhouseCompanyConfig(**c) for c in gh_raw.get("companies", [])]
    return GreenhouseConfig(companies=companies)


def _workday_section(raw: dict[str, Any]) -> WorkdayConfig:
    wd_raw = raw.get("workday") or {}
    companies = [WorkdayCompanyConfig(**c) for c in wd_raw.get("companies", [])]
    return WorkdayConfig(companies=companies)


def _resume_section(raw: dict[str, Any]) -> ResumeConfig:
    """Nested lists of dataclasses (work_experience, education,
    projects_and_communities) need their own loader, same reason as
    _greenhouse_section - _section() only handles flat dicts."""
    r = raw.get("resume") or {}
    return ResumeConfig(
        name=r.get("name", ""),
        email=r.get("email", ""),
        phone=r.get("phone", ""),
        summary=(r.get("summary", "") or "").strip(),
        skills=list(r.get("skills", []) or []),
        work_experience=[
            ResumeWorkExperienceConfig(**w) for w in r.get("work_experience", []) or []
        ],
        education=[
            ResumeEducationConfig(**e) for e in r.get("education", []) or []
        ],
        projects_and_communities=[
            ResumeProjectConfig(**p)
            for p in r.get("projects_and_communities", []) or []
        ],
    )


def _env_bool(name: str) -> bool | None:
    """Parse a boolean env var (1/true/yes, case-insensitive). None if unset."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in ("1", "true", "yes", "on")


def config_from_dict(raw: dict[str, Any]) -> AppConfig:
    """Build an AppConfig from a plain dict, applying the same env overrides
    that load_config() does. Used directly by the settings API when it
    receives a JSON body instead of reading a file.
    """
    ollama_raw = raw.get("ollama", {}) or {}
    ollama_think = _env_bool("OLLAMA_THINK")
    ollama = OllamaConfig(
        url=os.environ.get("OLLAMA_URL")
        or ollama_raw.get("url")
        or _detect_ollama_url(),
        model=os.environ.get("OLLAMA_MODEL") or ollama_raw.get("model", "qwen2.5:14b"),
        timeout=int(os.environ.get("OLLAMA_TIMEOUT") or ollama_raw.get("timeout", 300)),
        think=ollama_think
        if ollama_think is not None
        else bool(ollama_raw.get("think", False)),
    )
    database_raw = raw.get("database", {}) or {}
    database = DatabaseConfig(
        url=os.environ.get("DATABASE_URL") or database_raw.get("url", "")
    )

    return AppConfig(
        ollama=ollama,
        providers=_section(raw, "providers", ProvidersConfig),
        weworkremotely=_section(raw, "weworkremotely", WeWorkRemotelyConfig),
        remotive=_section(raw, "remotive", RemotiveConfig),
        jobicy=_section(raw, "jobicy", JobicyConfig),
        greenhouse=_greenhouse_section(raw),
        workday=_workday_section(raw),
        scoring=_section(raw, "scoring", ScoringConfig),
        database=database,
        output_base_dir=raw.get("output_base_dir", str(DEFAULT_OUTPUT_BASE_DIR)),
    )


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Read config.yaml (falling back to defaults for any missing section)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config.yaml.example to config.yaml and edit it."
        )
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return config_from_dict(raw)


def save_config(cfg: AppConfig, path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    """Persist an AppConfig back to config.yaml (used by the settings API)."""
    path = Path(path)
    path.write_text(
        yaml.safe_dump(cfg.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def profile_from_dict(name: str, raw: dict[str, Any]) -> ProfileConfig:
    telegram_raw = raw.get("telegram", {}) or {}
    return ProfileConfig(
        name=name,
        profile=(raw.get("profile", "") or "").strip(),
        keywords=_section(raw, "keywords", KeywordsConfig),
        output=_section(raw, "output", ProfileOutputConfig),
        telegram=TelegramConfig(
            chat_id=telegram_raw.get("chat_id"),
            enabled=bool(telegram_raw.get("enabled", False)),
        ),
        resume=_resume_section(raw),
    )


def load_profile(path: str | Path) -> ProfileConfig:
    """Read a single profiles/<name>.yaml file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = raw.get("name") or path.stem
    return profile_from_dict(name, raw)


def save_profile(
    profile: ProfileConfig, dir_path: str | Path = DEFAULT_PROFILES_DIR
) -> Path:
    """Persist a ProfileConfig to profiles/<name>.yaml. Returns the written path."""
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{profile.name}.yaml"
    path.write_text(
        yaml.safe_dump(profile.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def list_profile_paths(dir_path: str | Path = DEFAULT_PROFILES_DIR) -> list[Path]:
    dir_path = Path(dir_path)
    if not dir_path.exists():
        return []
    return sorted(
        p for p in dir_path.glob("*.yaml") if p.name != "profile.yaml.example"
    )


def load_profiles(dir_path: str | Path = DEFAULT_PROFILES_DIR) -> list[ProfileConfig]:
    """Load every profiles/<name>.yaml in the given directory."""
    profiles = [load_profile(p) for p in list_profile_paths(dir_path)]
    if not profiles:
        raise FileNotFoundError(
            f"No profiles found in {dir_path}/. Copy profiles/profile.yaml.example "
            "to profiles/<name>.yaml and edit it."
        )
    return profiles
