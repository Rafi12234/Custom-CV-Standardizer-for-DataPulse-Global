# app/main.py
# Main controller — orchestrates PDF analysis and output generation.
# No text extraction. PDF goes directly to Gemini.

import json
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

from app import config
from app.file_helper import ensure_output_folder, get_pdf_files
from app.gemini_parser import parse_cv
from app.pdf_generator import generate_individual_pdf

# Seconds to wait between successive Gemini calls (free-tier protection)
_INTER_FILE_DELAY = 35


def _log(message: str, callback: Optional[Callable[[str], None]]) -> None:
    print(message)
    if callback:
        callback(message)


def process_folder(
    folder_path: str,
    status_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Process all PDF CVs inside folder_path.

    For each PDF:
      1. Upload PDF directly to Gemini File API.
      2. Gemini analyzes the PDF and returns structured JSON.
      3. Generate one individual standardized PDF for that candidate.

    After all files:
      4. Save all results into output/all_cvs.json.

    Returns
    -------
    dict
        Summary: total_files, success_count, failed_count,
                 failed_files, json_path, output_pdfs.
    """
    summary = {
        "total_files":   0,
        "success_count": 0,
        "failed_count":  0,
        "failed_files":  [],
        "json_path":     "",
        "output_pdfs":   [],
    }

    # ── Validate API key ──────────────────────────────────────────────────────
    if not config.GEMINI_API_KEY:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set in your .env file.\n"
            "Please add your Gemini API key and restart the app."
        )

    # ── Ensure output folder ──────────────────────────────────────────────────
    ensure_output_folder()
    _log("Output folder ready.", status_callback)

    # ── Discover PDF files ────────────────────────────────────────────────────
    try:
        pdf_files = get_pdf_files(folder_path)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise ValueError(str(exc)) from exc

    summary["total_files"] = len(pdf_files)
    _log(
        f"Found {len(pdf_files)} PDF file(s). Starting processing...\n",
        status_callback,
    )

    # ── Process each PDF ──────────────────────────────────────────────────────
    successful_cvs: list[dict] = []

    for idx, pdf_path in enumerate(pdf_files, start=1):
        _log(
            f"[{idx}/{len(pdf_files)}] Processing: {pdf_path.name}",
            status_callback,
        )

        try:
            # Send PDF directly to Gemini — no text extraction
            _log("  → Uploading PDF to Gemini for analysis...", status_callback)
            cv_data = parse_cv(pdf_path)

            candidate_name = cv_data.get("candidate_name", "Unknown")
            _log(
                f"  → Gemini analyzed CV for: {candidate_name}",
                status_callback,
            )

            # Generate individual PDF for this candidate
            _log("  → Generating standardized PDF...", status_callback)
            pdf_out = generate_individual_pdf(cv_data)
            _log(f"  → PDF saved: {pdf_out.name}", status_callback)

            successful_cvs.append(cv_data)
            summary["success_count"] += 1
            summary["output_pdfs"].append(str(pdf_out))
            _log(f"  ✔ Done: {pdf_path.name}\n", status_callback)

        except Exception:
            error_detail = traceback.format_exc()
            summary["failed_count"] += 1
            summary["failed_files"].append(pdf_path.name)
            _log(
                f"  ✘ FAILED: {pdf_path.name}\n"
                f"    Reason: {error_detail.strip().splitlines()[-1]}\n",
                status_callback,
            )
            continue

        finally:
            # Wait between files to respect free-tier rate limits
            if idx < len(pdf_files):
                _log(
                    f"  ⏱ Waiting {_INTER_FILE_DELAY}s before next file "
                    f"(free-tier rate limit protection)...",
                    status_callback,
                )
                time.sleep(_INTER_FILE_DELAY)

    # ── Save combined JSON ────────────────────────────────────────────────────
    if successful_cvs:
        _log("Saving all_cvs.json...", status_callback)
        try:
            with open(config.OUTPUT_JSON_PATH, "w", encoding="utf-8") as fh:
                json.dump(successful_cvs, fh, ensure_ascii=False, indent=2)
            summary["json_path"] = str(config.OUTPUT_JSON_PATH)
            _log(f"  ✔ JSON saved: {config.OUTPUT_JSON_PATH}", status_callback)
        except Exception as exc:
            _log(f"  ✘ Failed to save JSON: {exc}", status_callback)
    else:
        _log(
            "No CVs were processed successfully. JSON not generated.",
            status_callback,
        )

    # ── Final summary ─────────────────────────────────────────────────────────
    _log(
        f"\n{'=' * 50}\n"
        f"Processing complete.\n"
        f"  Total files : {summary['total_files']}\n"
        f"  Succeeded   : {summary['success_count']}\n"
        f"  Failed      : {summary['failed_count']}\n"
        + (
            f"  Failed files: {', '.join(summary['failed_files'])}\n"
            if summary["failed_files"] else ""
        )
        + f"{'=' * 50}",
        status_callback,
    )

    return summary