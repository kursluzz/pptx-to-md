"""Orchestrates extraction, LLM enrichment and writing of the Markdown output."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

from .extract import extract_presentation
from .images import PreparedImage, prepare_image
from .model import ImageInfo
from .render import RenderContext, render_markdown
from .usage import format_summary

log = logging.getLogger(__name__)


class Describer(Protocol):
    def describe_image(self, blob: bytes, fmt: str) -> ImageInfo: ...

    def describe_slide(self, number: int, slide_text: str, image_infos: list[ImageInfo]) -> str: ...


def convert_file(
    pptx_path: str | Path,
    output_dir: str | Path,
    describer: Describer | None = None,
    workers: int = 2,
) -> Path:
    """Convert one .pptx into `<output_dir>/<stem>.md`; images go to `<output_dir>/<stem>_assets/`.

    With describer=None no LLM call is made: pictures are still stored and linked, but their
    text/descriptions are not produced. LLM errors propagate (the deck is not written half-done).
    """
    pptx_path = Path(pptx_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pptx_path.stem
    md_path = output_dir / f"{stem}.md"
    assets_dir = output_dir / f"{stem}_assets"

    log.info("converting %s", pptx_path)
    tracker = getattr(describer, "usage", None)
    before = tracker.snapshot() if tracker is not None else None
    pres = extract_presentation(pptx_path)

    # 1. unique pictures, prepared (converted if needed) and stored once each
    unique: dict[str, PreparedImage] = {}
    for slide in pres.slides:
        for asset in slide.images:
            if asset.digest not in unique:
                unique[asset.digest] = prepare_image(asset)

    image_paths: dict[str, str] = {}
    if unique:
        assets_dir.mkdir(parents=True, exist_ok=True)
    for digest, prepared in unique.items():
        filename = f"img_{digest[:12]}.{prepared.ext}"
        (assets_dir / filename).write_bytes(prepared.blob)
        image_paths[digest] = f"{assets_dir.name}/{filename}"

    # 2. LLM (only if enabled): text + description per unique picture, then one call per slide
    image_infos: dict[str, ImageInfo] = {}
    slide_descriptions: dict[int, str] = {}
    if describer is not None:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            llm_images = [(d, p) for d, p in unique.items() if p.llm_ok]
            futures_img = {d: pool.submit(describer.describe_image, *p.for_llm) for d, p in llm_images}

            slides = [s for s in pres.slides if s.plain_text() or s.images]
            # slide descriptions use the image results, so wait for the picture calls first
            try:
                for digest, future in futures_img.items():
                    image_infos[digest] = future.result()  # re-raises LLM errors
            except BaseException:
                for f in futures_img.values():
                    f.cancel()  # do not keep paying for calls once the deck has failed
                raise

            futures_slide = {
                s.number: pool.submit(
                    describer.describe_slide,
                    s.number,
                    s.plain_text(),
                    [image_infos[a.digest] for a in s.images if a.digest in image_infos],
                )
                for s in slides
            }
            try:
                for number, future in futures_slide.items():
                    text = future.result()  # re-raises LLM errors
                    if text:
                        slide_descriptions[number] = text
            except BaseException:
                for f in futures_slide.values():
                    f.cancel()
                raise

    # 3. render
    ctx = RenderContext(
        image_infos=image_infos,
        image_paths=image_paths,
        slide_descriptions=slide_descriptions,
        llm_enabled=describer is not None,
    )
    md_path.write_text(render_markdown(pres, ctx), encoding="utf-8")
    log.info("wrote %s (%d slides, %d images)", md_path, len(pres.slides), len(unique))

    if tracker is not None:
        deck_usage = tracker.record_deck(pptx_path.name, before, tracker.snapshot())
        log.info("LLM usage for %s:\n%s", pptx_path.name, format_summary(deck_usage))
    return md_path


def convert_tree(
    input_path: str | Path,
    output_dir: str | Path,
    describer: Describer | None = None,
    workers: int = 2,
) -> list[tuple[Path, Exception | None]]:
    """Convert a .pptx file, or every .pptx below a directory (mirroring its layout).

    Returns (source, error) pairs; error is None on success. A failing deck does not stop the others.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    if input_path.is_file():
        jobs = [(input_path, output_dir)]
    else:
        sources = sorted(
            p
            for p in input_path.rglob("*")
            if p.is_file() and p.suffix.lower() == ".pptx" and not p.name.startswith("~$")
        )
        jobs = [(p, output_dir / p.parent.relative_to(input_path)) for p in sources]

    results: list[tuple[Path, Exception | None]] = []
    for source, target in jobs:
        try:
            convert_file(source, target, describer=describer, workers=workers)
            results.append((source, None))
        except Exception as exc:  # keep going, report at the end
            log.exception("failed to convert %s", source)
            results.append((source, exc))
    return results
