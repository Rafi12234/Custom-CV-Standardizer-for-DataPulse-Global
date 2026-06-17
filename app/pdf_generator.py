# app/pdf_generator.py
# Custom designed standardized CV PDF generator.
#
# Fixed layout:
#   LEFT  = Skills
#   RIGHT = Educational Qualifications + Work Experience
#
# Movable balanced sections:
#   Personal Projects, Achievements, Certificates, Trainings, Publications
#
# Logic:
#   1. Build fixed left and fixed right sections first.
#   2. Collect all remaining/movable sections.
#   3. Try every possible left/right combination of movable sections.
#   4. Estimate visual balance for each combination.
#   5. Apply the combination with the best balance.
#   6. Generate final PDF using background + left column + right column merge.

from pathlib import Path
from typing import Any
import tempfile
import os
import itertools
import math

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

ASSETS_DIR = BASE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
IMG_DIR = ASSETS_DIR / "img"

FONT_TTF_PATH = FONTS_DIR / "GeneralSans-Medium.ttf"
FONT_OTF_PATH = FONTS_DIR / "GeneralSans-Medium.otf"
IMG_HEADER_DECO = IMG_DIR / "CV format-03.png"
IMG_BRAND_LOGO = IMG_DIR / "CV format-04.png"


# ── Brand colours ─────────────────────────────────────────────────────────────

ORANGE = colors.HexColor("#e9511d")
BLACK = colors.HexColor("#1a1a1a")
DARK_GRAY = colors.HexColor("#333333")
RULE_GRAY = colors.HexColor("#cccccc")
EXP_DETAIL = colors.HexColor("#2a2a2a")

SKILL_TAG_BG = colors.HexColor("#eeeeee")
SKILL_TAG_BORDER = colors.HexColor("#cccccc")
SKILL_TAG_TEXT = colors.HexColor("#222222")


# ── Page geometry ─────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = A4

MARGIN_LEFT = 14 * mm
MARGIN_RIGHT = 14 * mm
MARGIN_TOP = 12 * mm
MARGIN_BOTTOM = 30 * mm

HEADER_HEIGHT = 38 * mm

DIVIDER_Y_P1 = PAGE_H - MARGIN_TOP - HEADER_HEIGHT
DIVIDER_Y_PN = PAGE_H - MARGIN_TOP - 6 * mm

LEFT_COL_W = 62 * mm
GUTTER = 6 * mm
RIGHT_COL_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT - LEFT_COL_W - GUTTER

VERT_LINE_X = MARGIN_LEFT + LEFT_COL_W + GUTTER / 2

LOGO_W = 38 * mm
LOGO_H = 22 * mm
LOGO_X = MARGIN_LEFT
LOGO_Y = 6 * mm

DECO_W = 34 * mm
DECO_H = 34 * mm
DECO_X = PAGE_W - MARGIN_RIGHT - DECO_W
DECO_Y = PAGE_H - MARGIN_TOP - DECO_H

SECTION_HEAD_H = 8 * mm

TAG_H = 6.5 * mm
TAG_RADIUS = 3.0 * mm
TAG_PAD_X = 3.5 * mm
TAG_FONT_SIZE = 7.5
TAG_LINE_GAP = 2.0 * mm
TAG_H_GAP = 1.5 * mm


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
    value = str(value).strip() if value else ""
    return value if value and value.lower() != "not found" else fallback


def _clean_list(raw: Any) -> list:
    if not isinstance(raw, list):
        return []

    result = []

    for item in raw:
        value = str(item).strip() if item else ""

        if value and value.lower() != "not found":
            result.append(value)

    return result


def _shorten_text(text: str, max_words: int = 45) -> str:
    text = str(text).strip()

    if not text:
        return ""

    words = text.split()

    if len(words) <= max_words:
        return text

    return " ".join(words[:max_words]).rstrip(".,;") + "."


def _clean_project_items(projects: Any) -> list:
    """
    Convert personal_projects dicts into readable strings for the PDF.
    Expected project object:
    {
      "project_name": "",
      "tech_stack": "",
      "summary": ""
    }
    """

    if not isinstance(projects, list):
        return []

    result = []

    for project in projects:
        if not isinstance(project, dict):
            continue

        name = _val(project.get("project_name", ""), "")
        tech_stack = _val(project.get("tech_stack", ""), "")
        summary = _val(project.get("summary", ""), "")

        if not name and not summary:
            continue

        parts = []

        if name:
            parts.append(name)

        if tech_stack:
            parts.append(f"Tech Stack: {tech_stack}")

        if summary:
            parts.append(f"Summary: {_shorten_text(summary, max_words=35)}")

        result.append(" | ".join(parts))

    return result


