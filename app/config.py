# app/config.py
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

_env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=_env_path)

# ── Output paths ──────────────────────────────────────────────────────────────
OUTPUT_FOLDER    = BASE_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_FOLDER / "all_cvs.json"

# ── Gemini settings ───────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

# ── Retry settings ────────────────────────────────────────────────────────────
RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "5"))
RETRY_INITIAL_WAIT = int(os.getenv("RETRY_INITIAL_WAIT", "15"))