# app/gemini_parser.py

import json
import re
import time
from pathlib import Path

from google import genai

from app.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    RETRY_INITIAL_WAIT,
    RETRY_MAX_ATTEMPTS,
)

# ── Prompt ────────────────────────────────────────────────────────────────────

_PROMPT = """\
You are an expert CV/Resume parser. I am giving you a CV/Resume PDF file.

Analyze the entire CV visually and extract ONLY the following information:

1. Candidate full name
2. Email address
3. Educational qualifications (all degrees, institutions, results, years)
4. Skills — STRICT DEFINITION (read carefully below)
5. Job experiences — STRICT DEFINITION (read carefully below)
6. Achievements (any awards, honours, recognitions, or notable achievements)
7. Certificates (any certifications or certificates mentioned)
8. Trainings (any training programs, workshops, or courses mentioned)
9. Publications (any published papers, articles, books, or research mentioned)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Skills" (item 4 above):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ONLY extract skills that the candidate has EXPLICITLY listed in a
dedicated Skills section, Skills list, Technical Skills section,
Core Competencies section, or any clearly labelled skill listing.

DO NOT include:
- Skills you infer or guess from the candidate's job descriptions
- Skills you infer from project descriptions
- Skills mentioned only inside work experience details
- Skills mentioned only inside education descriptions
- Any skill that is NOT directly written by the candidate as a skill

If the CV has no dedicated skills section, return empty list [] for skills.
Each skill must be a SHORT string — maximum 4 words per skill.
Do not include sentences or phrases as skills.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Job Experience" (item 5 above):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INCLUDE in experiences if ANY of these are true:
  - Formal employment at a real company or organization
  - Internship at a real company or organization
  - Contract or freelance work FOR a named external client or company
  - Executive or leadership role at a registered club, society, or startup
  - Work listed under sections named: "Work Experience", "Experience",
    "Professional Experience", "Employment", "Career History",
    "Recent Works", "Recent Experience", "Projects (Professional)"
    — as long as it involves a real external organization or employer

ALSO INCLUDE "Recent Works" section entries IF:
  - They involve work done for a real client, company, or organization
  - They are professional engagements even if short-term or freelance
  - A company name, client name, or organization name is identifiable

DO NOT INCLUDE:
  - Personal projects (solo projects with no external client/employer)
  - Personal websites or portfolio projects
  - Academic coursework or university assignments
  - Club activity projects (where candidate is a regular member, not executive)
  - Hackathon entries (unless they resulted in a formal role)
  - Any project where company would be "Personal", "Self", "Project",
    "N/A", "None", "Freelance" with no named client, or left blank
  - Open source contributions with no named employer

For each valid experience entry extract:
  - company   : the real company, organization, startup, or client name
  - position  : the candidate's exact job title or role as written in CV
  - duration  : the time period as written in CV
  - details   : the job responsibilities and achievements exactly as
                written in the CV — copy them faithfully, do not summarise

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

General Rules:
- Return ONLY valid JSON. No markdown. No code fences. No extra explanation.
- Do NOT wrap the response inside ```json or ``` blocks.
- Do NOT invent or fabricate any information.
- If a field is not present in the CV, return an empty list [] for list fields.
- For skills return a flat list of short strings.
- For educational_qualifications return a list of objects.
- For experiences return a list of objects.
- For achievements, certificates, trainings, publications return a list of strings.
- Do NOT use "Not Found" for list fields — use empty list [] instead.
- candidate_name and email are strings — use "Not Found" if absent.

Return exactly this JSON structure and nothing else:
{
  "source_file": "",
  "candidate_name": "",
  "email": "",
  "educational_qualifications": [
    {
      "degree": "",
      "institution": "",
      "result": "",
      "year": ""
    }
  ],
  "skills": [],
  "experiences": [
    {
      "company": "",
      "position": "",
      "duration": "",
      "details": ""
    }
  ],
  "achievements": [],
  "certificates": [],
  "trainings": [],
  "publications": []
}

Return only the JSON object now.
"""

# ── Gemini client ─────────────────────────────────────────────────────────────

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. "
                "Please add your API key to the .env file."
            )
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    text = raw.strip()

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    brace_start = text.find("{")
    brace_end   = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        text = text[brace_start : brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse Gemini response as JSON.\n"
            f"Error: {exc}\n"
            f"Raw response (first 500 chars): {raw[:500]}"
        ) from exc


# ── Retryable error check ─────────────────────────────────────────────────────

def _is_retryable_error(exc: Exception) -> bool:
    error_str = str(exc).lower()
    retryable_keywords = [
        "429", "500", "503", "504",
        "resource_exhausted", "quota", "rate_limit", "rate limit",
        "per minute", "too many requests", "unavailable", "high demand",
        "temporarily", "try again", "overloaded", "internal error",
        "timeout", "deadline exceeded", "server error", "service unavailable",
    ]
    return any(kw in error_str for kw in retryable_keywords)


def _retry_reason(exc: Exception) -> str:
    error_str = str(exc).lower()
    if "503" in error_str or "unavailable" in error_str or "high demand" in error_str:
        return "Server overloaded (503) — Google servers are busy"
    if "429" in error_str or "quota" in error_str or "rate" in error_str:
        return "Rate limit hit (429) — too many requests"
    if "500" in error_str or "internal" in error_str:
        return "Internal server error (500)"
    if "504" in error_str or "timeout" in error_str or "deadline" in error_str:
        return "Request timeout (504)"
    return "Temporary server error"


