# app/file_helper.py
import os
import platform
import subprocess
from pathlib import Path
from typing import List

from app.config import OUTPUT_FOLDER


def get_pdf_files(folder_path: str) -> List[Path]:
    """
    Return all .pdf files inside folder_path sorted by file name.
    """
    folder = Path(folder_path)

    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    if not folder.is_dir():
        raise NotADirectoryError(f"Path is not a folder: {folder_path}")

    pdf_files = sorted(
        [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"],
        key=lambda p: p.name.lower(),
    )

    if not pdf_files:
        raise ValueError(f"No PDF files found in folder: {folder_path}")

    return pdf_files


def ensure_output_folder() -> Path:
    """Create the output folder if it does not already exist."""
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    return OUTPUT_FOLDER


def open_output_folder() -> None:
    """Open the output folder in the system default file explorer."""
    ensure_output_folder()
    folder = str(OUTPUT_FOLDER)
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(folder)
        elif system == "Darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception as exc:
        print(f"[file_helper] Could not open output folder: {exc}")


def sanitize_filename(name: str) -> str:
    """
    Convert a candidate name into a safe filename string.
    Example: 'Md. Mashiur Rahman' -> 'Md_Mashiur_Rahman'
    """
    import re
    # Replace any character that is not alphanumeric, space, dot, or hyphen
    safe = re.sub(r"[^\w\s\-.]", "", name)
    # Replace spaces with underscores
    safe = re.sub(r"\s+", "_", safe.strip())
    return safe if safe else "Unknown_Candidate"