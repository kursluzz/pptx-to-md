from pptx_to_md.extract import extract_presentation
from pptx_to_md.model import ImageAsset


def test_extracts_title_text_table_group_and_notes(sample_pptx):
    pres = extract_presentation(sample_pptx)
    assert len(pres.slides) == 4

    s1 = pres.slides[0]
    assert s1.title == "Intro to LLMs"
    assert [e.text for e in s1.elements] == ["- First bullet\n- Second bullet"]
    assert s1.notes == "Say hello"

    s2 = pres.slides[1]
    kinds = [e.kind for e in s2.elements]
    assert kinds == ["table", "image"]
    assert s2.elements[0].rows == [["Model", "Price | cheap"], ["Nova", "low"]]
    assert isinstance(s2.elements[1].image, ImageAsset)
    assert s2.elements[1].image.ext == "png"
    assert s2.elements[1].image.alt == "Logo of the demo"

    assert pres.slides[2].elements[0].text == "Grouped text"
    assert pres.slides[3].elements == [] and pres.slides[3].title == ""


def test_image_digest_is_content_based(sample_pptx):
    pres = extract_presentation(sample_pptx)
    img = pres.slides[1].images[0]
    assert len(img.digest) == 64


def test_footer_and_slide_number_placeholders_are_skipped(tmp_path):
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "T"
    slide.placeholders[1].text = "body"
    # PowerPoint copies footer placeholders from the layout; emulate one carrying "‹#›"
    from copy import deepcopy

    for ph in prs.slide_layouts[1].placeholders:
        if ph.placeholder_format.type.name in ("SLIDE_NUMBER", "FOOTER", "DATE"):
            slide.shapes._spTree.append(deepcopy(ph._element))
    path = tmp_path / "f.pptx"
    prs.save(path)
    elements = extract_presentation(path).slides[0].elements
    assert [e.text for e in elements] == ["- body"]
