import os
import stat
import sys

import pytest

from pptx_to_md.config import ConfigError, load_settings, read_config_file, write_config_file
from pptx_to_md.configure import run_wizard, show_config


def scripted(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_defaults_have_no_provider():
    s = load_settings()
    assert s.provider is None and s.workers == 2


def test_precedence_cli_over_env_over_file(tmp_path, monkeypatch):
    cfg = tmp_path / "c.toml"
    write_config_file({"provider": "bedrock", "bedrock": {"model": "file-model", "region": "eu-west-1"}}, cfg)
    assert load_settings(config_file=cfg).model_id == "file-model"
    assert load_settings(config_file=cfg).region == "eu-west-1"
    monkeypatch.setenv("PPTX_TO_MD_MODEL", "env-model")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    s = load_settings(config_file=cfg)
    assert s.model_id == "env-model" and s.region == "us-west-2"
    assert load_settings(config_file=cfg, model="cli-model").model_id == "cli-model"
    assert load_settings(config_file=cfg, provider="openai").provider == "openai"


def test_env_aws_keys_win_over_file_keys(tmp_path, monkeypatch):
    cfg = tmp_path / "c.toml"
    write_config_file({"provider": "bedrock", "bedrock": {"access_key_id": "FILE", "secret_access_key": "s"}}, cfg)
    assert load_settings(config_file=cfg).aws_access_key_id == "FILE"
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ENV")
    assert load_settings(config_file=cfg).aws_access_key_id is None  # boto3 then uses the environment


def test_openai_env_key_wins(tmp_path, monkeypatch):
    cfg = tmp_path / "c.toml"
    write_config_file({"provider": "openai", "openai": {"api_key": "file-key"}}, cfg)
    assert load_settings(config_file=cfg).api_key == "file-key"
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert load_settings(config_file=cfg).api_key == "env-key"


@pytest.mark.parametrize(
    "kwargs, env", [({"provider": "nope"}, {}), ({"workers": 0}, {}), ({}, {"PPTX_TO_MD_WORKERS": "x"})]
)
def test_invalid_values_raise_config_error(monkeypatch, kwargs, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError):
        load_settings(**kwargs)


def test_broken_config_file_is_a_clear_error(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("this is = not [valid")
    with pytest.raises(ConfigError, match="bad.toml"):
        read_config_file(bad)


def test_write_roundtrip_with_special_characters(tmp_path):
    cfg = tmp_path / "c.toml"
    data = {"provider": "openai", "openai": {"api_key": 'a"b\\c', "model": "m"}}
    write_config_file(data, cfg)
    assert read_config_file(cfg) == data


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_config_file_is_private(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("x = 1")
    cfg.chmod(0o644)
    write_config_file({"provider": "openai"}, cfg)
    assert stat.S_IMODE(os.stat(cfg).st_mode) == 0o600


def test_wizard_openai(tmp_path):
    cfg = tmp_path / "c.toml"
    run_wizard(
        ask=scripted(["2", "", "gpt-4o", "n"]),  # provider, base url (default), model, no connection test
        ask_secret=lambda p: "sk-secret",
        path=cfg,
    )
    s = load_settings(config_file=cfg)
    assert (s.provider, s.model_id, s.api_key) == ("openai", "gpt-4o", "sk-secret")
    shown = show_config(cfg)
    assert "sk-secret" not in shown and "********" in shown


def test_wizard_bedrock_profile_keeps_other_provider(tmp_path):
    cfg = tmp_path / "c.toml"
    write_config_file({"provider": "openai", "openai": {"api_key": "keep-me"}}, cfg)
    run_wizard(ask=scripted(["1", "1", "eu-west-1", "", "my-profile", "n"]), ask_secret=lambda p: "", path=cfg)
    s = load_settings(config_file=cfg)
    assert (s.provider, s.region, s.aws_profile) == ("bedrock", "eu-west-1", "my-profile")
    assert read_config_file(cfg)["openai"]["api_key"] == "keep-me"
