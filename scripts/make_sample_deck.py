"""Generate examples/sample.pptx, a small synthetic deck used by the README and the demo GIF."""

import io
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches

OUT = Path(__file__).resolve().parent.parent / "examples" / "sample.pptx"


def chart_png() -> bytes:
    im = Image.new("RGB", (640, 360), "white")
    d = ImageDraw.Draw(im)
    d.text((20, 15), "Monthly active users", fill="black")
    for i, h in enumerate([80, 130, 190, 260]):
        x = 90 + i * 130
        d.rectangle([x, 330 - h, x + 80, 330], fill=(40, 110, 220))
        d.text((x + 20, 335), f"Q{i + 1}", fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    prs = Presentation()

    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Quarterly Review"
    s.placeholders[1].text = "Product team, Q4"

    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Highlights"
    body = s.placeholders[1].text_frame
    body.text = "Launched the new onboarding flow"
    for text, level in [("Activation up 18%", 1), ("Support tickets down 12%", 1), ("Shipped 3 major integrations", 0)]:
        p = body.add_paragraph()
        p.text, p.level = text, level
    s.notes_slide.notes_text_frame.text = "Mention the onboarding experiment results."

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Roadmap"
    table = s.shapes.add_table(4, 3, Inches(1), Inches(2), Inches(8), Inches(2)).table
    rows = [
        ("Quarter", "Focus", "Status"),
        ("Q1", "Mobile app", "Planned"),
        ("Q2", "Offline mode", "Planned"),
        ("Q3", "API v2", "Idea"),
    ]
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.cell(r, c).text = value

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Growth"
    pic = s.shapes.add_picture(io.BytesIO(chart_png()), Inches(2), Inches(2), Inches(6))
    pic._element.xpath(".//p:cNvPr")[0].set("descr", "Bar chart of monthly active users growing each quarter")

    OUT.parent.mkdir(exist_ok=True)
    prs.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
