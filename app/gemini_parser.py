# app/gemini_parser.py

import json
import re
import time
from pathlib import Path

from google import genai
from google.genai import types

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
3. Educational qualifications
4. Skills
5. Work experiences
6. Personal projects
7. Achievements
8. Certificates
9. Trainings
10. Publications

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Skills":
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ONLY extract skills that the candidate has EXPLICITLY listed in a
dedicated Skills section, Skills list, Technical Skills section,
Core Competencies section, or any clearly labelled skill listing.

DO NOT include:
- Skills you infer or guess from job descriptions
- Skills you infer from project descriptions
- Skills mentioned only inside work experience details
- Skills mentioned only inside education descriptions
- Any skill that is not directly written by the candidate as a skill

If the CV has no dedicated skills section, return [] for skills.
Each skill must be a SHORT string, maximum 4 words.
Do not include sentences or long phrases as skills.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Work Experience":
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Work Experience must include ONLY real job/work-type roles.

INCLUDE in experiences ONLY if the entry is one of these:
- Full-time job
- Part-time job
- Internship
- Apprenticeship
- Startup role
- Business role
- Entrepreneur/founder/co-founder role
- Contract work for a real named client/company
- Freelance work for a real named client/company
- Professional work for a real organization
- Executive/official club position, such as President, Vice President,
  General Secretary, Treasurer, Executive Member, Organizer, Lead, Coordinator,
  Convener, Campus Ambassador, Volunteer Coordinator, etc.

IMPORTANT:
If a student mentions a club position as a responsibility/role, include it in Work Experience.
Example:
- President at ABC Club
- Executive Member at CSE Club
- Organizer at Robotics Club
- Volunteer Coordinator at Computer Club

DO NOT include in Work Experience:
- Personal project
- Solo project
- Academic project
- University assignment
- Course project
- Club project
- Portfolio project
- Website project
- GitHub project
- Hackathon project
- Open-source project without employer/client
- Any project where company/client/employer is not clearly mentioned
- Any item where company would be Personal, Self, Project, N/A, None,
  Academic, University, Club Project, Portfolio, Solo, or Side Project

For each valid Work Experience entry extract:
- company: real company, business, startup, organization, or club name
- position: exact role/title
- duration: time period as written
- details: short responsibilities/details from CV

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Personal Projects":
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Personal Projects must include:
- Personal software projects
- Solo projects
- Academic projects
- Course projects
- University projects
- Club projects
- Portfolio projects
- GitHub projects
- Hackathon projects
- Research/demo projects
- Any project that is not a real job/internship/client work

For each personal project extract:
- project_name: project title/name
- tech_stack: technologies/tools/languages/frameworks mentioned
- summary: short summary of the project

If the CV has a long project description, shorten it into a clean 1-2 sentence summary.
Do not copy very long descriptions.
Do not put personal projects inside experiences.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Achievements":
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Achievements must include:
- Awards
- Honours
- Recognitions
- Competitions won
- Notable accomplishments
- Scholarships
- Contest placements

Do not put certificates here unless the CV clearly presents them as achievements.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Certificates":
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Certificates must include:
- Certifications
- Certificates
- Professional certificates
- Online course certificates
- Vendor certificates

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Trainings":
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trainings must include:
- Training programs
- Workshops
- Bootcamps
- Short courses
- Skill development programs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT DEFINITION OF "Publications":
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Publications must include:
- Published papers
- Articles
- Books
- Research publications
- Journals
- Conference papers

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