# ── Paragraph styles ──────────────────────────────────────────────────────────

def _make_styles() -> dict:
    styles = {}

    styles["body"] = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=DARK_GRAY,
        leading=13,
        spaceAfter=1 * mm,
    )

    styles["body_bold"] = ParagraphStyle(
        "body_bold",
        fontName="Helvetica-Bold",
        fontSize=9.5,
        textColor=BLACK,
        leading=13,
        spaceBefore=2.5 * mm,
        spaceAfter=0.8 * mm,
    )

    styles["exp_detail"] = ParagraphStyle(
        "exp_detail",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=EXP_DETAIL,
        leading=13,
        spaceAfter=0.8 * mm,
        leftIndent=3 * mm,
    )

    styles["extra_item"] = ParagraphStyle(
        "extra_item",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=DARK_GRAY,
        leading=13,
        spaceAfter=1.5 * mm,
        leftIndent=2 * mm,
    )

    return styles


# ── Section heading flowable ──────────────────────────────────────────────────

class SectionHeadingSpacer(Flowable):
    def __init__(self, label: str):
        super().__init__()
        self.label = label
        self.width = 0
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


# ── Skill tag flowable ────────────────────────────────────────────────────────

class SkillTagsFlowable(Flowable):
    """
    Renders all skills as rounded tags.
    No minimum/maximum threshold is used.
    """

    def __init__(self, skills: list, available_width: float):
        super().__init__()
        self.skills = skills
        self.available_width = available_width
        self._rows = []
        self.width = 0
        self.height = 0

    @staticmethod
    def _tag_width(skill: str) -> float:
        char_width = 4.2
        text_width = len(skill) * char_width
        return text_width + 2 * TAG_PAD_X

    def _compute_rows(self) -> list:
        rows = []
        current_row = []
        current_width = 0.0

        for skill in self.skills:
            tag_width = min(self._tag_width(skill), self.available_width)
            gap = TAG_H_GAP if current_row else 0.0

            if current_row and current_width + gap + tag_width > self.available_width:
                rows.append(current_row)
                current_row = [(skill, tag_width)]
                current_width = tag_width
            else:
                current_row.append((skill, tag_width))
                current_width += gap + tag_width

        if current_row:
            rows.append(current_row)

        return rows

    def wrap(self, available_width, available_height):
        self.available_width = available_width
        self.width = available_width
        self._rows = self._compute_rows()

        row_count = len(self._rows)

        self.height = (
            row_count * TAG_H
            + max(0, row_count - 1) * TAG_LINE_GAP
        )

        return available_width, self.height

    def draw(self):
        canvas = self.canv
        self._rows = self._compute_rows()

        canvas.saveState()

        y = self.height

        for row in self._rows:
            y -= TAG_H
            x = 0.0

            for skill, tag_width in row:
                tag_width = min(tag_width, self.available_width - x)

                if tag_width <= 0:
                    break

                canvas.setFillColor(SKILL_TAG_BG)
                canvas.setStrokeColor(SKILL_TAG_BORDER)
                canvas.setLineWidth(0.5)

                canvas.roundRect(
                    x,
                    y,
                    tag_width,
                    TAG_H,
                    TAG_RADIUS,
                    stroke=1,
                    fill=1,
                )

                text_y = y + (TAG_H - TAG_FONT_SIZE * 0.75) / 2
                canvas.setFillColor(SKILL_TAG_TEXT)
                canvas.setFont("Helvetica", TAG_FONT_SIZE)

                canvas.saveState()
                clip_path = canvas.beginPath()
                clip_path.rect(x, y, tag_width, TAG_H)
                canvas.clipPath(clip_path, stroke=0, fill=0)
                canvas.drawString(x + TAG_PAD_X, text_y, skill)
                canvas.restoreState()

                x += tag_width + TAG_H_GAP

            y -= TAG_LINE_GAP

        canvas.restoreState()


# ── Fixed section builders ────────────────────────────────────────────────────

