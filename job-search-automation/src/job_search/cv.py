"""ATS-friendly CV generation: tailors a candidate's resume to a specific
job posting using the same Ollama model used for job scoring, then renders
it as a PDF.

Critical design constraint: the LLM is NEVER allowed to invent resume
facts. Company names, job titles, dates, degrees, and institutions always
come straight from the candidate's profiles/<name>.yaml - the LLM only
rewrites/reorders text that already exists there (the summary, the order
skills are listed in, and the phrasing of each job's bullet points) to
better match the posting's language and emphasis. This keeps the tailored
CV truthful by construction rather than by asking the model nicely: every
LLM output is validated against the original data before use, and falls
back to the untouched original on any mismatch (see build_tailored_cv).

PDF layout follows standard ATS-parsing conventions: single column, no
tables/text boxes/images, a built-in PDF font (Helvetica - always embeds
cleanly, every ATS parser handles it), name/contact rendered as normal
body text at the top of the page rather than in a PDF header/footer
region (many ATS parsers skip those entirely), plain "- " bullets, and
literal standard section headers (Summary, Skills, Work Experience,
Education, Projects & Communities).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from fpdf import FPDF

from .config import ResumeConfig, ResumeEducationConfig, ResumeWorkExperienceConfig
from .scoring import OllamaClient, ProgressFn

TAILOR_PROMPT = """You are tailoring a candidate's ATS resume for ONE specific job posting.

STRICT RULES - do not break these:
- Do NOT invent, add, or remove any company, job title, date, degree, institution, or achievement that is not already present in the resume data below.
- You may ONLY: (1) write a tailored professional summary using facts already in the resume, (2) reorder the given skills list (exact same skills, no additions/removals), (3) rephrase each work experience entry's existing bullets to emphasize what's relevant to this posting and mirror its language, without inventing new responsibilities or numbers.

Respond ONLY with JSON, no other text, in exactly this shape:
{{
  "summary": "3-4 sentence tailored professional summary",
  "skills_order": ["skill1", "skill2", ...],
  "work_experience_bullets": [["bullet1", "bullet2"], ["bullet1", "..."], ...]
}}

"work_experience_bullets" must have exactly {n_jobs} entries, in the same order as listed below, one bullet list per job.
"skills_order" must contain exactly these skills, just reordered: {skills_csv}

CANDIDATE'S RESUME:
{resume_text}

