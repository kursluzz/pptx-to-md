"""Interactive `pptx-to-md configure`: pick an LLM provider and store the settings once."""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable
from pathlib import Path

from .config import (
    DEFAULT_MODELS,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_REGION,
    ConfigError,
    config_path,
    load_settings,
    read_config_file,
    write_config_file,
)

Ask = Callable[[str], str]


def _choose(ask: Ask, question: str, options: list[tuple[str, str]], default: str) -> str:
    print(question)
    for key, label in options:
        print(f"  {key}) {label}")
    valid = {key for key, _ in options}
    while True:
        answer = ask(f"Choice [{default}]: ").strip() or default
        if answer in valid:
            return answer
        print(f"Please enter one of: {', '.join(sorted(valid))}")


def _text(ask: Ask, label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return ask(f"{label}{suffix}: ").strip() or default


def run_wizard(ask: Ask = input, ask_secret: Ask | None = None, path: Path | None = None) -> Path:
    """Ask the questions, write the config file and return its path."""
    ask_secret = ask_secret or getpass.getpass
    path = path or config_path()
    data = read_config_file(path)  # keep settings of the provider we are not editing

    print("pptx-to-md: LLM setup (used with `pptx-to-md --llm`)\n")
    provider = {
        "1": "bedrock",
        "2": "openai",
    }[
        _choose(
            ask,
            "Which LLM provider do you want to use?",
            [
                ("1", "Amazon Bedrock (Amazon Nova by default) - uses AWS credentials"),
                ("2", "OpenAI, or any OpenAI-compatible API (OpenRouter, Ollama, LM Studio, ...) - uses an API key"),
            ],
            "1" if data.get("provider") != "openai" else "2",
        )
    ]
    section: dict = dict(data.get(provider, {}))

    if provider == "bedrock":
        mode = _choose(
            ask,
            "\nHow should pptx-to-md authenticate to AWS?",
            [
                ("1", "Use my existing AWS setup (environment variables, ~/.aws, SSO, IAM role) - recommended"),
                ("2", "Store an AWS access key in the config file"),
            ],
            "1",
        )
        section["region"] = _text(ask, "AWS region", section.get("region", DEFAULT_REGION))
        section["model"] = _text(
            ask, "Bedrock model or inference profile id", section.get("model", DEFAULT_MODELS["bedrock"])
        )
        if mode == "1":
            profile = _text(ask, "AWS profile name (empty = default credential chain)", section.get("profile", ""))
            if profile:
                section["profile"] = profile
            else:
                section.pop("profile", None)
            for key in ("access_key_id", "secret_access_key", "session_token"):
                section.pop(key, None)
        else:
            section["access_key_id"] = _text(ask, "AWS access key id", section.get("access_key_id", ""))
            secret = ask_secret("AWS secret access key (input hidden): ").strip()
            if secret:
                section["secret_access_key"] = secret
            token = ask_secret("AWS session token (optional, input hidden): ").strip()
            if token:
                section["session_token"] = token
            section.pop("profile", None)
    else:
        section["base_url"] = _text(ask, "\nAPI base URL", section.get("base_url", DEFAULT_OPENAI_BASE_URL))
        section["model"] = _text(
            ask, "Model name (must support image input)", section.get("model", DEFAULT_MODELS["openai"])
        )
        print("API key: leave empty to read it from the OPENAI_API_KEY environment variable instead.")
        key = ask_secret("API key (input hidden): ").strip()
        if key:
            section["api_key"] = key

    data["provider"] = provider
    data[provider] = section
    written = write_config_file(data, path)
    print(f"\nSaved to {written} (readable only by you).")

    if _text(ask, "Test the connection now? (y/n)", "y").lower().startswith("y"):
        _test_connection(path)
    print("\nDone. Convert with:  pptx-to-md deck.pptx --llm")
    return written


def _test_connection(path: Path) -> None:
    from .llm import LLMDescriber

    try:
        LLMDescriber(load_settings(config_file=path)).ping()
    except Exception as exc:
        print(
            f"Connection test FAILED: {exc}\nThe settings were saved anyway; run `pptx-to-md configure` to change them."
        )
    else:
        print("Connection OK.")


def show_config(path: Path | None = None) -> str:
    """Config contents with secrets masked."""
    path = path or config_path()
    if not path.is_file():
        return f"No config file yet ({path}). Run: pptx-to-md configure"
    secret_keys = {"api_key", "secret_access_key", "session_token", "access_key_id"}
    out = [f"# {path}"]
    for name, value in read_config_file(path).items():
        if isinstance(value, dict):
            out.append(f"[{name}]")
            out += [f"{k} = {'********' if k in secret_keys else value[k]!r}" for k in value]
        else:
            out.append(f"{name} = {value!r}")
    return "\n".join(out)


def require_tty() -> None:
    if not sys.stdin.isatty():
        raise ConfigError(
            "`configure` is interactive; set PPTX_TO_MD_PROVIDER and the provider's credentials in the environment instead"
        )
