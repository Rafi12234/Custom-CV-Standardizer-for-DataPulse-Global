# app/pdf_generator.py
# Custom designed standardized CV PDF generator.
# Uses a two-pass build: left column and right column are built separately,
# then merged page-by-page so left content always stays left and right
# content always stays right — even across multiple pages.
# Extra sections (Achievements, Certificates, Trainings, Publications) are
# distributed between left and right columns automatically to balance height.

from pathlib import Path
from typing import Any
import tempfile
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    NextPageTemplate,
)
from reportlab.platypus.flowables import HRFlowable, Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas as pdfgen_canvas

import fitz  # PyMuPDF

from app.config import OUTPUT_FOLDER, BASE_DIR

# ── Asset paths ───────────────────────────────────────────────────────────────
ASSETS_DIR      = BASE_DIR / "assets"
FONTS_DIR       = ASSETS_DIR / "fonts"
IMG_DIR         = ASSETS_DIR / "img"

FONT_TTF_PATH   = FONTS_DIR / "GeneralSans-Medium.ttf"
FONT_OTF_PATH   = FONTS_DIR / "GeneralSans-Medium.otf"
IMG_HEADER_DECO = IMG_DIR   / "CV format-03.png"
IMG_BRAND_LOGO  = IMG_DIR   / "CV format-04.png"

# ── Brand colours ─────────────────────────────────────────────────────────────
ORANGE      = colors.HexColor("#e9511d")
BLACK       = colors.HexColor("#1a1a1a")
DARK_GRAY   = colors.HexColor("#333333")
MID_GRAY    = colors.HexColor("#666666")
RULE_GRAY   = colors.HexColor("#cccccc")
EXP_DETAIL  = colors.HexColor("#2a2a2a")

# Skill tag colours — light grey background like the reference image
SKILL_TAG_BG     = colors.HexColor("#eeeeee")   # light grey fill
SKILL_TAG_BORDER = colors.HexColor("#cccccc")   # subtle border
SKILL_TAG_TEXT   = colors.HexColor("#222222")   # near-black text

# ── Page geometry ─────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4

MARGIN_LEFT   = 14 * mm
MARGIN_RIGHT  = 14 * mm
MARGIN_TOP    = 12 * mm
MARGIN_BOTTOM = 30 * mm

HEADER_HEIGHT = 38 * mm
DIVIDER_Y_P1  = PAGE_H - MARGIN_TOP - HEADER_HEIGHT
DIVIDER_Y_PN  = PAGE_H - MARGIN_TOP - 6 * mm

LEFT_COL_W  = 62 * mm
GUTTER      =  6 * mm
RIGHT_COL_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT - LEFT_COL_W - GUTTER
VERT_LINE_X = MARGIN_LEFT + LEFT_COL_W + GUTTER / 2

LOGO_W = 38 * mm
LOGO_H = 22 * mm
LOGO_X = MARGIN_LEFT
LOGO_Y =  6 * mm

DECO_W = 34 * mm
DECO_H = 34 * mm
DECO_X = PAGE_W - MARGIN_RIGHT - DECO_W
DECO_Y = PAGE_H - MARGIN_TOP - DECO_H

SECTION_HEAD_H    = 8 * mm
SKILLS_BULLET_MAX = 25

LINE_H = 3.5 * mm


# Skill tag geometry
TAG_H          = 6.5 * mm    # height of each tag box
TAG_RADIUS     = 3.0 * mm    # corner radius for rounded rectangle
TAG_PAD_X      = 3.5 * mm   # horizontal padding inside tag
TAG_PAD_Y      = 1.5 * mm   # vertical padding inside tag
TAG_FONT_SIZE  = 7.5         # pt
TAG_LINE_GAP   = 2.0 * mm   # vertical gap between tag rows
TAG_H_GAP      = 1.5 * mm   # horizontal gap between tags in a row


# ── Font registration ─────────────────────────────────────────────────────────

_GENERAL_SANS_OK = False


