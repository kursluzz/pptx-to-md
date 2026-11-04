"""Read a .pptx file into the Presentation model (text, tables, charts, pictures, notes)."""

from __future__ import annotations

import contextlib
from pathlib import Path

from pptx import Presentation as PptxPresentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.shapes.base import BaseShape

from .model import Element, ImageAsset, Presentation, Slide

_BOILERPLATE_TYPES = {PP_PLACEHOLDER.SLIDE_NUMBER, PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.FOOTER}
_BODY_TYPES = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT}


def extract_presentation(path: str | Path) -> Presentation:
    path = Path(path)
    prs = PptxPresentation(str(path))
    result = Presentation(source_name=path.name)
    for index, slide in enumerate(prs.slides, start=1):
        result.slides.append(_extract_slide(slide, index))
    return result


def _extract_slide(slide, number: int) -> Slide:
    title_shape = slide.shapes.title
    title = _clean(title_shape.text_frame.text) if title_shape is not None and title_shape.has_text_frame else ""

    out = Slide(number=number, title=title)
    for shape in slide.shapes:
        if title_shape is not None and shape.shape_id == title_shape.shape_id:
            continue
        out.elements.extend(_shape_elements(shape))

    if slide.has_notes_slide:
        notes_frame = slide.notes_slide.notes_text_frame
        if notes_frame is not None:
            out.notes = _clean(notes_frame.text)
    return out


def _shape_elements(shape: BaseShape) -> list[Element]:
    if getattr(shape, "is_placeholder", False) and shape.placeholder_format.type in _BOILERPLATE_TYPES:
        return []  # slide number, date and footer placeholders only repeat on every slide
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        elements: list[Element] = []
        for child in shape.shapes:
            elements.extend(_shape_elements(child))
        return elements

    if getattr(shape, "has_table", False):
        rows = [[_clean(cell.text) for cell in row.cells] for row in shape.table.rows]
        rows = [row for row in rows if any(row)]
        return [Element(kind="table", rows=rows)] if rows else []

    if getattr(shape, "has_chart", False):
        text = _chart_text(shape.chart)
        return [Element(kind="text", text=text)] if text else []

    image = _picture_asset(shape)
    if image is not None:
        return [Element(kind="image", image=image)]

    if shape.has_text_frame:
        text = _frame_text(shape)
        return [Element(kind="text", text=text)] if text else []

    return []


def _picture_asset(shape: BaseShape) -> ImageAsset | None:
    is_picture = shape.shape_type == MSO_SHAPE_TYPE.PICTURE
    if not is_picture and not getattr(shape, "is_placeholder", False):
        return None
    try:
        image = shape.image  # raises for placeholders without a picture and for linked images
    except Exception:
        return None
    alt = ""
    with contextlib.suppress(Exception):
        alt = _clean(shape._element.xpath(".//p:cNvPr")[0].get("descr", "")).replace("\n", " ")
        alt = alt.replace("Description automatically generated", "").strip()  # PowerPoint boilerplate
    return ImageAsset(blob=image.blob, ext=image.ext.lower(), name=getattr(shape, "name", ""), alt=alt)


_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _frame_text(shape: BaseShape) -> str:
    """Text of a shape, keeping bullet lists (with nesting) as Markdown lists."""
    is_body = bool(getattr(shape, "is_placeholder", False)) and shape.placeholder_format.type in _BODY_TYPES
    lines: list[str] = []
    for paragraph in shape.text_frame.paragraphs:
        text = _clean(paragraph.text.replace("\x0b", " "))
        if not text:
            continue
        ppr = paragraph._p.pPr
        no_bullet = ppr is not None and ppr.find("a:buNone", _NS) is not None
        explicit = ppr is not None and (
            ppr.find("a:buChar", _NS) is not None or ppr.find("a:buAutoNum", _NS) is not None
        )
        if (explicit or (is_body and not no_bullet)) and paragraph.level >= 0:
            lines.append("  " * paragraph.level + "- " + text)
        else:
            lines.append(text)
    return "\n".join(lines)


def _chart_text(chart) -> str:
    parts: list[str] = []
    if chart.has_title and chart.chart_title.has_text_frame:
        title = _clean(chart.chart_title.text_frame.text)
        if title:
            parts.append(f"Chart: {title}")
    for plot in chart.plots:
        categories = [str(c) for c in plot.categories]
        if categories:
            parts.append("Categories: " + ", ".join(categories))
        series_names = [s.name for s in plot.series if s.name]
        if series_names:
            parts.append("Series: " + ", ".join(series_names))
    return "\n".join(parts)


def _clean(text: str) -> str:
    """Normalise python-pptx line breaks (vertical tab for soft breaks) and trim whitespace."""
    lines = [line.strip() for line in text.replace("\x0b", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)