# ── File upload / delete ──────────────────────────────────────────────────────

def _upload_pdf(pdf_path: Path) -> object:
    client = _get_client()
    with open(pdf_path, "rb") as f:
        uploaded_file = client.files.upload(
            file=f,
            config={
                "mime_type": "application/pdf",
                "display_name": pdf_path.name,
            },
        )
    return uploaded_file


def _delete_uploaded_file(uploaded_file: object) -> None:
    try:
        _get_client().files.delete(name=uploaded_file.name)
    except Exception:
        pass


# ── Core call with retry ──────────────────────────────────────────────────────

def _call_gemini_with_retry(pdf_path: Path) -> str:
    wait       = RETRY_INITIAL_WAIT
    last_error = None

    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        uploaded_file = None
        try:
            if attempt == 1:
                print(f"  → Uploading PDF to Gemini for analysis...")
            else:
                print(
                    f"  → Uploading PDF to Gemini for analysis "
                    f"(attempt {attempt}/{RETRY_MAX_ATTEMPTS})..."
                )

            uploaded_file = _upload_pdf(pdf_path)

            response = _get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[uploaded_file, _PROMPT],
            )

            raw_text = response.text
            if not raw_text or not raw_text.strip():
                raise RuntimeError(
                    f"Gemini returned an empty response for '{pdf_path.name}'."
                )

            return raw_text

        except Exception as exc:
            last_error = exc

            if _is_retryable_error(exc):
                if attempt < RETRY_MAX_ATTEMPTS:
                    reason = _retry_reason(exc)
                    print(
                        f"\n  ⚠ [{reason}]"
                        f"\n  Attempt {attempt}/{RETRY_MAX_ATTEMPTS} failed "
                        f"for '{pdf_path.name}'."
                        f"\n  Waiting {wait}s before retry {attempt + 1}...\n"
                    )
                    time.sleep(wait)
                    wait = min(wait * 2, 120)
                    continue
                else:
                    raise RuntimeError(
                        f"Gemini failed for '{pdf_path.name}' "
                        f"after {RETRY_MAX_ATTEMPTS} attempts.\n"
                        f"Last error: {exc}"
                    ) from exc
            else:
                raise RuntimeError(
                    f"Gemini API call failed for '{pdf_path.name}': {exc}"
                ) from exc

        finally:
            if uploaded_file is not None:
                _delete_uploaded_file(uploaded_file)

    raise RuntimeError(
        f"Retry loop ended unexpectedly for '{pdf_path.name}'.\n"
        f"Last error: {last_error}"
    )


# ── Post-processing filters ───────────────────────────────────────────────────

_INVALID_COMPANY_NAMES = {
    "project", "personal", "personal project", "self", "self-employed",
    "freelance", "n/a", "na", "none", "own", "independent", "solo",
    "hackathon", "open source", "academic", "coursework", "assignment",
    "club project", "university project", "college project",
    "personal website", "portfolio", "side project",
}


def _filter_experiences(experiences: list) -> list:
    """Remove non-job entries as a safety net after Gemini parsing."""
    filtered = []
    for exp in experiences:
        if not isinstance(exp, dict):
            continue

        company  = str(exp.get("company",  "")).strip().lower()
        position = str(exp.get("position", "")).strip().lower()

        if company in _INVALID_COMPANY_NAMES:
            print(
                f"  [filter] Removed non-job: "
                f"'{exp.get('position','')}' at '{exp.get('company','')}'"
            )
            continue

        if "implied" in position:
            print(
                f"  [filter] Removed implied role: '{exp.get('position','')}'"
            )
            continue

        if not company or company == "not found":
            print(
                f"  [filter] Removed entry with no company: "
                f"'{exp.get('position','')}'"
            )
            continue

        filtered.append(exp)

    return filtered


def _filter_skills(skills: list) -> list:
    """
    Clean the skills list:
    - Remove empty entries
    - Remove entries that are full sentences (more than 5 words)
    - Strip extra whitespace
    - Remove duplicates while preserving order
    """
    seen     = set()
    filtered = []

    for skill in skills:
        if not isinstance(skill, str):
            continue
        s = skill.strip()
        if not s:
            continue
        # Skip sentence-like entries (more than 5 words)
        if len(s.split()) > 5:
            print(f"  [filter] Removed sentence-like skill: '{s[:60]}'")
            continue
        # Deduplicate case-insensitively
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(s)

    return filtered


# ── Public API ────────────────────────────────────────────────────────────────

def parse_cv(pdf_path: Path) -> dict:
    """
    Send the PDF directly to Gemini for analysis.
    Returns structured CV data as a Python dictionary.
    """
    raw_text = _call_gemini_with_retry(pdf_path)
    parsed   = _extract_json(raw_text)

    parsed["source_file"] = pdf_path.name
    parsed.setdefault("candidate_name", "Not Found")
    parsed.setdefault("email",          "Not Found")
    parsed.setdefault("educational_qualifications", [])
    parsed.setdefault("skills",         [])
    parsed.setdefault("experiences",    [])
    parsed.setdefault("achievements",   [])
    parsed.setdefault("certificates",   [])
    parsed.setdefault("trainings",      [])
    parsed.setdefault("publications",   [])

    # Post-processing filters
    parsed["experiences"] = _filter_experiences(parsed["experiences"])
    parsed["skills"]      = _filter_skills(parsed["skills"])

    return parsed