def _register_fonts() -> None:
    global _GENERAL_SANS_OK
    if FONT_TTF_PATH.exists():
        try:
            pdfmetrics.registerFont(
                TTFont("GeneralSans-Medium", str(FONT_TTF_PATH))
            )
            _GENERAL_SANS_OK = True
            print("[pdf_generator] GeneralSans-Medium (TTF) registered.")
        except Exception as exc:
            print(f"[pdf_generator] Warning – TTF load failed: {exc}")
    elif FONT_OTF_PATH.exists():
        print(
            "[pdf_generator] WARNING: Only OTF found — run "
            "python convert_font.py. Using Helvetica-Bold fallback."
        )
    else:
        print("[pdf_generator] Warning – Font not found. Using Helvetica-Bold.")


_register_fonts()


def _heading_font() -> str:
    return "GeneralSans-Medium" if _GENERAL_SANS_OK else "Helvetica-Bold"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _val(value: Any, fallback: str = "Not Found") -> str:
    s = str(value).strip() if value else ""
    return s if s and s.lower() != "not found" else fallback


def _clean_list(raw: Any) -> list:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        v = str(item).strip() if item else ""
        if v and v.lower() != "not found":
            result.append(v)
    return result


# ── Paragraph styles ──────────────────────────────────────────────────────────

def _make_styles() -> dict:
    s = {}
    s["body"] = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=8.5,
        textColor=DARK_GRAY, leading=13, spaceAfter=1 * mm,
    )
    s["body_bold"] = ParagraphStyle(
        "body_bold", fontName="Helvetica-Bold", fontSize=9.5,
        textColor=BLACK, leading=13,
        spaceBefore=2.5 * mm, spaceAfter=0.8 * mm,
    )
    s["skill_bullet"] = ParagraphStyle(
        "skill_bullet", fontName="Helvetica-Bold", fontSize=9,
        textColor=DARK_GRAY, leading=15, spaceAfter=2 * mm,
    )
    s["exp_detail"] = ParagraphStyle(
        "exp_detail", fontName="Helvetica", fontSize=8.5,
        textColor=EXP_DETAIL, leading=13,
        spaceAfter=0.8 * mm, leftIndent=3 * mm,
    )
    s["extra_item"] = ParagraphStyle(
        "extra_item", fontName="Helvetica", fontSize=8.5,
        textColor=DARK_GRAY, leading=13,
        spaceAfter=1.5 * mm, leftIndent=2 * mm,
    )
    return s


# ── Section heading flowable ──────────────────────────────────────────────────

class SectionHeadingSpacer(Flowable):
    def __init__(self, label: str):
        super().__init__()
        self.label  = label
        self.width  = 0
        self.height = SECTION_HEAD_H

    def draw(self):
        self.canv.saveState()
        self.canv.setFont(_heading_font(), 12)
        self.canv.setFillColor(ORANGE)
        self.canv.drawString(0, 2 * mm, self.label)
        self.canv.restoreState()

    def wrap(self, available_width, available_height):
        self.width = available_width
        return available_width, self.height


# ── Skill tag flowable (rounded pill per skill) ───────────────────────────────

