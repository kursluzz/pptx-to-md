import pptx_to_md.cli as cli
from pptx_to_md.config import write_config_file


def test_default_run_uses_no_llm(sample_pptx, tmp_path, capsys):
    assert cli.main([str(sample_pptx), "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "deck.md").exists()
    assert not (tmp_path / "out" / "llm_usage.json").exists()
    assert "LLM" not in capsys.readouterr().out


def test_llm_without_provider_in_non_interactive_mode_explains_how(sample_pptx, tmp_path, capsys):
    assert cli.main([str(sample_pptx), "-o", str(tmp_path / "out"), "--llm"]) == 2
    assert "pptx-to-md configure" in capsys.readouterr().err


def test_llm_run_with_fake_backend(sample_pptx, tmp_path, monkeypatch, fake_backend, capsys):
    monkeypatch.setenv("PPTX_TO_MD_PROVIDER", "bedrock")
    monkeypatch.setattr("pptx_to_md.llm.make_backend", lambda settings: fake_backend)
    out = tmp_path / "out"
    assert cli.main([str(sample_pptx), "-o", str(out), "--llm"]) == 0
    assert "Slide description" in (out / "deck.md").read_text(encoding="utf-8")
    assert (out / "llm_usage.json").exists()
    assert "input_tokens=" in capsys.readouterr().out


def test_empty_folder_is_an_error(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert cli.main([str(tmp_path / "empty"), "-o", str(tmp_path / "out")]) == 1


def test_configure_path_and_show(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "c.toml"
    monkeypatch.setenv("PPTX_TO_MD_CONFIG", str(cfg))
    assert cli.main(["configure", "--path"]) == 0
    assert str(cfg) in capsys.readouterr().out
    write_config_file({"provider": "openai", "openai": {"api_key": "sk-x"}}, cfg)
    assert cli.main(["configure", "--show"]) == 0
    out = capsys.readouterr().out
    assert "openai" in out and "sk-x" not in out
