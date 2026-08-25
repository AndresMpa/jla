"""LLM-backed scoring and outreach drafting, via a local Ollama instance."""

from __future__ import annotations

import json
import re
from typing import Callable

import requests

from .config import AppConfig
from .models import JobListing

# Called with a short human-readable string at each meaningful step of a
# generation call (e.g. "Sending request to Ollama...", "Received
# response"). Optional everywhere it's threaded through - CLI usage (see
# cli.py's main()) never passes one, so it's always safe to leave as None.
ProgressFn = Callable[[str], None]

# Qwen3 (and other hybrid-reasoning models) default to emitting a long
# <think>...</think> block before the actual answer, which can eat a whole
# request's timeout on slow/CPU-only hardware. Controlled by ollama.think
# in config.yaml (default false). /no_think is Qwen3's own prompt-level
# switch; "think": false in the request body is the equivalent top-level
# option Ollama (>=0.6.9) exposes for models that support toggling it.
# Both are harmless no-ops on models that don't.
NO_THINK_SUFFIX = "\n/no_think"

SCORE_PROMPT = """Evaluate this job posting for a Senior AI Engineer.

Respond ONLY with JSON, no other text:
{{"fit": <1-10>, "income": <1-10>, "reason": "<short explanation>"}}

CANDIDATE PROFILE:
{profile}

POSTING:
Title: {title}
Company: {company}
Location: {location}
Salary: {salary}
Description: {description}

INCOME CRITERIA (1-10):
- 9-10: USA, 250k+ USD
- 7-8: USA/UK, 150-250k
- 5-6: Europe, 100-150k
- <5: low or unspecified
"""

OUTREACH_PROMPT = """Write a short outreach message in English (max 100 words).

CANDIDATE PROFILE:
{profile}

POSTING:
{title} @ {company}

Mention:
- The candidate's flagship open-source project (see profile)
- Their technical stack
- Genuine interest in the company
- A [Name] placeholder for the signature
"""

THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class OllamaClient:
    """Thin wrapper around the Ollama /api/generate endpoint."""

    def __init__(self, cfg: AppConfig, on_progress: ProgressFn | None = None):
        self.cfg = cfg
        self.on_progress = on_progress

    def _emit(self, message: str) -> None:
        if self.on_progress is not None:
            self.on_progress(message)

    def check_connection(self) -> bool:
        base_url = self.cfg.ollama.url.replace("/api/generate", "")
        try:
            resp = requests.get(f"{base_url}/api/tags", timeout=5)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"Could not reach Ollama at {base_url}: {exc}")
            return False

        model_names = [m.get("name") for m in resp.json().get("models", [])]
        if not any(self.cfg.ollama.model in name for name in model_names):
            print(
                f"Model '{self.cfg.ollama.model}' not found. Available: {', '.join(model_names)}"
            )
            return False

        print(f"Connected to Ollama, model '{self.cfg.ollama.model}' is available.")
        return True

    def _generate(self, prompt: str, num_predict: int = 500, model: str | None = None) -> str:
        model = model or self.cfg.ollama.model
        if not self.cfg.ollama.think:
            prompt += NO_THINK_SUFFIX
        self._emit(f"Sending request to Ollama ({model})...")
        try:
            resp = requests.post(
                self.cfg.ollama.url,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "think": self.cfg.ollama.think,  # ignored by models that don't support it
                    "options": {"num_predict": num_predict},
                },
                timeout=self.cfg.ollama.timeout,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()
            self._emit("Received response from Ollama")
            # Belt and suspenders: strip a <think> block if one leaked through
            # despite the flags above (e.g. think=true but caller still wants
            # the block excluded from the parsed answer).
            return THINK_BLOCK_RE.sub("", raw).strip()
        except requests.exceptions.Timeout:
            print(
                f"  Ollama timed out after {self.cfg.ollama.timeout}s - skipping. "
                "If this keeps happening, the model is likely too slow for your "
                "hardware at this timeout; try a smaller/faster model, make sure "
                "ollama.think is false, or raise ollama.timeout in config.yaml."
            )
            self._emit("Ollama timed out")
            return ""
        except requests.RequestException as exc:
            print(f"  Ollama error: {exc}")
            self._emit(f"Ollama error: {exc}")
            return ""

    def generate(self, prompt: str, num_predict: int = 500, model: str | None = None) -> str:
        """Public entry point for callers outside this module (e.g. cv.py's
        CV-tailoring step) that need a raw completion but aren't doing job
        scoring/outreach. `model` overrides `cfg.ollama.model` for this call
        only - cv.py uses this to run tailoring on `cfg.ollama.cv_model`
        when one is configured, independent of whatever model scoring uses.
        Empty string means the call failed or timed out - callers must have
        a sensible fallback, same as score_job/draft_outreach."""
        return self._generate(prompt, num_predict, model=model)

    def score_job(self, job: JobListing, profile_text: str) -> None:
        self._emit(f"Scoring: {job.title} @ {job.company}")
        prompt = SCORE_PROMPT.format(
            profile=profile_text,
            title=job.title,
            company=job.company,
            location=job.location,
            salary=job.salary or "unspecified",
            description=job.description[:1000],
        )
        raw = self._generate(prompt, num_predict=300)
        if not raw:
            job.fit_score = job.income_score = job.score = 0
            job.reasoning = "Timeout"
            return

        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            parsed = json.loads(match.group(0)) if match else {}
            job.fit_score = int(parsed.get("fit", 0))
            job.income_score = int(parsed.get("income", 0))
            job.score = int(
                job.fit_score * self.cfg.scoring.fit_weight
                + job.income_score * self.cfg.scoring.income_weight
            )
            job.reasoning = parsed.get("reason", "")
        except (ValueError, AttributeError) as exc:
            print(f"  Could not parse score response: {exc}")
            job.fit_score = job.income_score = job.score = 0
            job.reasoning = "Error"

    def draft_outreach(self, job: JobListing, profile_text: str) -> None:
        self._emit(f"Drafting outreach message: {job.title} @ {job.company}")
        prompt = OUTREACH_PROMPT.format(
            profile=profile_text, title=job.title, company=job.company
        )
        job.outreach_draft = self._generate(prompt, num_predict=200)