class SkillTagsFlowable(Flowable):
    """
    Renders skill names as individual rounded-rectangle tags that wrap
    across rows to fit within the left column width.

    Each tag width is determined by its text content so tags never overflow.
    The available_width is strictly respected — no tag or row ever exceeds it.
    """

    def __init__(self, skills: list, available_width: float):
        super().__init__()
        self.skills          = skills
        self.available_width = available_width
        self._rows: list     = []
        self.width           = 0
        self.height          = 0

    @staticmethod
    def _tag_width(skill: str) -> float:
        """
        Calculate tag width from character count using a fixed-width estimate.
        Helvetica at 7.5pt ≈ 4.2pt per character average.
        We use a conservative estimate to prevent overflow.
        """
        char_w = 4.2   # pt per character at 7.5pt Helvetica
        text_w = len(skill) * char_w
        return text_w + 2 * TAG_PAD_X

    def _compute_rows(self) -> list:
        """
        Pack skills into rows. Each row total width must not exceed
        available_width. Uses conservative char-width estimation.
        """
        # Hard cap: no single tag can be wider than available_width
        max_tag_w = self.available_width

        rows    = []
        cur_row = []
        cur_w   = 0.0

        for skill in self.skills:
            tw  = min(self._tag_width(skill), max_tag_w)
            gap = TAG_H_GAP if cur_row else 0.0

            if cur_row and cur_w + gap + tw > self.available_width:
                rows.append(cur_row)
                cur_row = [(skill, tw)]
                cur_w   = tw
            else:
                cur_row.append((skill, tw))
                cur_w += gap + tw

        if cur_row:
            rows.append(cur_row)

        return rows

    def wrap(self, available_width, available_height):
        # Strictly use the frame's available width — never exceed it
        self.available_width = available_width
        self.width           = available_width
        self._rows           = self._compute_rows()

        n_rows      = len(self._rows)
        self.height = (
            n_rows * TAG_H
            + max(0, n_rows - 1) * TAG_LINE_GAP
        )
        return available_width, self.height

    def draw(self):
        canv = self.canv

        # Recompute with final available_width for accurate placement
        self._rows = self._compute_rows()

        canv.saveState()

        # ReportLab y=0 is bottom of flowable, y=self.height is top
        y = self.height

        for row in self._rows:
            y -= TAG_H
            x  = 0.0

            for skill, tw in row:
                # Clamp tag width to available space remaining in row
                tw = min(tw, self.available_width - x)
                if tw <= 0:
                    break

                # Rounded rectangle background
                canv.setFillColor(SKILL_TAG_BG)
                canv.setStrokeColor(SKILL_TAG_BORDER)
                canv.setLineWidth(0.5)
                canv.roundRect(
                    x, y,
                    tw, TAG_H,
                    TAG_RADIUS,
                    stroke=1, fill=1,
                )

                # Skill text — clip to tag width
                text_y = y + (TAG_H - TAG_FONT_SIZE * 0.75) / 2
                canv.setFillColor(SKILL_TAG_TEXT)
                canv.setFont("Helvetica", TAG_FONT_SIZE)

                # Save clip region so text never bleeds outside the tag
                canv.saveState()
                p = canv.beginPath()
                p.rect(x, y, tw, TAG_H)
                canv.clipPath(p, stroke=0, fill=0)
                canv.drawString(x + TAG_PAD_X, text_y, skill)
                canv.restoreState()

                x += tw + TAG_H_GAP

            y -= TAG_LINE_GAP

        canv.restoreState()

# ── Height estimator ──────────────────────────────────────────────────────────

def _estimate_text_lines(text: str, col_width_mm: float, font_size: float = 8.5) -> int:
    if not text:
        return 1
    chars_per_line = max(1, int(col_width_mm * 2.2 / font_size))
    words    = text.split()
    lines    = 1
    cur_len  = 0
    for word in words:
        wl = len(word) + 1
        if cur_len + wl > chars_per_line:
            lines  += 1
            cur_len = wl
        else:
            cur_len += wl
    return lines


def _estimate_skill_tags_height(skills: list, col_width_mm: float) -> float:
    """
    Estimate height of the skill-tag layout in mm.
    Approximates tag widths using character count * avg char width.
    """
    AVG_CHAR_W_MM = 1.8   # approx mm per character at 7.5pt Helvetica
    TAG_PAD_MM    = TAG_PAD_X / mm * 2
    col_w         = col_width_mm

    rows    = 0
    cur_w   = 0.0
    started = False

    for skill in skills:
        tw  = len(skill) * AVG_CHAR_W_MM + TAG_PAD_MM
        gap = TAG_H_GAP / mm if started else 0.0
        if started and cur_w + gap + tw > col_w:
            rows  += 1
            cur_w  = tw
        else:
            cur_w += gap + tw
            started = True

    if started:
        rows += 1

    return rows * (TAG_H / mm) + max(0, rows - 1) * (TAG_LINE_GAP / mm)