def _build_fixed_left_content(cv: dict, styles: dict) -> list:
    """
    Fixed LEFT content.
    Skills always stay on the left side.
    """

    flowables = []

    flowables.append(SectionHeadingSpacer("Skills"))

    clean_skills = _clean_list(cv.get("skills", []))

    if not clean_skills:
        flowables.append(Paragraph("Not Found", styles["body"]))
    else:
        flowables.append(Spacer(1, 1 * mm))
        available_width = LEFT_COL_W - 2 * mm
        flowables.append(SkillTagsFlowable(clean_skills, available_width))

    return flowables


def _build_fixed_right_content(cv: dict, styles: dict) -> list:
    """
    Fixed RIGHT content.
    Educational Qualifications and Work Experience always stay on the right side.
    """

    flowables = []

    # Educational Qualifications
    flowables.append(SectionHeadingSpacer("Educational Qualifications"))

    qualifications = cv.get("educational_qualifications", [])

    if not qualifications:
        flowables.append(Paragraph("Not Found", styles["body"]))
    else:
        for index, edu in enumerate(qualifications):
            degree = _val(edu.get("degree", ""))
            institution = _val(edu.get("institution", ""))
            result = _val(edu.get("result", ""))
            year = _val(edu.get("year", ""))

            flowables.append(Paragraph(_esc(degree), styles["body_bold"]))

            if institution != "Not Found":
                flowables.append(
                    Paragraph(
                        f'<font color="#888888">Institution:&nbsp;&nbsp;&nbsp;&nbsp;</font>'
                        f'{_esc(institution)}',
                        styles["body"],
                    )
                )

            if result != "Not Found":
                flowables.append(
                    Paragraph(
                        f'<font color="#888888">Result / Grade:&nbsp;</font>'
                        f'{_esc(result)}',
                        styles["body"],
                    )
                )

            if year != "Not Found":
                flowables.append(
                    Paragraph(
                        f'<font color="#888888">Year:&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
                        f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</font>'
                        f'{_esc(year)}',
                        styles["body"],
                    )
                )

            if index < len(qualifications) - 1:
                flowables.append(Spacer(1, 2 * mm))
                flowables.append(
                    HRFlowable(
                        width="100%",
                        thickness=0.4,
                        color=RULE_GRAY,
                        spaceAfter=2 * mm,
                    )
                )

    # Work Experience
    flowables.append(Spacer(1, 4 * mm))
    flowables.append(
        HRFlowable(
            width="100%",
            thickness=0.6,
            color=RULE_GRAY,
            spaceAfter=1 * mm,
        )
    )
    flowables.append(SectionHeadingSpacer("Work Experience"))

    experiences = cv.get("experiences", [])

    if not experiences:
        flowables.append(Paragraph("Not Found", styles["body"]))
    else:
        for index, exp in enumerate(experiences):
            position = _val(exp.get("position", ""))
            company = _val(exp.get("company", ""))
            duration = _val(exp.get("duration", ""))
            details = _val(exp.get("details", ""))

            parts = []

            if position != "Not Found":
                parts.append(_esc(position))

            if company != "Not Found":
                parts.append(_esc(company))

            title_text = (
                f'<font color="#aaaaaa"> &nbsp;|&nbsp; </font>'.join(parts)
                if parts
                else "Not Found"
            )

            flowables.append(Paragraph(title_text, styles["body_bold"]))

            if duration != "Not Found":
                flowables.append(
                    Paragraph(
                        f'<font color="#888888">Duration:&nbsp;</font>{_esc(duration)}',
                        styles["body"],
                    )
                )

            if details and details != "Not Found":
                flowables.append(Spacer(1, 1 * mm))

                for line in details.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                    cleaned = line.strip().lstrip("-•*·▪▸►◆○●‣⁃∙➤✓✔ ").strip()

                    if cleaned:
                        flowables.append(
                            Paragraph(f"• {_esc(cleaned)}", styles["exp_detail"])
                        )

            if index < len(experiences) - 1:
                flowables.append(Spacer(1, 2 * mm))
                flowables.append(
                    HRFlowable(
                        width="100%",
                        thickness=0.3,
                        color=RULE_GRAY,
                        spaceAfter=1 * mm,
                    )
                )

    return flowables


# ── Movable extra sections ────────────────────────────────────────────────────

