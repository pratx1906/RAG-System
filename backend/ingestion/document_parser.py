import os
import re
import pandas as pd
from pathlib import Path
from docx import Document as DocxDocument
from pptx import Presentation
from openpyxl import load_workbook

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".txt", ".csv", ".md"}

# -------------------------------------------------------
# DOCUMENT ROUTER
# -------------------------------------------------------

def parse_document(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        return _parse_pdf(file_path)

    elif ext in (".docx", ".doc"):
        return _parse_docx(file_path)

    elif ext in (".xlsx", ".xls"):
        return _parse_excel(file_path)

    elif ext == ".pptx":
        return _parse_pptx(file_path)

    elif ext == ".csv":
        return _parse_csv(file_path)

    elif ext in (".txt", ".md"):
        return _parse_text(file_path)

    else:
        raise ValueError(f"Unsupported file type: {ext}")


# -------------------------------------------------------
# Surya + Marker PDF Parser (Layout-aware)
# -------------------------------------------------------

_marker_converter = None


def _get_marker_converter():
    global _marker_converter

    if _marker_converter is not None:
        return _marker_converter

    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        _marker_converter = PdfConverter(
            artifact_dict=create_model_dict(),
        )

    except ImportError as exc:
        raise ImportError(
            "marker-pdf is not installed. Install with: pip install marker-pdf"
        ) from exc

    return _marker_converter


def _parse_pdf(path):

    converter = _get_marker_converter()

    rendered = converter(path)

    if hasattr(rendered, "markdown"):
        markdown_text = rendered.markdown
    else:
        from marker.output import text_from_rendered
        markdown_text, _, _ = text_from_rendered(rendered)

    return _markdown_to_plain_text(markdown_text)


# -------------------------------------------------------
# MARKDOWN → TEXT (FIGURES + TABLES + PAGE ANCHORS)
# -------------------------------------------------------

def _markdown_to_plain_text(markdown: str):

    lines = markdown.split("\n")
    result = []
    in_table = False

    page_counter = 1

    for line in lines:

        stripped = line.strip()

        # -----------------------
        # PAGE ANCHORS
        # -----------------------

        if stripped.lower().startswith("page "):

            result.append(f"\n[PAGE {page_counter}]\n")
            page_counter += 1
            continue

        # -----------------------
        # FIGURES / IMAGES
        # -----------------------

        img_match = re.match(r'!\[(.*?)\]\((.*?)\)', stripped)

        if img_match:

            caption = img_match.group(1).strip()

            if caption:
                result.append(f"\n[FIGURE] {caption}\n")
            else:
                result.append("\n[FIGURE]\n")

            continue

        # -----------------------
        # TABLE SEPARATOR
        # -----------------------

        if "|" in stripped and re.fullmatch(r'[\|\s\-:]+', stripped):

            in_table = True
            continue

        # -----------------------
        # HEADINGS
        # -----------------------

        heading = re.match(r'^(#{1,6})\s+(.*)', line)

        if heading:

            title = heading.group(2).strip()

            result.append(f"\n[SECTION] {title}\n")

            continue

        # -----------------------
        # CLEAN MARKDOWN SYNTAX
        # -----------------------

        line = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', line)
        line = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', line)
        line = re.sub(r'~~(.*?)~~', r'\1', line)
        line = re.sub(r'`(.+?)`', r'\1', line)
        line = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', line)

        # -----------------------
        # TABLE ROWS
        # -----------------------

        if "|" in line:

            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]

            if parts:

                if not in_table:
                    result.append("\n[TABLE]")
                    in_table = True

                line = " | ".join(parts)

        else:

            in_table = False

        result.append(line)

    text = "\n".join(result)

    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# -------------------------------------------------------
# DOCX
# -------------------------------------------------------

def _parse_docx(path):

    doc = DocxDocument(path)

    parts = []

    for para in doc.paragraphs:

        if para.text.strip():
            parts.append(para.text)

    for table in doc.tables:

        parts.append("[TABLE]")

        for row in table.rows:

            row_text = " | ".join(
                cell.text.strip()
                for cell in row.cells
                if cell.text.strip()
            )

            if row_text:
                parts.append(row_text)

    return "\n".join(parts)


# -------------------------------------------------------
# NATURAL LANGUAGE FOR SPREADSHEETS (UNCHANGED)
# -------------------------------------------------------