def _estimate_skills_height(skills: list, col_width_mm: float) -> float:
    total = SECTION_HEAD_H / mm

    if not skills:
        return total + LINE_H / mm

    if len(skills) <= SKILLS_BULLET_MAX:
        for skill in skills:
            n = _estimate_text_lines(skill, col_width_mm)
            total += n * (15 / mm) + 2
    else:
        total += _estimate_skill_tags_height(skills, col_width_mm)

    return total


def _estimate_section_height(title: str, items: list, col_width_mm: float) -> float:
    total = SECTION_HEAD_H / mm + 3 + 1 + 1
    for item in items:
        n = _estimate_text_lines(item, col_width_mm)
        total += n * LINE_H / mm + 1.5
    return total


def _estimate_education_height(qualifications: list, col_width_mm: float) -> float:
    total = SECTION_HEAD_H / mm
    for edu in qualifications:
        total += LINE_H / mm + 0.8
        for field in ["institution", "result", "year"]:
            v = _val(edu.get(field, ""))
            if v != "Not Found":
                n = _estimate_text_lines(v, col_width_mm)
                total += n * LINE_H / mm + 1
        total += 2 + 2
    return total


def _estimate_experience_height(experiences: list, col_width_mm: float) -> float:
    total = 4 + 1 + SECTION_HEAD_H / mm
    for exp in experiences:
        total += LINE_H / mm + 0.8
        dur = _val(exp.get("duration", ""))
        if dur != "Not Found":
            total += LINE_H / mm + 1
        details = _val(exp.get("details", ""))
        if details and details != "Not Found":
            total += 1
            for line in details.replace("\r\n", "\n").split("\n"):
                cleaned = line.strip().lstrip("-•*·▪▸►◆○●‣⁃∙➤✓✔ ").strip()
                if cleaned:
                    n = _estimate_text_lines(cleaned, col_width_mm)
                    total += n * LINE_H / mm + 0.8
        total += 2 + 1
    return total


# ── Smart section balancer ────────────────────────────────────────────────────

def _balance_extra_sections(
    extra_sections: list,
    base_left_h: float,
    base_right_h: float,
    left_col_w_mm: float,
    right_col_w_mm: float,
) -> tuple:
    left_h  = base_left_h
    right_h = base_right_h

    left_extras  = []
    right_extras = []

    sized = []
    for title, items in extra_sections:
        if not items:
            continue
        h_l = _estimate_section_height(title, items, left_col_w_mm)
        h_r = _estimate_section_height(title, items, right_col_w_mm)
        sized.append((title, items, h_l, h_r))

    sized.sort(key=lambda x: max(x[2], x[3]), reverse=True)

    for title, items, h_l, h_r in sized:
        diff_if_left  = abs((left_h  + h_l) - right_h)
        diff_if_right = abs(left_h  - (right_h + h_r))

        if diff_if_left <= diff_if_right:
            left_extras.append((title, items))
            left_h += h_l
            side    = "LEFT"
        else:
            right_extras.append((title, items))
            right_h += h_r
            side     = "RIGHT"

        print(
            f"  [balance] '{title}' → {side} "
            f"(left≈{left_h:.0f}mm, right≈{right_h:.0f}mm)"
        )

    return left_extras, right_extras


# ── Extra section flowables ───────────────────────────────────────────────────

def _build_extra_section_flowables(sections: list, styles: dict) -> list:
    flowables = []
    for title, items in sections:
        clean = _clean_list(items)
        if not clean:
            continue
        flowables.append(Spacer(1, 3 * mm))
        flowables.append(HRFlowable(
            width="100%", thickness=0.4, color=RULE_GRAY, spaceAfter=1 * mm,
        ))
        flowables.append(SectionHeadingSpacer(title))
        for item in clean:
            cleaned = item.strip().lstrip("-•*·▪▸►◆○● ").strip()
            if cleaned:
                flowables.append(
                    Paragraph(f"• {_esc(cleaned)}", styles["extra_item"])
                )
    return flowables


# ── Column content builders ───────────────────────────────────────────────────

