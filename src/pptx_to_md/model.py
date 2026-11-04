"""Format-independent data model produced by the extractor and consumed by the renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ImageAsset:
    """An embedded picture. `blob` is raw bytes, `ext` is the file extension without dot."""

    blob: bytes
    ext: str
    name: str = ""  # original shape name, informational only
    alt: str = ""  # alt text written by the deck author (may be empty)

    @property
    def digest(self) -> str:
        import hashlib

        return hashlib.sha256(self.blob).hexdigest()


@dataclass
class Element:
    """One piece of slide content, kept in the deck's shape (z-)order, which is the reading order in most decks."""

    kind: Literal["text", "table", "image"]
    text: str = ""  # for lists, one line per item, already prefixed with indentation and "- "
    rows: list[list[str]] = field(default_factory=list)
    image: ImageAsset | None = None


@dataclass
class ImageInfo:
    """What the LLM (or nothing, when disabled) knows about one image."""

    text: str = ""  # text found inside the image
    description: str = ""


@dataclass
class Slide:
    number: int
    title: str = ""
    elements: list[Element] = field(default_factory=list)
    notes: str = ""

    def plain_text(self) -> str:
        """All text on the slide as plain lines, used as context for the LLM."""
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        for el in self.elements:
            if el.kind == "text" and el.text:
                parts.append(el.text)
            elif el.kind == "table":
                parts.extend(" | ".join(row) for row in el.rows)
        return "\n".join(parts)

    @property
    def images(self) -> list[ImageAsset]:
        return [el.image for el in self.elements if el.kind == "image" and el.image is not None]


@dataclass
class Presentation:
    source_name: str
    slides: list[Slide] = field(default_factory=list)