General Rules:
- Return ONLY valid JSON.
- No markdown.
- No code fences.
- No extra explanation.
- Do NOT invent or fabricate information.
- If a list field is missing, return [].
- Do NOT use "Not Found" for list fields.
- candidate_name and email are strings; use "Not Found" if absent.
- For achievements, certificates, trainings, publications return list of strings.
- For skills return a flat list of short strings.
- For personal_projects return a list of objects.
- For experiences return a list of objects.
- Personal projects must NEVER be inside experiences.
- Work Experience must contain only job/internship/business/startup/official club roles.

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
  "personal_projects": [
    {
      "project_name": "",
      "tech_stack": "",
      "summary": ""
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
    brace_end = text.rfind("}")

    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        text = text[brace_start: brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse Gemini response as JSON.\n"
            f"Error: {exc}\n"
            f"Raw response (first 500 chars): {raw[:500]}"
        ) from exc


# ── Retryable error check ─────────────────────────────────────────────────────

def _is_zero_quota_error(exc: Exception) -> bool:
    error_str = str(exc).lower()

    zero_quota_patterns = [
        "quota_limit_value': '0'",
        '"quota_limit_value": "0"',
        "quota_limit_value: 0",
        "quota_limit_value=0",
        "limit_value': '0'",
        '"limit_value": "0"',
    ]

    return any(pattern in error_str for pattern in zero_quota_patterns)


def _is_retryable_error(exc: Exception) -> bool:
    if _is_zero_quota_error(exc):
        return False

    error_str = str(exc).lower()

    retryable_keywords = [
        "429",
        "500",
        "503",
        "504",
        "resource_exhausted",
        "rate_limit",
        "rate limit",
        "per minute",
        "too many requests",
        "unavailable",
        "high demand",
        "temporarily",
        "try again",
        "overloaded",
        "internal error",
        "timeout",
        "deadline exceeded",
        "server error",
        "service unavailable",
    ]

    return any(keyword in error_str for keyword in retryable_keywords)


def _retry_reason(exc: Exception) -> str:
    error_str = str(exc).lower()

    if _is_zero_quota_error(exc):
        return "Quota is 0 — this project/API key has no active Gemini quota"

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

    with open(pdf_path, "rb") as file:
        uploaded_file = client.files.upload(
            file=file,
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
    wait = RETRY_INITIAL_WAIT
    last_error = None

    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        uploaded_file = None

        try:
            if attempt == 1:
                print("  → Uploading PDF to Gemini for analysis...")
            else:
                print(
                    f"  → Uploading PDF to Gemini for analysis "
                    f"(attempt {attempt}/{RETRY_MAX_ATTEMPTS})..."
                )

            uploaded_file = _upload_pdf(pdf_path)

            response = _get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[uploaded_file, _PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            raw_text = response.text

            if not raw_text or not raw_text.strip():
                raise RuntimeError(
                    f"Gemini returned an empty response for '{pdf_path.name}'."
                )

            return raw_text

        except Exception as exc:
            last_error = exc

            if _is_zero_quota_error(exc):
                raise RuntimeError(
                    "Gemini quota is 0 for this Google project/API key. "
                    "Retrying will not fix this. Use another Gemini API key "
                    "from a project with active quota or enable billing/quota. "
                    f"Original error: {exc}"
                ) from exc

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

                raise RuntimeError(
                    f"Gemini failed for '{pdf_path.name}' "
                    f"after {RETRY_MAX_ATTEMPTS} attempts.\n"
                    f"Last error: {exc}"
                ) from exc

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


# ── Post-processing helpers ───────────────────────────────────────────────────

_INVALID_COMPANY_NAMES = {
    "project",
    "projects",
    "personal",
    "personal project",
    "self",
    "self-employed",
    "n/a",
    "na",
    "none",
    "own",
    "independent",
    "solo",
    "hackathon",
    "open source",
    "academic",
    "coursework",
    "assignment",
    "club project",
    "university project",
    "college project",
    "personal website",
    "portfolio",
    "side project",
    "github",
    "final year project",
    "capstone project",
    "course project",
}

_PROJECT_KEYWORDS = {
    "personal project",
    "solo project",
    "academic project",
    "course project",
    "university project",
    "college project",
    "club project",
    "portfolio project",
    "github project",
    "hackathon project",
    "final year project",
    "capstone project",
    "project",
    "projects",
    "portfolio",
    "github",
}

_REAL_WORK_ROLE_KEYWORDS = {
    "intern",
    "internship",
    "developer",
    "engineer",
    "manager",
    "officer",
    "assistant",
    "executive",
    "president",
    "vice president",
    "secretary",
    "treasurer",
    "organizer",
    "coordinator",
    "lead",
    "founder",
    "co-founder",
    "owner",
    "business",
    "consultant",
    "teacher",
    "trainer",
    "ambassador",
    "volunteer coordinator",
    "member secretary",
}


def _shorten_text(text: str, max_words: int = 35) -> str:
    text = str(text).strip()

    if not text:
        return ""

    words = text.split()

    if len(words) <= max_words:
        return text

    return " ".join(words[:max_words]).rstrip(".,;") + "."


def _looks_like_personal_project(exp: dict) -> bool:
    company = str(exp.get("company", "")).strip().lower()
    position = str(exp.get("position", "")).strip().lower()
    details = str(exp.get("details", "")).strip().lower()

    joined = f"{company} {position} {details}"

    if company in _INVALID_COMPANY_NAMES:
        return True

    # If this is clearly an official club/job role, keep as experience.
    if any(role in position for role in _REAL_WORK_ROLE_KEYWORDS):
        return False

    # Project-like entries should not stay in Work Experience.
    if any(keyword in joined for keyword in _PROJECT_KEYWORDS):
        return True

    if not company or company == "not found":
        return True

    return False


def _experience_to_personal_project(exp: dict) -> dict:
    company = str(exp.get("company", "")).strip()
    position = str(exp.get("position", "")).strip()
    details = str(exp.get("details", "")).strip()

    project_name = position or company or "Project"

    if company:
        company_lower = company.lower()
        if company_lower not in _INVALID_COMPANY_NAMES:
            if company_lower not in project_name.lower():
                project_name = f"{project_name} - {company}"

    return {
        "project_name": project_name or "Project",
        "tech_stack": "",
        "summary": _shorten_text(details, max_words=35),
    }


def _filter_experiences_and_extract_projects(experiences: list) -> tuple[list, list]:
    """
    Keep only real job/internship/business/startup/official club-position experiences.
    Move personal/solo/academic/club projects into personal_projects.
    """

    valid_experiences = []
    moved_projects = []

    for exp in experiences:
        if not isinstance(exp, dict):
            continue

        company = str(exp.get("company", "")).strip().lower()
        position = str(exp.get("position", "")).strip().lower()

        if "implied" in position:
            print(f"  [filter] Moved implied role to Personal Projects: '{exp.get('position', '')}'")
            moved_projects.append(_experience_to_personal_project(exp))
            continue

        if _looks_like_personal_project(exp):
            print(
                f"  [filter] Moved project from Work Experience to Personal Projects: "
                f"'{exp.get('position', '')}' at '{exp.get('company', '')}'"
            )
            moved_projects.append(_experience_to_personal_project(exp))
            continue

        if not company or company == "not found":
            print(
                f"  [filter] Moved no-company entry to Personal Projects: "
                f"'{exp.get('position', '')}'"
            )
            moved_projects.append(_experience_to_personal_project(exp))
            continue

        valid_experiences.append(
            {
                "company": str(exp.get("company", "")).strip(),
                "position": str(exp.get("position", "")).strip(),
                "duration": str(exp.get("duration", "")).strip(),
                "details": _shorten_text(str(exp.get("details", "")).strip(), max_words=60),
            }
        )

    return valid_experiences, moved_projects


def _filter_skills(skills: list) -> list:
    """
    Clean the skills list:
    - Remove empty entries
    - Remove entries that are full sentences
    - Strip extra whitespace
    - Remove duplicates while preserving order
    """

    seen = set()
    filtered = []

    for skill in skills:
        if not isinstance(skill, str):
            continue

        value = skill.strip()

        if not value:
            continue

        if len(value.split()) > 4:
            print(f"  [filter] Removed sentence-like skill: '{value[:60]}'")
            continue

        key = value.lower()

        if key in seen:
            continue

        seen.add(key)
        filtered.append(value)

    return filtered


def _filter_personal_projects(projects: list) -> list:
    """
    Clean personal projects:
    - Keep only dict objects
    - Ensure project_name, tech_stack, summary exist
    - Shorten long summaries
    - Remove duplicate projects
    """

    filtered = []
    seen = set()

    for project in projects:
        if not isinstance(project, dict):
            continue

        name = str(project.get("project_name", "")).strip()
        tech_stack = str(project.get("tech_stack", "")).strip()
        summary = str(project.get("summary", "")).strip()

        if not name and not summary:
            continue

        if not name:
            name = "Project"

        summary = _shorten_text(summary, max_words=35)

        key = name.lower()

        if key in seen:
            continue

        seen.add(key)

        filtered.append(
            {
                "project_name": name,
                "tech_stack": tech_stack,
                "summary": summary,
            }
        )

    return filtered


def _clean_string_list(items: list) -> list:
    cleaned = []
    seen = set()

    if not isinstance(items, list):
        return []

    for item in items:
        if not isinstance(item, str):
            continue

        value = item.strip()

        if not value:
            continue

        key = value.lower()

        if key in seen:
            continue

        seen.add(key)
        cleaned.append(value)

    return cleaned


def _normalize_education(items: list) -> list:
    if not isinstance(items, list):
        return []

    normalized = []

    for item in items:
        if not isinstance(item, dict):
            continue

        degree = str(item.get("degree", "")).strip()
        institution = str(item.get("institution", "")).strip()
        result = str(item.get("result", "")).strip()
        year = str(item.get("year", "")).strip()

        if not degree and not institution and not result and not year:
            continue

        normalized.append(
            {
                "degree": degree or "Not Found",
                "institution": institution or "Not Found",
                "result": result or "Not Found",
                "year": year or "Not Found",
            }
        )

    return normalized


# ── Public API ────────────────────────────────────────────────────────────────

def parse_cv(pdf_path: Path) -> dict:
    """
    Send the PDF directly to Gemini for analysis.
    Returns structured CV data as a Python dictionary.
    """

    raw_text = _call_gemini_with_retry(pdf_path)
    parsed = _extract_json(raw_text)

    parsed["source_file"] = pdf_path.name
    parsed.setdefault("candidate_name", "Not Found")
    parsed.setdefault("email", "Not Found")
    parsed.setdefault("educational_qualifications", [])
    parsed.setdefault("skills", [])
    parsed.setdefault("experiences", [])
    parsed.setdefault("personal_projects", [])
    parsed.setdefault("achievements", [])
    parsed.setdefault("certificates", [])
    parsed.setdefault("trainings", [])
    parsed.setdefault("publications", [])

    valid_experiences, moved_projects = _filter_experiences_and_extract_projects(
        parsed.get("experiences", [])
    )

    parsed["candidate_name"] = str(parsed.get("candidate_name", "")).strip() or "Not Found"
    parsed["email"] = str(parsed.get("email", "")).strip() or "Not Found"
    parsed["educational_qualifications"] = _normalize_education(
        parsed.get("educational_qualifications", [])
    )
    parsed["skills"] = _filter_skills(parsed.get("skills", []))
    parsed["experiences"] = valid_experiences
    parsed["personal_projects"] = _filter_personal_projects(
        parsed.get("personal_projects", []) + moved_projects
    )
    parsed["achievements"] = _clean_string_list(parsed.get("achievements", []))
    parsed["certificates"] = _clean_string_list(parsed.get("certificates", []))
    parsed["trainings"] = _clean_string_list(parsed.get("trainings", []))
    parsed["publications"] = _clean_string_list(parsed.get("publications", []))

    return parsed