def _build_left_content(cv: dict, left_extras: list, styles: dict) -> list:
    flowables = []

    # Skills heading
    flowables.append(SectionHeadingSpacer("Skills"))

    clean_skills = _clean_list(cv.get("skills", []))

    if not clean_skills:
        flowables.append(Paragraph("Not Found", styles["body"]))

    elif len(clean_skills) <= SKILLS_BULLET_MAX:
        # Bullet list for ≤ 25 skills
        for skill in clean_skills:
            flowables.append(
                Paragraph(f"• {_esc(skill)}", styles["skill_bullet"])
            )

    else:
        # ── Rounded tag layout for > 25 skills ───────────────────────────────
        flowables.append(Spacer(1, 1 * mm))
        # We pass LEFT_COL_W minus padding as available width
        avail_w = LEFT_COL_W - 2 * mm   # matches frame rightPadding
        flowables.append(SkillTagsFlowable(clean_skills, avail_w))

    # Balanced extra sections for left column
    flowables.extend(_build_extra_section_flowables(left_extras, styles))

    return flowables


def _build_right_content(cv: dict, right_extras: list, styles: dict) -> list:
    flowables = []

    # Educational Qualifications
    flowables.append(SectionHeadingSpacer("Educational Qualifications"))
    qualifications = cv.get("educational_qualifications", [])

    if not qualifications:
        flowables.append(Paragraph("Not Found", styles["body"]))
    else:
        for idx, edu in enumerate(qualifications):
            degree      = _val(edu.get("degree",      ""))
            institution = _val(edu.get("institution", ""))
            result      = _val(edu.get("result",      ""))
            year        = _val(edu.get("year",        ""))

            flowables.append(Paragraph(_esc(degree), styles["body_bold"]))
            if institution != "Not Found":
                flowables.append(Paragraph(
                    f'<font color="#888888">Institution:&nbsp;&nbsp;&nbsp;&nbsp;</font>'
                    f'{_esc(institution)}', styles["body"],
                ))
            if result != "Not Found":
                flowables.append(Paragraph(
                    f'<font color="#888888">Result / Grade:&nbsp;</font>'
                    f'{_esc(result)}', styles["body"],
                ))
            if year != "Not Found":
                flowables.append(Paragraph(
                    f'<font color="#888888">Year:&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
                    f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</font>'
                    f'{_esc(year)}', styles["body"],
                ))
            if idx < len(qualifications) - 1:
                flowables.append(Spacer(1, 2 * mm))
                flowables.append(HRFlowable(
                    width="100%", thickness=0.4,
                    color=RULE_GRAY, spaceAfter=2 * mm,
                ))

    # Work Experience
    flowables.append(Spacer(1, 4 * mm))
    flowables.append(HRFlowable(
        width="100%", thickness=0.6, color=RULE_GRAY, spaceAfter=1 * mm,
    ))
    flowables.append(SectionHeadingSpacer("Work Experience"))

    experiences = cv.get("experiences", [])
    if not experiences:
        flowables.append(Paragraph("Not Found", styles["body"]))
    else:
        for idx, exp in enumerate(experiences):
            position = _val(exp.get("position", ""))
            company  = _val(exp.get("company",  ""))
            duration = _val(exp.get("duration", ""))
            details  = _val(exp.get("details",  ""))

            parts = []
            if position != "Not Found":
                parts.append(_esc(position))
            if company != "Not Found":
                parts.append(_esc(company))

            title_text = (
                f'<font color="#aaaaaa"> &nbsp;|&nbsp; </font>'.join(parts)
                if parts else "Not Found"
            )
            flowables.append(Paragraph(title_text, styles["body_bold"]))

            if duration != "Not Found":
                flowables.append(Paragraph(
                    f'<font color="#888888">Duration:&nbsp;</font>{_esc(duration)}',
                    styles["body"],
                ))

            if details and details != "Not Found":
                flowables.append(Spacer(1, 1 * mm))
                for line in details.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                    cleaned = line.strip().lstrip("-•*·▪▸►◆○●‣⁃∙➤✓✔ ").strip()
                    if cleaned:
                        flowables.append(
                            Paragraph(f"• {_esc(cleaned)}", styles["exp_detail"])
                        )

            if idx < len(experiences) - 1:
                flowables.append(Spacer(1, 2 * mm))
                flowables.append(HRFlowable(
                    width="100%", thickness=0.3,
                    color=RULE_GRAY, spaceAfter=1 * mm,
                ))

    # Balanced extra sections for right column
    flowables.extend(_build_extra_section_flowables(right_extras, styles))

    return flowables


