import io
import os

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches


def png_bytes(color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_pptx(tmp_path):
    """Deck with: title+body slide, table slide with picture, group with text, notes, empty slide."""
    prs = Presentation()
    layout = prs.slide_layouts[1]  # title + content

    s1 = prs.slides.add_slide(layout)
    s1.shapes.title.text = "Intro to LLMs"
    s1.placeholders[1].text = "First bullet\nSecond bullet"
    s1.notes_slide.notes_text_frame.text = "Say hello"

    blank = prs.slide_layouts[6]
    s2 = prs.slides.add_slide(blank)
    tb = s2.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(1))
    tb.table.cell(0, 0).text = "Model"
    tb.table.cell(0, 1).text = "Price | cheap"
    tb.table.cell(1, 0).text = "Nova"
    tb.table.cell(1, 1).text = "low"
    pic = s2.shapes.add_picture(io.BytesIO(png_bytes()), Inches(1), Inches(3), Inches(1), Inches(1))
    pic._element.xpath(".//p:cNvPr")[0].set("descr", "Logo of the demo")

    s3 = prs.slides.add_slide(blank)
    group = s3.shapes.add_group_shape()
    box = group.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1))
    box.text_frame.text = "Grouped text"

    prs.slides.add_slide(blank)  # empty

    path = tmp_path / "deck.pptx"
    prs.save(path)
    return path


class FakeBackend:
    """Stands in for an LLM backend; records prompts and returns canned answers."""

    def __init__(self):
        self.calls = []  # (prompt, image)

    def complete(self, prompt, image, max_tokens):
        from pptx_to_md.llm import Completion

        self.calls.append((prompt, image))
        if image is not None:
            text = "<text>\nHello image\n</text>\n<description>\nA red square.\n</description>"
        else:
            text = "This slide introduces LLMs."
        return Completion(text=text, input_tokens=100, output_tokens=20, latency_ms=250)


@pytest.fixture
def fake_backend():
    return FakeBackend()


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Never read the developer's real config or credentials."""
    for name in list(os.environ):
        if name.startswith(("PPTX_TO_MD_", "AWS_", "OPENAI_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PPTX_TO_MD_CONFIG", str(tmp_path / "no-such-config.toml"))