def _build_extra_section_flowables(sections: list, styles: dict) -> list:
    flowables = []

    for title, items in sections:
        clean_items = _clean_list(items)

        if not clean_items:
            continue

        flowables.append(Spacer(1, 3 * mm))
        flowables.append(
            HRFlowable(
                width="100%",
                thickness=0.4,
                color=RULE_GRAY,
                spaceAfter=1 * mm,
            )
        )
        flowables.append(SectionHeadingSpacer(title))

        for item in clean_items:
            cleaned = item.strip().lstrip("-•*·▪▸►◆○● ").strip()

            if cleaned:
                flowables.append(
                    Paragraph(f"• {_esc(cleaned)}", styles["extra_item"])
                )

    return flowables


def _build_left_content(cv: dict, left_extras: list, styles: dict) -> list:
    """
    Full left content = fixed left content + selected movable sections.
    """

    flowables = []
    flowables.extend(_build_fixed_left_content(cv, styles))
    flowables.extend(_build_extra_section_flowables(left_extras, styles))

    return flowables


def _build_right_content(cv: dict, right_extras: list, styles: dict) -> list:
    """
    Full right content = fixed right content + selected movable sections.
    """

    flowables = []
    flowables.extend(_build_fixed_right_content(cv, styles))
    flowables.extend(_build_extra_section_flowables(right_extras, styles))

    return flowables


# ── Height / page visual analysis ─────────────────────────────────────────────

def _estimate_flowables_height(flowables: list, available_width: float) -> float:
    """
    Estimate rendered height in millimeters using ReportLab wrap().
    This is used to compare all possible combinations before final PDF generation.
    """

    total_height = 0.0

    for flowable in flowables:
        try:
            _, height = flowable.wrap(available_width, 100000)
            total_height += height / mm
        except Exception:
            total_height += 4

    return total_height


def _column_page_stats(total_height_mm: float) -> dict:
    """
    Convert total column height into page statistics:
    - page_count
    - last_page_fill
    - remaining_empty_on_last_page
    """

    first_page_capacity = max(
        1.0,
        (DIVIDER_Y_P1 - MARGIN_BOTTOM - 4 * mm) / mm,
    )

    next_page_capacity = max(
        1.0,
        (DIVIDER_Y_PN - MARGIN_BOTTOM - 4 * mm) / mm,
    )

    if total_height_mm <= first_page_capacity:
        fill = total_height_mm / first_page_capacity
        return {
            "page_count": 1,
            "last_page_fill": fill,
            "last_page_empty": first_page_capacity - total_height_mm,
        }

    remaining = total_height_mm - first_page_capacity
    extra_pages = math.ceil(remaining / next_page_capacity)

    used_before_last = max(0, extra_pages - 1) * next_page_capacity
    last_page_height = remaining - used_before_last

    fill = last_page_height / next_page_capacity

    return {
        "page_count": 1 + extra_pages,
        "last_page_fill": fill,
        "last_page_empty": next_page_capacity - last_page_height,
    }


def _layout_score(left_height: float, right_height: float) -> tuple:
    """
    Lower score is better.

    Priority:
    1. Same number of pages.
    2. Similar last-page fill.
    3. Similar total height.
    """

    left_stats = _column_page_stats(left_height)
    right_stats = _column_page_stats(right_height)

    page_gap = abs(left_stats["page_count"] - right_stats["page_count"])
    fill_gap = abs(left_stats["last_page_fill"] - right_stats["last_page_fill"])
    height_gap = abs(left_height - right_height)

    score = (
        page_gap * 100000
        + fill_gap * 10000
        + height_gap
    )

    return (
        score,
        page_gap,
        fill_gap,
        height_gap,
        left_stats,
        right_stats,
    )