# ── Single-column PDF builder ─────────────────────────────────────────────────

def _build_column_pdf(
    flowables: list,
    output_path: str,
    frame_x: float,
    frame_w: float,
    is_left: bool,
) -> int:
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=0, rightMargin=0,
        topMargin=0,  bottomMargin=0,
    )

    def _make_frame(divider_y: float, fid: str) -> Frame:
        h = divider_y - MARGIN_BOTTOM
        return Frame(
            x1=frame_x, y1=MARGIN_BOTTOM,
            width=frame_w, height=h,
            leftPadding=0 if is_left else 3 * mm,
            rightPadding=2 * mm if is_left else 0,
            topPadding=4 * mm, bottomPadding=0,
            id=fid, showBoundary=0,
        )

    p1 = _make_frame(DIVIDER_Y_P1, "p1")
    pn = _make_frame(DIVIDER_Y_PN, "pn")

    doc.addPageTemplates([
        PageTemplate(id="page1", frames=[p1], onPage=lambda c, d: None),
        PageTemplate(id="pageN", frames=[pn], onPage=lambda c, d: None),
    ])

    story = [NextPageTemplate("pageN")] + flowables
    doc.build(story)

    tmp = fitz.open(output_path)
    n   = tmp.page_count
    tmp.close()
    return n


# ── Background / decoration layer ─────────────────────────────────────────────

def _build_background_pdf(output_path: str, n_pages: int, cv: dict) -> None:
    c = pdfgen_canvas.Canvas(output_path, pagesize=A4)

    candidate_name = _val(cv.get("candidate_name", ""), "Unknown Candidate")
    email          = _val(cv.get("email", ""), "")

    for page_num in range(1, n_pages + 1):
        c.saveState()

        if page_num == 1:
            divider_y = DIVIDER_Y_P1

            if IMG_HEADER_DECO.exists():
                try:
                    c.drawImage(
                        str(IMG_HEADER_DECO),
                        x=DECO_X, y=DECO_Y,
                        width=DECO_W, height=DECO_H,
                        preserveAspectRatio=True, mask="auto",
                    )
                except Exception as e:
                    print(f"[pdf_generator] Deco image error: {e}")

            name_upper  = candidate_name.upper()
            name_x      = MARGIN_LEFT
            name_y_top  = PAGE_H - MARGIN_TOP - 8 * mm
            max_name_w  = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT - DECO_W - 6 * mm
            font_size   = 28
            line_height = font_size * 1.10

            c.setFont("Times-Bold", font_size)
            c.setFillColor(ORANGE)

            words    = name_upper.split()
            lines    = []
            cur_line = ""
            for word in words:
                test = (cur_line + " " + word).strip()
                if c.stringWidth(test, "Times-Bold", font_size) <= max_name_w:
                    cur_line = test
                else:
                    if cur_line:
                        lines.append(cur_line)
                    cur_line = word
            if cur_line:
                lines.append(cur_line)

            for i, line in enumerate(lines):
                c.drawString(name_x, name_y_top - i * line_height, line)

            email_y = name_y_top - len(lines) * line_height - 1.5 * mm
            c.setFont("Times-Roman", 9.5)
            c.setFillColor(DARK_GRAY)
            if email and email != "Not Found":
                c.drawString(name_x, email_y, f"Email: {email}")
        else:
            divider_y = DIVIDER_Y_PN

        # Orange H-line
        c.setStrokeColor(ORANGE)
        c.setLineWidth(1.2)
        c.line(MARGIN_LEFT, divider_y, PAGE_W - MARGIN_RIGHT, divider_y)

        # Orange V-line
        c.setStrokeColor(ORANGE)
        c.setLineWidth(1.0)
        c.line(VERT_LINE_X, divider_y, VERT_LINE_X, MARGIN_BOTTOM)

        # Brand logo
        if IMG_BRAND_LOGO.exists():
            try:
                c.drawImage(
                    str(IMG_BRAND_LOGO),
                    x=LOGO_X, y=LOGO_Y,
                    width=LOGO_W, height=LOGO_H,
                    preserveAspectRatio=True, mask="auto",
                )
            except Exception as e:
                print(f"[pdf_generator] Logo error: {e}")

        c.restoreState()
        c.showPage()

    c.save()