JOB POSTING TO TAILOR FOR:
Title: {title}
Company: {company}
Description:
{description}
"""


class ResumeIncomplete(Exception):
    """Raised when a profile has no resume data configured yet - the
    caller (api.py) turns this into a user-facing 400."""


@dataclass
class TailoredCV:
    summary: str
    skills_order: list[str]
    # one bullet list per resume.work_experience entry, same order/length
    work_experience_bullets: list[list[str]]


def resume_to_text(resume: ResumeConfig) -> str:
    """Plain-text rendering of the base (untailored) resume, used as the
    ground-truth context given to the LLM."""
    lines = [f"Name: {resume.name}"]
    if resume.summary:
        lines.append(f"Summary: {resume.summary}")
    if resume.skills:
        lines.append("Skills: " + ", ".join(resume.skills))

    if resume.work_experience:
        lines.append("")
        lines.append("Work Experience:")
        for job in resume.work_experience:
            lines.append(f"- {job.title} at {job.company} ({_work_span(job)})")
            for bullet in job.bullets:
                lines.append(f"  * {bullet}")

    if resume.education:
        lines.append("")
        lines.append("Education:")
        for edu in resume.education:
            degree_line = _degree_line(edu)
            lines.append(f"- {degree_line}, {edu.institution} ({_edu_span(edu)})")

    if resume.projects_and_communities:
        lines.append("")
        lines.append("Projects & Communities:")
        for p in resume.projects_and_communities:
            lines.append(f"- {p.name}: {p.description}")

    return "\n".join(lines)


def _fallback_tailored_cv(resume: ResumeConfig) -> TailoredCV:
    """The untailored resume, verbatim. Used whenever the LLM call fails or
    returns something we can't validate - never worse than not sending a
    CV at all, and never risks shipping a fabricated bullet."""
    return TailoredCV(
        summary=resume.summary,
        skills_order=list(resume.skills),
        work_experience_bullets=[list(job.bullets) for job in resume.work_experience],
    )


def build_tailored_cv(
    client: OllamaClient, resume: ResumeConfig, job, on_progress: ProgressFn | None = None
) -> TailoredCV:
    """`job` needs .title, .company, .description - a JobListing or a
    db.JobRecord both work (same duck-typed usage pattern as telegram.py).

    Raises ResumeIncomplete if the profile has no resume.name set (i.e. the
    resume section was never filled in) - there's nothing to tailor.

    `on_progress`, if given, is wired onto `client` for the duration of this
    call so its own request/response messages (see scoring.py) are included
    alongside the CV-specific ones emitted here, then restored to whatever
    the client had before - `client` may be reused by the caller afterwards
    (e.g. for other jobs) and shouldn't keep emitting into a channel that's
    no longer listening.
    """
    if not resume.name:
        raise ResumeIncomplete(
            "This profile has no resume data yet - add a `resume:` section "
            "to its profiles/<name>.yaml first."
        )

    previous_on_progress = client.on_progress
    if on_progress is not None:
        client.on_progress = on_progress

    def emit(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    try:
        return _build_tailored_cv(client, resume, job, emit)
    finally:
        client.on_progress = previous_on_progress


def _build_tailored_cv(
    client: OllamaClient, resume: ResumeConfig, job, emit: Callable[[str], None]
) -> TailoredCV:
    fallback = _fallback_tailored_cv(resume)

    emit("Preparing tailored CV prompt...")
    prompt = TAILOR_PROMPT.format(
        n_jobs=len(resume.work_experience),
        skills_csv=", ".join(resume.skills),
        resume_text=resume_to_text(resume),
        title=job.title,
        company=job.company,
        description=(job.description or "")[:3000],
    )
    # 600 tokens covers a tailored summary + a reordered skills list + a
    # handful of bullets per job comfortably for a typical resume - this
    # used to be 1200, which on CPU-bound Ollama can take several minutes
    # of full-CPU generation (potentially the entire 300s ollama.timeout)
    # for output that in practice never needs more than a few hundred
    # tokens. Lower num_predict is the actual lever on wall-clock time
    # here; the request/response mechanism (HTTP polling vs WebSockets)
    # doesn't change how fast the model generates tokens.
    raw = client.generate(
        prompt, num_predict=600, model=client.cfg.ollama.cv_model or client.cfg.ollama.model
    )
    if not raw:
        emit("No usable response from Ollama - using untailored resume")
        return fallback

    emit("Validating tailored content against original resume...")
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else {}
    except (ValueError, AttributeError):
        emit("Could not parse Ollama's response - using untailored resume")
        return fallback

    summary = (parsed.get("summary") or "").strip() or resume.summary
    skills_order = _validated_skills_order(parsed.get("skills_order"), resume.skills)
    bullets = _validated_bullets(
        parsed.get("work_experience_bullets"), resume.work_experience
    )
    emit("Tailored CV content ready")
    return TailoredCV(summary=summary, skills_order=skills_order, work_experience_bullets=bullets)


def _validated_skills_order(candidate: object, original: list[str]) -> list[str]:
    """Only accept the LLM's reordering if it's exactly the same set of
    skills (case-insensitive) - any addition, drop, or invented skill
    falls back to the original order instead."""
    if not isinstance(candidate, list) or not all(isinstance(s, str) for s in candidate):
        return list(original)
    if {s.strip().lower() for s in candidate} != {s.strip().lower() for s in original}:
        return list(original)
    return candidate


def _validated_bullets(
    candidate: object, jobs: list[ResumeWorkExperienceConfig]
) -> list[list[str]]:
    """Only accept a rewritten bullet list for a job if it's a non-empty
    list of strings; otherwise that job keeps its original bullets. Applied
    per-job (not all-or-nothing) so one malformed entry doesn't discard
    otherwise-good tailoring for the rest of the resume."""
    if not isinstance(candidate, list) or len(candidate) != len(jobs):
        return [list(j.bullets) for j in jobs]

    out: list[list[str]] = []
    for job, entry in zip(jobs, candidate):
        if isinstance(entry, list) and entry and all(isinstance(b, str) for b in entry):
            out.append(entry)
        else:
            out.append(list(job.bullets))
    return out


def _work_span(job: ResumeWorkExperienceConfig) -> str:
    if not job.start_date and not job.end_date:
        return ""
    return f"{job.start_date} - {job.end_date or 'Present'}"


def _edu_span(edu: ResumeEducationConfig) -> str:
    if not edu.start_date and not edu.end_date:
        return ""
    if edu.end_date:
        return f"{edu.start_date} - {edu.end_date}"
    return edu.start_date


def _degree_line(edu: ResumeEducationConfig) -> str:
    if edu.degree and edu.field_of_study:
        return f"{edu.degree} in {edu.field_of_study}"
    return edu.degree or edu.field_of_study


# --- PDF rendering -------------------------------------------------------

_MARGIN = 18
_PAGE_WIDTH = 210  # A4 mm - ATS parsers don't care about paper size
_MAX_UNBROKEN_WORD = 40  # chars; longer tokens get soft-broken so fpdf2 can wrap them


def _wrap_long_tokens(text: str) -> str:
    """fpdf2 only wraps at whitespace, so a single "word" wider than the
    page's content width raises FPDFException("Not enough horizontal space
    to render a single character") instead of wrapping. This happens in
    practice with LLM-generated keyword-stuffed phrases like
    "Instructional-Design-and-Curriculum-Development-for-Global-Audiences"
    (hyphens/underscores standing in for spaces).

    Break any token longer than _MAX_UNBROKEN_WORD at its hyphens/
    underscores first (usually turns it back into normal separate words);
    if it's still too long after that (e.g. a raw URL with no separators
    at all), force-insert spaces every _MAX_UNBROKEN_WORD characters as a
    last resort, so PDF rendering can never crash on this again regardless
    of what text a model or a profile YAML happens to contain.
    """

    def _fix_token(match: re.Match) -> str:
        token = match.group(0)
        if len(token) <= _MAX_UNBROKEN_WORD:
            return token
        spaced = re.sub(r"[-_]", " ", token)
        longest = max(spaced.split(), key=len, default="")
        if len(longest) <= _MAX_UNBROKEN_WORD:
            return spaced
        return " ".join(
            spaced[i : i + _MAX_UNBROKEN_WORD] for i in range(0, len(spaced), _MAX_UNBROKEN_WORD)
        )

    return re.sub(r"\S+", _fix_token, text)


def _cell(pdf: FPDF, h: float, text: str, **kwargs) -> None:
    pdf.cell(0, h, _wrap_long_tokens(text), **kwargs)


def _multi_cell(pdf: FPDF, h: float, text: str) -> None:
    # wrapmode="CHAR" is fpdf2's own built-in answer to this exact failure
    # mode: if a "word" still doesn't fit the available width even after
    # _wrap_long_tokens() (e.g. the model used a separator like "," or "/"
    # instead of "-"/"_", which that preprocessing doesn't split on), this
    # tells fpdf2 to break mid-character instead of raising
    # FPDFException("Not enough horizontal space..."). Belt and suspenders
    # with _wrap_long_tokens(), which keeps hyphenated phrases readable as
    # separate words in the common case.
    pdf.multi_cell(0, h, _wrap_long_tokens(text), wrapmode="CHAR")


def _new_pdf() -> FPDF:
    pdf = FPDF(format="A4")
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.set_auto_page_break(auto=True, margin=_MARGIN)
    pdf.add_page()
    return pdf


def _section_header(pdf: FPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(20, 20, 20)
    _cell(pdf, 7, title.upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(60, 60, 60)
    y = pdf.get_y()
    pdf.line(_MARGIN, y, _PAGE_WIDTH - _MARGIN, y)
    pdf.ln(2)


def render_ats_pdf(resume: ResumeConfig, tailored: TailoredCV) -> bytes:
    pdf = _new_pdf()

    pdf.set_font("Helvetica", "B", 18)
    _cell(pdf, 10, resume.name or "Candidate", new_x="LMARGIN", new_y="NEXT")

    contact_bits = [b for b in (resume.email, resume.phone) if b]
    if contact_bits:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(70, 70, 70)
        _cell(pdf, 6, " | ".join(contact_bits), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    if tailored.summary:
        _section_header(pdf, "Summary")
        pdf.set_font("Helvetica", "", 10.5)
        _multi_cell(pdf, 5.5, tailored.summary)

    if tailored.skills_order:
        _section_header(pdf, "Skills")
        pdf.set_font("Helvetica", "", 10.5)
        _multi_cell(pdf, 5.5, " | ".join(tailored.skills_order))

    if resume.work_experience:
        _section_header(pdf, "Work Experience")
        for job, bullets in zip(resume.work_experience, tailored.work_experience_bullets):
            pdf.set_font("Helvetica", "B", 11)
            _cell(pdf, 6, f"{job.title} - {job.company}", new_x="LMARGIN", new_y="NEXT")
            meta = " | ".join(b for b in (job.location, _work_span(job)) if b)
            if meta:
                pdf.set_font("Helvetica", "I", 9.5)
                _cell(pdf, 5, meta, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10.5)
            for bullet in bullets:
                _multi_cell(pdf, 5.5, f"- {bullet}")
            pdf.ln(1)

    if resume.education:
        _section_header(pdf, "Education")
        for edu in resume.education:
            pdf.set_font("Helvetica", "B", 11)
            _cell(pdf, 6, _degree_line(edu), new_x="LMARGIN", new_y="NEXT")
            meta = " | ".join(b for b in (edu.institution, _edu_span(edu)) if b)
            if meta:
                pdf.set_font("Helvetica", "I", 9.5)
                _cell(pdf, 5, meta, new_x="LMARGIN", new_y="NEXT")
            if edu.details:
                pdf.set_font("Helvetica", "", 10.5)
                _multi_cell(pdf, 5.5, edu.details)
            pdf.ln(1)

    if resume.projects_and_communities:
        _section_header(pdf, "Projects & Communities")
        for p in resume.projects_and_communities:
            pdf.set_font("Helvetica", "B", 10.5)
            _cell(pdf, 5.5, p.name, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10.5)
            desc = p.description + (f" ({p.url})" if p.url else "")
            if desc.strip():
                _multi_cell(pdf, 5.5, desc)
            pdf.ln(1)

    return bytes(pdf.output())
