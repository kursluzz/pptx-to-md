"""Settings: command line > environment variables > config file > defaults.

The config file is TOML, created by ``pptx-to-md configure``:

    ~/.config/pptx-to-md/config.toml        (Linux / macOS, honours XDG_CONFIG_HOME)
    %APPDATA%\\pptx-to-md\\config.toml       (Windows)

Set ``PPTX_TO_MD_CONFIG`` to use another path.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROVIDERS = ("bedrock", "openai")

DEFAULT_MODELS = {
    "bedrock": "us.amazon.nova-2-lite-v1:0",
    "openai": "gpt-4o-mini",
}
DEFAULT_REGION = "us-east-1"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_WORKERS = 2


class ConfigError(ValueError):
    """Invalid or missing configuration; the message is meant for the end user."""


@dataclass(frozen=True)
class Settings:
    provider: str | None = None
    model: str | None = None
    workers: int = DEFAULT_WORKERS
    # bedrock
    region: str = DEFAULT_REGION
    aws_profile: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    # openai-compatible
    api_key: str | None = None
    base_url: str = DEFAULT_OPENAI_BASE_URL
    # optional, for the cost estimate only (USD per 1M tokens)
    price_input_per_million: float | None = None
    price_output_per_million: float | None = None

    @property
    def model_id(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.provider or "", "")


def config_path() -> Path:
    override = os.environ.get("PPTX_TO_MD_CONFIG")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "pptx-to-md" / "config.toml"


def read_config_file(path: Path | None = None) -> dict:
    path = path or config_path()
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def write_config_file(data: dict, path: Path | None = None) -> Path:
    """Write the config (top-level scalars, then one table per provider) readable by the owner only."""
    path = path or config_path()
    lines = [f"{k} = {_toml_value(v)}" for k, v in data.items() if not isinstance(v, dict)]
    for name, table in data.items():
        if isinstance(table, dict) and table:
            lines += ["", f"[{name}]"] + [f"{k} = {_toml_value(v)}" for k, v in table.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with contextlib.suppress(OSError):
        path.chmod(0o600)  # file may have existed with looser permissions
    return path


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None


def load_settings(
    *,
    provider: str | None = None,
    model: str | None = None,
    workers: int | None = None,
    config_file: Path | None = None,
    use_config_file: bool = True,
) -> Settings:
    """Resolve settings. Arguments are the command line overrides; ``None`` means not given."""
    file = read_config_file(config_file) if use_config_file else {}
    env = os.environ

    provider = provider or env.get("PPTX_TO_MD_PROVIDER") or file.get("provider")
    if provider is not None and provider not in PROVIDERS:
        raise ConfigError(f"unknown provider {provider!r}; choose one of: {', '.join(PROVIDERS)}")
    section = file.get(provider or "", {}) if isinstance(file.get(provider or ""), dict) else {}

    if workers is None:
        raw = env.get("PPTX_TO_MD_WORKERS")
        try:
            workers = int(raw) if raw else int(file.get("workers", DEFAULT_WORKERS))
        except ValueError:
            raise ConfigError(f"workers must be an integer, got {raw!r}") from None
    if workers < 1:
        raise ConfigError("workers must be >= 1")

    # explicit AWS credentials in the environment win over keys stored in the config file
    file_keys_ok = not env.get("AWS_ACCESS_KEY_ID")

    prices = file.get("prices", {}) if isinstance(file.get("prices"), dict) else {}
    price_in = _env_float("PPTX_TO_MD_PRICE_INPUT_PER_1M")
    price_out = _env_float("PPTX_TO_MD_PRICE_OUTPUT_PER_1M")

    return Settings(
        provider=provider,
        model=model or env.get("PPTX_TO_MD_MODEL") or section.get("model"),
        workers=workers,
        region=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or section.get("region") or DEFAULT_REGION
        if provider == "bedrock"
        else DEFAULT_REGION,
        aws_profile=env.get("AWS_PROFILE") or section.get("profile") if provider == "bedrock" else None,
        aws_access_key_id=section.get("access_key_id") if provider == "bedrock" and file_keys_ok else None,
        aws_secret_access_key=section.get("secret_access_key") if provider == "bedrock" and file_keys_ok else None,
        aws_session_token=section.get("session_token") if provider == "bedrock" and file_keys_ok else None,
        api_key=(env.get("OPENAI_API_KEY") or section.get("api_key")) if provider == "openai" else None,
        base_url=(env.get("OPENAI_BASE_URL") or section.get("base_url") or DEFAULT_OPENAI_BASE_URL)
        if provider == "openai"
        else DEFAULT_OPENAI_BASE_URL,
        price_input_per_million=price_in if price_in is not None else prices.get("input_per_million"),
        price_output_per_million=price_out if price_out is not None else prices.get("output_per_million"),
    )
