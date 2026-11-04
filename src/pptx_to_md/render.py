"""Render a Presentation (plus LLM results) to Markdown."""

from __future__ import annotations

from urllib.parse import quote

from .model import Element, ImageInfo, Presentation, Slide


class RenderContext:
    """Per-deck lookup tables needed while rendering."""

    def __init__(
        self,
        image_infos: dict[str, ImageInfo],
        image_paths: dict[str, str],
        slide_descriptions: dict[int, str],
        llm_enabled: bool,
    ) -> None:
        self.image_infos = image_infos  # image digest -> info
        self.image_paths = image_paths  # image digest -> path relative to the markdown file
        self.slide_descriptions = slide_descriptions  # slide number -> description
        self.llm_enabled = llm_enabled


def render_markdown(pres: Presentation, ctx: RenderContext) -> str:
    out: list[str] = [f"# {pres.source_name}", "", f"Slides: {len(pres.slides)}", ""]
    for slide in pres.slides:
        out.extend(_render_slide(slide, ctx))
    return "\n".join(out).rstrip() + "\n"


def _render_slide(slide: Slide, ctx: RenderContext) -> list[str]:
    heading = f"## Slide {slide.number}"
    if slide.title:
        heading += f": {slide.title}"
    lines: list[str] = [heading, ""]

    image_index = 0
    for el in slide.elements:
        if el.kind == "text":
            lines += [el.text, ""]
        elif el.kind == "table":
            lines += _render_table(el) + [""]
        elif el.kind == "image" and el.image is not None:
            image_index += 1
            lines += _render_image(el, slide.number, image_index, ctx) + [""]

    description = ctx.slide_descriptions.get(slide.number, "")
    if description:
        lines += [f"**Slide description:** {description}", ""]

    if slide.notes:
        lines += ["**Speaker notes:**", ""] + [line for line in slide.notes.split("\n")] + [""]

    if len(lines) == 2:  # heading only, nothing on the slide
        lines.append("_(empty slide)_")
        lines.append("")
    return lines


def _render_table(el: Element) -> list[str]:
    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>")

    if not el.rows:
        return []
    width = max(len(r) for r in el.rows)
    rows = [[cell(c) for c in r] + [""] * (width - len(r)) for r in el.rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines


def _render_image(el: Element, slide_no: int, index: int, ctx: RenderContext) -> list[str]:
    assert el.image is not None
    digest = el.image.digest
    lines: list[str] = []
    path = ctx.image_paths.get(digest)
    alt = el.image.alt.replace("[", "(").replace("]", ")") or f"Slide {slide_no} image {index}"
    if path:
        lines.append(f"![{alt}](<{quote(path)}>)")
    else:
        lines.append(f"_({alt}: image could not be stored)_")

    info = ctx.image_infos.get(digest)
    if not ctx.llm_enabled or info is None:
        return lines
    if info.text:
        lines.append(">")
        lines.append("> **Text in image:**")
        lines += [f"> {line}" if line else ">" for line in info.text.split("\n")]
    if info.description:
        lines.append(">")
        lines.append(f"> _Image description:_ {info.description}")
    return lines