def _choose_best_balanced_layout(
    cv: dict,
    movable_sections: list,
    styles: dict,
) -> tuple[list, list]:
    """
    This is the main balancing logic.

    It first keeps fixed sections in their fixed positions:
      LEFT  = Skills
      RIGHT = Education + Work Experience

    Then it tests every possible combination of movable sections:
      Personal Projects, Achievements, Certificates, Trainings, Publications

    It chooses the combination that produces the most balanced visual layout.
    """

    if not movable_sections:
        return [], []

    best_left_extras = []
    best_right_extras = []
    best_result = None

    left_available_width = LEFT_COL_W - 2 * mm
    right_available_width = RIGHT_COL_W - 3 * mm

    # 0 = left, 1 = right
    all_placements = itertools.product([0, 1], repeat=len(movable_sections))

    for placement in all_placements:
        left_extras = []
        right_extras = []

        for index, side in enumerate(placement):
            section = movable_sections[index]

            if side == 0:
                left_extras.append(section)
            else:
                right_extras.append(section)

        left_flowables = _build_left_content(cv, left_extras, styles)
        right_flowables = _build_right_content(cv, right_extras, styles)

        left_height = _estimate_flowables_height(
            left_flowables,
            left_available_width,
        )
        right_height = _estimate_flowables_height(
            right_flowables,
            right_available_width,
        )

        result = _layout_score(left_height, right_height)

        if best_result is None or result[0] < best_result[0]:
            best_result = result
            best_left_extras = left_extras
            best_right_extras = right_extras

    score, page_gap, fill_gap, height_gap, left_stats, right_stats = best_result

    print(
        "  [balance] Best combination selected "
        f"| pages L/R={left_stats['page_count']}/{right_stats['page_count']} "
        f"| last-fill L/R={left_stats['last_page_fill']:.2f}/"
        f"{right_stats['last_page_fill']:.2f} "
        f"| height-gap≈{height_gap:.0f}mm"
    )

    for title, _ in best_left_extras:
        print(f"  [balance] '{title}' → LEFT")

    for title, _ in best_right_extras:
        print(f"  [balance] '{title}' → RIGHT")

    return best_left_extras, best_right_extras


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
        leftMargin=0,
        rightMargin=0,
        topMargin=0,
        bottomMargin=0,
    )

    def _make_frame(divider_y: float, frame_id: str) -> Frame:
        height = divider_y - MARGIN_BOTTOM

        return Frame(
            x1=frame_x,
            y1=MARGIN_BOTTOM,
            width=frame_w,
            height=height,
            leftPadding=0 if is_left else 3 * mm,
            rightPadding=2 * mm if is_left else 0,
            topPadding=4 * mm,
            bottomPadding=0,
            id=frame_id,
            showBoundary=0,
        )

    page_1_frame = _make_frame(DIVIDER_Y_P1, "p1")
    page_n_frame = _make_frame(DIVIDER_Y_PN, "pn")

    doc.addPageTemplates(
        [
            PageTemplate(id="page1", frames=[page_1_frame], onPage=lambda c, d: None),
            PageTemplate(id="pageN", frames=[page_n_frame], onPage=lambda c, d: None),
        ]
    )

    story = [NextPageTemplate("pageN")] + flowables
    doc.build(story)

    temp_doc = fitz.open(output_path)
    page_count = temp_doc.page_count
    temp_doc.close()

    return page_count


# ── Background / decoration layer ─────────────────────────────────────────────

