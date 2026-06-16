# app/text_cleaner.py
# Cleans and normalises raw text extracted from PDFs before sending to Gemini.

import re

from app.config import MAX_CV_TEXT_CHARS


def clean_text(raw_text: str) -> str:
    """
    Clean and normalise raw CV text extracted from a PDF.

    Steps applied (in order):
    1.  Normalise Windows/Mac line endings to Unix \\n.
    2.  Replace common Unicode bullet / dash variants with plain ASCII.
    3.  Remove non-printable / invisible control characters (except \\n and \\t).
    4.  Collapse runs of blank lines (3+ → 2).
    5.  Strip trailing whitespace from every line.
    6.  Collapse runs of spaces/tabs on a single line into one space.
    7.  Truncate to MAX_CV_TEXT_CHARS to stay inside API limits.

    Parameters
    ----------
    raw_text : str
        The unprocessed text returned by pdf_extractor.

    Returns
    -------
    str
        The cleaned, normalised text ready for the Gemini prompt.
    """
    text = raw_text

    # 1. Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Normalise bullet characters → plain hyphen-space
    bullet_pattern = re.compile(r"[•·▪▸►◆◇○●‣⁃∙➤➢➣➡→✓✔✗✘◦‐‑‒–—]")
    text = bullet_pattern.sub("- ", text)

    # 3. Remove non-printable control characters (keep \n and \t)
    text = re.sub(r"[^\S\n\t ]+", " ", text)          # exotic whitespace → space
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # 4. Collapse 3+ consecutive blank lines → 2 blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 5 & 6. Per-line cleanup
    cleaned_lines  = []
    for line in text.split("\n"):
        line = line.rstrip()                            # strip trailing whitespace
        line = re.sub(r"[ \t]{2,}", " ", line)         # collapse inline spaces/tabs
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines).strip()

    # 7. Truncate to avoid  exceeding API token limits
    if len(text) > MAX_CV_TEXT_CHARS:
        text = text[:MAX_CV_TEXT_CHARS]
        # Try not to cut mid-word
        last_newline = text.rfind("\n")
        if last_newline > MAX_CV_TEXT_CHARS * 0.9:
            text = text[:last_newline]
        text = text.rstrip() + "\n\n[TEXT TRUNCATED]"

    return text