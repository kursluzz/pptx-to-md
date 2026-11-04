"""Prepare embedded pictures: keep formats the LLM accepts, convert the rest (EMF/WMF/SVG...) with LibreOffice."""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .model import ImageAsset

log = logging.getLogger(__name__)

# Formats accepted by the Bedrock Converse image content block.
LLM_FORMATS = {"png", "jpeg", "gif", "webp"}
_ALIASES = {"jpg": "jpeg"}


# Conservative per-image limits (Bedrock: 3.75 MB and 8000 px per side).
MAX_LLM_BYTES = 3_500_000
MAX_LLM_SIDE = 7_500


@dataclass
class PreparedImage:
    blob: bytes  # what is stored next to the Markdown file
    ext: str  # file extension to store the image with
    llm_ok: bool  # True when the LLM can read the image
    llm_blob: bytes | None = None  # payload for the LLM when `blob` is too large (else use `blob`)
    llm_ext: str | None = None

    @property
    def for_llm(self) -> tuple[bytes, str]:
        return (self.llm_blob or self.blob, self.llm_ext or self.ext)


def prepare_image(asset: ImageAsset) -> PreparedImage:
    ext = _ALIASES.get(asset.ext, asset.ext)
    if ext in LLM_FORMATS:
        return _with_llm_payload(PreparedImage(blob=asset.blob, ext=ext, llm_ok=True))

    converted = _convert_with_pillow(asset.blob) or _convert_with_libreoffice(asset)
    if converted is not None:
        return _with_llm_payload(PreparedImage(blob=converted, ext="png", llm_ok=True))

    log.warning("cannot convert %s image %s; it will be stored as-is", asset.ext, asset.name or "?")
    return PreparedImage(blob=asset.blob, ext=asset.ext, llm_ok=False)


def _with_llm_payload(img: PreparedImage) -> PreparedImage:
    """Shrink pictures that exceed provider limits, for the LLM request only (the stored file is untouched)."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(img.blob)) as im:
            too_big = max(im.size) > MAX_LLM_SIDE
            if len(img.blob) <= MAX_LLM_BYTES and not too_big:
                return img
            im.seek(0)
            im = im.convert("RGB")
            side = min(max(im.size), 4000)
            while True:
                copy = im.copy()
                copy.thumbnail((side, side))
                buf = io.BytesIO()
                copy.save(buf, format="JPEG", quality=85)
                if buf.tell() <= MAX_LLM_BYTES or side <= 500:
                    img.llm_blob, img.llm_ext = buf.getvalue(), "jpeg"
                    return img
                side = int(side * 0.7)
    except Exception as exc:  # unreadable image: send as-is and let the provider decide
        log.debug("cannot shrink image: %s", exc)
        return img


def _convert_with_pillow(blob: bytes) -> bytes | None:
    """Raster formats LLMs do not accept (BMP, TIFF, ...) -> PNG. Returns None if Pillow cannot read it."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(blob)) as im:
            im.seek(0)
            buf = io.BytesIO()
            im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None


def _convert_with_libreoffice(asset: ImageAsset) -> bytes | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return None
    with tempfile.TemporaryDirectory(prefix="pptx_to_md_img_") as tmp:
        src = Path(tmp) / f"input.{asset.ext}"
        src.write_bytes(asset.blob)
        try:
            # a private profile dir lets this run even while a LibreOffice window is open
            profile = (Path(tmp) / "profile").as_uri()
            subprocess.run(
                [
                    soffice,
                    f"-env:UserInstallation={profile}",
                    "--headless",
                    "--convert-to",
                    "png",
                    "--outdir",
                    tmp,
                    str(src),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.debug("libreoffice conversion failed: %s", exc)
            return None
        out = Path(tmp) / "input.png"
        return out.read_bytes() if out.exists() else None