def _build_background_pdf(output_path: str, n_pages: int, cv: dict) -> None:
    canvas = pdfgen_canvas.Canvas(output_path, pagesize=A4)

    candidate_name = _val(cv.get("candidate_name", ""), "Unknown Candidate")
    email = _val(cv.get("email", ""), "")

    for page_num in range(1, n_pages + 1):
        canvas.saveState()

        if page_num == 1:
            divider_y = DIVIDER_Y_P1

            if IMG_HEADER_DECO.exists():
                try:
                    canvas.drawImage(
                        str(IMG_HEADER_DECO),
                        x=DECO_X,
                        y=DECO_Y,
                        width=DECO_W,
                        height=DECO_H,
                        preserveAspectRatio=True,
                        mask="auto",
                    )
                except Exception as error:
                    print(f"[pdf_generator] Deco image error: {error}")

            name_upper = candidate_name.upper()
            name_x = MARGIN_LEFT
            name_y_top = PAGE_H - MARGIN_TOP - 8 * mm
            max_name_width = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT - DECO_W - 6 * mm
            font_size = 28
            line_height = font_size * 1.10

            canvas.setFont("Times-Bold", font_size)
            canvas.setFillColor(ORANGE)

            words = name_upper.split()
            lines = []
            current_line = ""

            for word in words:
                test_line = (current_line + " " + word).strip()

                if canvas.stringWidth(test_line, "Times-Bold", font_size) <= max_name_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word

            if current_line:
                lines.append(current_line)

            for index, line in enumerate(lines):
                canvas.drawString(name_x, name_y_top - index * line_height, line)

            email_y = name_y_top - len(lines) * line_height - 1.5 * mm
            canvas.setFont("Times-Roman", 9.5)
            canvas.setFillColor(DARK_GRAY)

            if email and email != "Not Found":
                canvas.drawString(name_x, email_y, f"Email: {email}")

        else:
            divider_y = DIVIDER_Y_PN

        canvas.setStrokeColor(ORANGE)
        canvas.setLineWidth(1.2)
        canvas.line(MARGIN_LEFT, divider_y, PAGE_W - MARGIN_RIGHT, divider_y)

        canvas.setStrokeColor(ORANGE)
        canvas.setLineWidth(1.0)
        canvas.line(VERT_LINE_X, divider_y, VERT_LINE_X, MARGIN_BOTTOM)

        if IMG_BRAND_LOGO.exists():
            try:
                canvas.drawImage(
                    str(IMG_BRAND_LOGO),
                    x=LOGO_X,
                    y=LOGO_Y,
                    width=LOGO_W,
                    height=LOGO_H,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception as error:
                print(f"[pdf_generator] Logo error: {error}")

        canvas.restoreState()
        canvas.showPage()

    canvas.save()


# ── PDF merger ────────────────────────────────────────────────────────────────

def _merge_pdfs(
    bg_path: str,
    left_path: str,
    right_path: str,
    output_path: str,
    n_pages: int,
) -> None:
    bg_doc = fitz.open(bg_path)
    left_doc = fitz.open(left_path)
    right_doc = fitz.open(right_path)
    out_doc = fitz.open()

    for index in range(n_pages):
        new_page = out_doc.new_page(width=PAGE_W, height=PAGE_H)

        new_page.show_pdf_page(new_page.rect, bg_doc, index)

        if index < left_doc.page_count:
            new_page.show_pdf_page(new_page.rect, left_doc, index)

        if index < right_doc.page_count:
            new_page.show_pdf_page(new_page.rect, right_doc, index)

    out_doc.save(output_path)
    out_doc.close()
    bg_doc.close()
    left_doc.close()
    right_doc.close()


# ── Public entry point ────────────────────────────────────────────────────────

def generate_individual_pdf(cv: dict) -> Path:
    """
    Generate one custom-designed balanced standardized PDF.

    Fixed sections are placed first:
      LEFT  = Skills
      RIGHT = Educational Qualifications + Work Experience

    Then all movable sections are tested in every possible left/right
    combination, and the most visually balanced combination is selected.
    """

    from app.file_helper import sanitize_filename

    candidate_name = _val(cv.get("candidate_name", ""), "Unknown Candidate")
    safe_name = sanitize_filename(candidate_name)

    source_file = _val(cv.get("source_file", ""), "")
    source_stem = sanitize_filename(Path(source_file).stem) if source_file else safe_name

    final_path = str(OUTPUT_FOLDER / f"{source_stem}_{safe_name}_CV.pdf")

    styles = _make_styles()

    movable_sections = []

    personal_projects = _clean_project_items(cv.get("personal_projects", []))

    if personal_projects:
        movable_sections.append(("Personal Projects", personal_projects))

    for title, key in [
        ("Achievements", "achievements"),
        ("Certificates", "certificates"),
        ("Trainings", "trainings"),
        ("Publications", "publications"),
    ]:
        items = _clean_list(cv.get(key, []))

        if items:
            movable_sections.append((title, items))

    left_extras, right_extras = _choose_best_balanced_layout(
        cv,
        movable_sections,
        styles,
    )

    left_flowables = _build_left_content(cv, left_extras, styles)
    right_flowables = _build_right_content(cv, right_extras, styles)

    with tempfile.TemporaryDirectory() as temp_dir:
        bg_path = os.path.join(temp_dir, "bg.pdf")
        left_path = os.path.join(temp_dir, "left.pdf")
        right_path = os.path.join(temp_dir, "right.pdf")

        left_pages = _build_column_pdf(
            left_flowables,
            left_path,
            frame_x=MARGIN_LEFT,
            frame_w=LEFT_COL_W,
            is_left=True,
        )

        right_pages = _build_column_pdf(
            right_flowables,
            right_path,
            frame_x=MARGIN_LEFT + LEFT_COL_W + GUTTER,
            frame_w=RIGHT_COL_W,
            is_left=False,
        )

        n_pages = max(left_pages, right_pages)

        _build_background_pdf(bg_path, n_pages, cv)
        _merge_pdfs(bg_path, left_path, right_path, final_path, n_pages)

    return Path(final_path)