def _row_to_natural_language(fields: dict) -> str:

    def get(*keys):
        for k in keys:
            for fk, fv in fields.items():
                if fk.lower().strip() == k.lower():
                    return fv
        return ""

    project  = get("project", "name", "title", "task")
    people   = get("people involved", "people", "team", "members",
                   "assigned to", "owner", "responsible")
    status   = get("status", "state", "progress", "stage")
    category = get("category", "type", "domain", "area", "department")
    details  = get("details", "description", "notes", "summary", "objective")
    date     = get("date", "deadline", "due date", "due", "milestone", "timeline")

    parts = []

    if people and project:

        verb = "is" if "," not in people else "are"

        status_part = f", Status: {status}" if status else ""
        category_part = f", Category: {category}" if category else ""

        parts.append(
            f"{people} {verb} working on {project} (Status: {status}{category_part})."
            if status
            else f"{people} {verb} working on {project}{category_part}."
        )

    elif project:
        parts.append(f"Project: {project}.")

    if details:
        parts.append(f"Details: {details}.")

    if date:
        parts.append(f"Date: {date}.")

    if not parts:
        parts = [f"The {k} is {v}." for k, v in fields.items() if v]

    return " ".join(parts)


# -------------------------------------------------------
# EXCEL PARSER (UNCHANGED EXACTLY)
# -------------------------------------------------------

def _parse_excel(path):

    wb = load_workbook(path, data_only=True)

    parts = []

    for sheet in wb.sheetnames:

        ws = wb[sheet]

        rows = list(ws.iter_rows(values_only=True))

        if not rows:
            continue

        headers = [str(h).strip() if h is not None else "" for h in rows[0]]

        for row in rows[1:]:

            cells = [str(v).strip() if v is not None else "" for v in row]

            if not any(cells):
                continue

            field_dict = {
                h: v for h, v in zip(headers, cells) if h and v
            }

            if not field_dict:
                continue

            PRIORITY_FIELDS = ["people involved", "project", "status", "category"]

            reordered = {}

            for pf in PRIORITY_FIELDS:
                for k, v in field_dict.items():
                    if k.lower().strip() == pf and k not in reordered:
                        reordered[k] = v

            for k, v in field_dict.items():
                if k not in reordered:
                    reordered[k] = v

            structured = "[Sheet: {}] {} | ".format(
                sheet,
                " | ".join(f"{h}: {v}" for h, v in reordered.items())
            )

            nl = _row_to_natural_language(reordered)

            parts.append(f"{structured}\n{nl}")

    return "\n---\n".join(parts)


# -------------------------------------------------------
# PPTX PARSER (CHART + TABLE AWARE)
# -------------------------------------------------------

def _parse_pptx(path):

    prs = Presentation(path)

    text = []

    for i, slide in enumerate(prs.slides):

        text.append(f"\n[SLIDE {i+1}]\n")

        for shape in slide.shapes:

            if hasattr(shape, "text") and shape.text.strip():

                text.append(shape.text.strip())

            if shape.has_table:

                text.append("[TABLE]")

                for row in shape.table.rows:

                    row_text = " | ".join(
                        cell.text.strip()
                        for cell in row.cells
                        if cell.text.strip()
                    )

                    if row_text:
                        text.append(row_text)

            if shape.has_chart:

                try:
                    title = shape.chart.chart_title.text_frame.text
                except:
                    title = ""

                if title:
                    text.append(f"[CHART] {title}")
                else:
                    text.append("[CHART]")

    return "\n".join(text)


# -------------------------------------------------------
# CSV PARSER
# -------------------------------------------------------

def _parse_csv(path):

    df = pd.read_csv(path)

    parts = []

    for i, row in df.iterrows():

        field_dict = {
            col: str(val).strip()
            for col, val in row.items()
            if pd.notna(val) and str(val).strip()
        }

        if not field_dict:
            continue

        structured = " | ".join(
            f"{k}: {v}" for k, v in field_dict.items()
        ) + " | "

        nl = _row_to_natural_language(field_dict)

        parts.append(f"[ROW {i+1}]\n{structured}\n{nl}")

    return "\n---\n".join(parts)


# -------------------------------------------------------
# TEXT / MARKDOWN
# -------------------------------------------------------

def _parse_text(path):

    with open(path, "r", encoding="utf-8", errors="ignore") as f:

        content = f.read()

    content = re.sub(
        r'^#{1,6}\s+(.*)',
        r'\n[SECTION] \1\n',
        content,
        flags=re.MULTILINE
    )

    return content