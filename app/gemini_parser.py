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
4. Skills (all skills listed anywhere in the CV)
5. Job experiences — STRICT DEFINITION (read carefully below)
6. Achievements (any awards, honours, recognitions, or notable achievements mentioned)
7. Certificates (any certifications or certificates mentioned)
8. Trainings (any training programs, workshops, or courses mentioned)
9. Publications (any published papers, articles, books, or research mentioned)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Job Experience" (item 5 above):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INCLUDE in experiences ONLY if ALL of these are true:
  - The candidate worked FOR an external organization, company, or employer
  - It was a formal employment, internship, or paid/credited role
  - There is a real company name OR a real organization name as the employer
  - Examples of VALID entries:
      * Software Engineer at Google
      * Intern at ABC Ltd
      * Junior Developer at XYZ Company
      * Research Assistant at University Lab (if paid/formal role)
      * Executive at a registered club or society (e.g. "President, AUST Robotics Club")

DO NOT INCLUDE in experiences:
  - Personal projects (solo projects the candidate built themselves)
  - Academic projects (university coursework assignments)
  - Club projects (projects done as a member activity, not as an executive role)
  - Hackathon projects (even if they won prizes)
  - Open source contributions
  - Freelance work with no named client/employer
  - Any entry where the "company" would be "Project", "Personal", "Self",
    "Freelance", "N/A", or blank
  - Any entry where the candidate is described as "sole developer",
    "developer (implied)", or similar self-assigned titles with no employer

If an entry does not clearly meet the INCLUDE criteria above,
DO NOT put it in experiences. Leave it out entirely.
Projects and hackathons belong in achievements or extra_sections — not here.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

General Rules:
- Return ONLY valid JSON. No markdown. No code fences. No extra explanation.
- Do NOT wrap the response inside ```json or ``` blocks.
- Do NOT invent or fabricate any information.
- If a field is not present in the CV, return an empty list [] for that field.
- For skills return a flat list of strings.
- For educational_qualifications return a list of objects.
- For experiences return a list of objects.
- For achievements, certificates, trainings, publications return a list of strings.
  Each string should be one complete entry as it appears in the CV.
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


# ── Post-processing filter ────────────────────────────────────────────────────

# Company names that indicate a non-job entry — filtered out after parsing
_INVALID_COMPANY_NAMES = {
    "project", "personal", "personal project", "self", "self-employed",
    "freelance", "n/a", "na", "none", "own", "independent", "solo",
    "hackathon", "open source", "academic", "coursework", "assignment",
    "club project", "university project", "college project",
}


def _filter_experiences(experiences: list) -> list:
    """
    Remove any experience entry where the company name is clearly
    not a real employer (personal projects, hackathons, club projects, etc.).

    This acts as a safety net in case Gemini ignores the prompt rules.
    """
    filtered = []
    for exp in experiences:
        if not isinstance(exp, dict):
            continue

        company  = str(exp.get("company",  "")).strip().lower()
        position = str(exp.get("position", "")).strip().lower()

        # Skip if company is in the invalid set
        if company in _INVALID_COMPANY_NAMES:
            print(
                f"  [filter] Removed non-job entry: "
                f"'{exp.get('position', '')}' at '{exp.get('company', '')}'"
            )
            continue

        # Skip if position contains "implied" — Gemini's own signal for inferred roles
        if "implied" in position:
            print(
                f"  [filter] Removed implied role: "
                f"'{exp.get('position', '')}' at '{exp.get('company', '')}'"
            )
            continue

        # Skip if company is empty or "not found"
        if not company or company == "not found":
            print(
                f"  [filter] Removed entry with no company: "
                f"'{exp.get('position', '')}'"
            )
            continue

        filtered.append(exp)

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

    # Apply post-processing filter as safety net
    parsed["experiences"] = _filter_experiences(parsed["experiences"])

    return parsed