# ── PDF merger ────────────────────────────────────────────────────────────────

def _merge_pdfs(
    bg_path: str,
    left_path: str,
    right_path: str,
    output_path: str,
    n_pages: int,
) -> None:
    bg_doc    = fitz.open(bg_path)
    left_doc  = fitz.open(left_path)
    right_doc = fitz.open(right_path)
    out_doc   = fitz.open()

    for i in range(n_pages):
        new_page = out_doc.new_page(width=PAGE_W, height=PAGE_H)
        new_page.show_pdf_page(new_page.rect, bg_doc, i)
        if i < left_doc.page_count:
            new_page.show_pdf_page(new_page.rect, left_doc, i)
        if i < right_doc.page_count:
            new_page.show_pdf_page(new_page.rect, right_doc, i)

    out_doc.save(output_path)
    out_doc.close()
    bg_doc.close()
    left_doc.close()
    right_doc.close()


# ── Public entry point ────────────────────────────────────────────────────────

def generate_individual_pdf(cv: dict) -> Path:
    """
    Generate one custom-designed balanced standardized PDF.
    """
    from app.file_helper import sanitize_filename

    candidate_name = _val(cv.get("candidate_name", ""), "Unknown Candidate")
    safe_name      = sanitize_filename(candidate_name)
    final_path     = str(OUTPUT_FOLDER / f"{safe_name}_CV.pdf")

    styles = _make_styles()

    # Optional sections
    optional_sections = []
    for title, key in [
        ("Achievements",  "achievements"),
        ("Certificates",  "certificates"),
        ("Trainings",     "trainings"),
        ("Publications",  "publications"),
    ]:
        items = _clean_list(cv.get(key, []))
        if items:
            optional_sections.append((title, items))

    # Estimate base heights
    left_col_w_mm  = (LEFT_COL_W  - 2 * mm) / mm
    right_col_w_mm = (RIGHT_COL_W - 3 * mm) / mm

    base_left_h = _estimate_skills_height(
        _clean_list(cv.get("skills", [])), left_col_w_mm,
    )
    base_right_h = (
        _estimate_education_height(
            cv.get("educational_qualifications", []), right_col_w_mm,
        )
        + _estimate_experience_height(
            cv.get("experiences", []), right_col_w_mm,
        )
    )

    print(
        f"  [balance] Base — "
        f"left≈{base_left_h:.0f}mm  right≈{base_right_h:.0f}mm"
    )

    left_extras, right_extras = _balance_extra_sections(
        optional_sections, base_left_h, base_right_h,
        left_col_w_mm, right_col_w_mm,
    )

    left_flowables  = _build_left_content(cv, left_extras, styles)
    right_flowables = _build_right_content(cv, right_extras, styles)

    with tempfile.TemporaryDirectory() as tmp_dir:
        bg_path    = os.path.join(tmp_dir, "bg.pdf")
        left_path  = os.path.join(tmp_dir, "left.pdf")
        right_path = os.path.join(tmp_dir, "right.pdf")

        left_pages = _build_column_pdf(
            left_flowables, left_path,
            frame_x=MARGIN_LEFT, frame_w=LEFT_COL_W, is_left=True,
        )
        right_pages = _build_column_pdf(
            right_flowables, right_path,
            frame_x=MARGIN_LEFT + LEFT_COL_W + GUTTER,
            frame_w=RIGHT_COL_W, is_left=False,
        )

        n_pages = max(left_pages, right_pages)
        _build_background_pdf(bg_path, n_pages, cv)
        _merge_pdfs(bg_path, left_path, right_path, final_path, n_pages)

    return Path(final_path)