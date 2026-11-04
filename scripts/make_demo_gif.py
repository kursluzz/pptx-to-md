"""Render docs/demo.gif: a terminal session recorded from the real CLI run on examples/sample.pptx.

    uv run python scripts/make_demo_gif.py

The commands are executed for real in a temp directory; only the typing animation is synthetic.
Needs Pillow and the DejaVu Sans Mono font (or pass FONT=/path/to/mono.ttf).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = os.environ.get("FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
W, H, SIZE, PAD, TOP = 880, 560, 17, 22, 46
BG, FG, DIM = (30, 32, 40), (220, 223, 228), (140, 146, 160)
GREEN, BLUE, YELLOW = (130, 210, 120), (110, 170, 255), (240, 200, 110)

COMMANDS = [
    "pptx-to-md examples/sample.pptx -o output",
    "ls output",
    "head -n 22 output/sample.md",
]


def run_real(workdir: Path) -> list[list[str]]:
    """Run the commands for real and return their output lines."""
    shutil.copytree(ROOT / "examples", workdir / "examples", ignore=shutil.ignore_patterns("output"))
    outputs = []
    cli = [sys.executable, "-m", "pptx_to_md"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for cmd in COMMANDS:
        if cmd.startswith("pptx-to-md"):
            res = subprocess.run(
                cli + cmd.split()[1:], cwd=workdir, capture_output=True, text=True, env=env, check=True
            )
            text = res.stdout
        elif cmd.startswith("ls"):
            text = (
                "  ".join(sorted(p.name + ("/" if p.is_dir() else "") for p in (workdir / "output").iterdir())) + "\n"
            )
        else:
            text = "".join((workdir / "output" / "sample.md").read_text().splitlines(keepends=True)[:22])
        outputs.append(text.rstrip("\n").split("\n"))
    return outputs


def colour(line: str) -> tuple[int, int, int]:
    if line.startswith("#"):
        return BLUE
    if line.startswith(("Converted", "![")):
        return GREEN if line.startswith("Converted") else YELLOW
    return FG if line.startswith(("|", "-", "  -", "**")) else DIM if line.startswith("sample") else FG


def render(lines: list[tuple[str, tuple[int, int, int]]], font: ImageFont.FreeTypeFont, cursor: bool) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 34], fill=(45, 48, 58))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16 + i * 22, 11, 28 + i * 22, 23], fill=c)
    d.text((W // 2, 17), "terminal", fill=DIM, font=font, anchor="mm")
    line_h = SIZE + 6
    visible = lines[-((H - TOP - PAD) // line_h) :]
    y = TOP
    for text, color in visible:
        if text.startswith("$ "):
            d.text((PAD, y), "$", fill=GREEN, font=font)
            d.text((PAD + font.getlength("$ "), y), text[2:], fill=FG, font=font)
        else:
            d.text((PAD, y), text, fill=color, font=font)
        y += line_h
    if cursor and visible:
        last = visible[-1][0]
        x = PAD + font.getlength(last)
        d.rectangle([x, y - line_h + 2, x + font.getlength("M"), y - 4], fill=FG)
    return im


def main() -> None:
    font = ImageFont.truetype(FONT, SIZE)
    with tempfile.TemporaryDirectory() as tmp:
        outputs = run_real(Path(tmp))

    frames: list[tuple[Image.Image, int]] = []
    shown: list[tuple[str, tuple[int, int, int]]] = []

    def add(cursor: bool, ms: int) -> None:
        frames.append((render(shown, font, cursor), ms))

    shown.append(("$ ", FG))
    add(True, 600)
    for cmd, out in zip(COMMANDS, outputs, strict=True):
        for n in range(2, len(cmd) + 2, 2):
            shown[-1] = ("$ " + cmd[:n], FG)
            add(True, 45)
        add(False, 500)
        for line in out:
            shown.append((line, colour(line)))
            add(False, 70 if cmd.startswith("head") else 180)
        add(False, 900)
        shown.append(("$ ", FG))
        add(True, 400)
    frames[-1] = (frames[-1][0], 3500)

    out_path = ROOT / "docs" / "demo.gif"
    out_path.parent.mkdir(exist_ok=True)
    pal = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=32) for f, _ in frames]
    pal[0].save(
        out_path, save_all=True, append_images=pal[1:], duration=[ms for _, ms in frames], loop=0, optimize=True
    )
    print(f"wrote {out_path} ({out_path.stat().st_size // 1024} KiB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
