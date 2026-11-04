from pptx_to_md.config import Settings
from pptx_to_md.converter import convert_file, convert_tree
from pptx_to_md.llm import LLMDescriber


def make_describer(backend):
    return LLMDescriber(Settings(provider="bedrock"), backend=backend)


def test_convert_without_llm(sample_pptx, tmp_path):
    out = tmp_path / "out"
    md_path = convert_file(sample_pptx, out, describer=None)
    md = md_path.read_text(encoding="utf-8")
    assert md_path.name == "deck.md"
    assert "## Slide 1: Intro to LLMs" in md
    assert "- First bullet\n- Second bullet" in md
    assert "Say hello" in md
    assert "| Model | Price \\| cheap |" in md
    assert "| Nova | low |" in md
    assert "Grouped text" in md
    assert "_(empty slide)_" in md
    assert "Slide description" not in md and "Image description" not in md
    images = list((out / "deck_assets").iterdir())
    assert len(images) == 1 and images[0].suffix == ".png"
    assert "![Logo of the demo](<deck_assets/" in md  # author's alt text is used


def test_convert_with_llm(sample_pptx, tmp_path, fake_backend):
    md = convert_file(sample_pptx, tmp_path / "out", describer=make_describer(fake_backend)).read_text(encoding="utf-8")
    assert "**Text in image:**" in md and "Hello image" in md
    assert "_Image description:_ A red square." in md
    assert "**Slide description:** This slide introduces LLMs." in md
    # one image call (unique picture) + one call for each of the three slides with content
    assert sum(1 for _, image in fake_backend.calls if image) == 1
    assert len(fake_backend.calls) == 4


def test_llm_payloads_are_minimal(sample_pptx, tmp_path, fake_backend):
    """Slide calls send only that slide's text, never pictures or the whole deck."""
    convert_file(sample_pptx, tmp_path / "out", describer=make_describer(fake_backend))
    for prompt, image in fake_backend.calls:
        if image is None:
            assert "Slide text:" in prompt
            assert sum(t in prompt for t in ("Intro to LLMs", "Model", "Grouped")) == 1


def test_llm_failure_fails_the_deck_and_writes_nothing(sample_pptx, tmp_path):
    class Boom:
        def complete(self, *a, **k):
            raise RuntimeError("bad credentials")

    out = tmp_path / "out"
    results = convert_tree(sample_pptx, out, describer=make_describer(Boom()))
    assert isinstance(results[0][1], RuntimeError)
    assert not (out / "deck.md").exists()


def test_convert_tree_mirrors_layout_and_isolates_failures(sample_pptx, tmp_path):
    src = tmp_path / "src" / "Lesson-01"
    src.mkdir(parents=True)
    (src / "a.pptx").write_bytes(sample_pptx.read_bytes())
    (src / "UPPER.PPTX").write_bytes(sample_pptx.read_bytes())
    (src / "~$lock.pptx").write_text("office lock file")
    (src / "broken.pptx").write_text("not a zip")
    results = convert_tree(tmp_path / "src", tmp_path / "out")
    by_name = {p.name: err for p, err in results}
    assert set(by_name) == {"a.pptx", "UPPER.PPTX", "broken.pptx"}
    assert by_name["a.pptx"] is None and by_name["UPPER.PPTX"] is None
    assert by_name["broken.pptx"] is not None
    assert (tmp_path / "out" / "Lesson-01" / "a.md").exists()
