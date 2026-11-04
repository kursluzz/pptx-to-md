"""LLM access: prompts, retry logic and one backend per provider (Bedrock, OpenAI-compatible).

A backend only knows how to send one prompt (optionally with one picture) and return the text
plus token counts. Everything else (prompts, parsing, retries, usage accounting) is shared.
"""

from __future__ import annotations

import base64
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Protocol

from .config import ConfigError, Settings
from .model import ImageInfo
from .usage import Pricing, UsageTracker

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 8

IMAGE_PROMPT = """You are analysing a picture taken from a slide of a technical presentation.
1. Transcribe ALL text visible in the picture exactly as written (titles, labels, code, numbers, captions), keeping line breaks. If there is no text, write NONE.
2. Describe the picture in 1-3 sentences: what it shows and what it communicates.

Answer in exactly this format and nothing else:
<text>
transcribed text or NONE
</text>
<description>
description
</description>"""

SLIDE_PROMPT = """Below is the content of slide {number} of a technical presentation.

Slide text:
{text}

{images}Write a concise description (2-4 sentences) of what this slide shows and teaches. Do not copy the text verbatim. Reply with the description only."""

_TAG_RE = {tag: re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.DOTALL) for tag in ("text", "description")}


class RetryableError(Exception):
    """Raised by a backend for throttling / transient failures that are worth retrying."""


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class Backend(Protocol):
    def complete(self, prompt: str, image: tuple[bytes, str] | None, max_tokens: int) -> Completion:
        """Send `prompt` (plus `image` = (bytes, format) if given). May raise RetryableError."""
        ...


# --------------------------------------------------------------------------- backends
class BedrockBackend:
    """Amazon Bedrock Converse API (Amazon Nova by default). Credentials: standard AWS chain."""

    RETRYABLE = {
        "ThrottlingException",
        "ServiceUnavailableException",
        "ModelTimeoutException",
        "InternalServerException",
    }

    def __init__(self, settings: Settings, client=None) -> None:
        self.model_id = settings.model_id
        self.client = client or self._make_client(settings)

    @staticmethod
    def _make_client(settings: Settings):
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise ConfigError("the 'bedrock' provider needs boto3: pip install 'pptx-to-md[bedrock]'") from None
        session = boto3.Session(
            profile_name=settings.aws_profile,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
        )
        return session.client(
            "bedrock-runtime",
            region_name=settings.region,
            config=Config(retries={"max_attempts": 1}, read_timeout=120),  # we retry ourselves
        )

    def complete(self, prompt, image, max_tokens):
        from botocore.exceptions import BotoCoreError, ClientError

        content: list[dict] = []
        if image is not None:
            blob, fmt = image
            content.append({"image": {"format": fmt, "source": {"bytes": blob}}})
        content.append({"text": prompt})
        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": content}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code", "") in self.RETRYABLE:
                raise RetryableError(str(exc)) from exc
            raise
        except BotoCoreError as exc:  # connection resets, read timeouts, ...
            if type(exc).__name__ in {
                "ReadTimeoutError",
                "ConnectTimeoutError",
                "EndpointConnectionError",
                "ConnectionClosedError",
            }:
                raise RetryableError(str(exc)) from exc
            raise
        usage = response.get("usage", {})
        blocks = response["output"]["message"]["content"]
        return Completion(
            text="".join(b["text"] for b in blocks if "text" in b),
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            latency_ms=response.get("metrics", {}).get("latencyMs", 0),
        )


class OpenAIBackend:
    """OpenAI Chat Completions API, or any compatible server (OpenRouter, Ollama, LM Studio, vLLM...)."""

    def __init__(self, settings: Settings, client=None) -> None:
        self.model_id = settings.model_id
        self.client = client or self._make_client(settings)

    @staticmethod
    def _make_client(settings: Settings):
        try:
            import openai
        except ImportError:
            raise ConfigError(
                "the 'openai' provider needs the openai package: pip install 'pptx-to-md[openai]'"
            ) from None
        local = not settings.base_url.startswith("https://api.openai.com")
        api_key = settings.api_key or ("not-needed" if local else None)
        if not api_key:
            raise ConfigError("no API key for the 'openai' provider: set OPENAI_API_KEY or run 'pptx-to-md configure'")
        return openai.OpenAI(api_key=api_key, base_url=settings.base_url, max_retries=0, timeout=120)

    def complete(self, prompt, image, max_tokens):
        import openai

        content: list[dict] = []
        if image is not None:
            blob, fmt = image
            url = f"data:image/{fmt};base64,{base64.b64encode(blob).decode('ascii')}"
            content.append({"type": "image_url", "image_url": {"url": url}})
        content.append({"type": "text", "text": prompt})
        started = time.monotonic()
        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": content}],
                max_tokens=max_tokens,
                temperature=0.2,
            )
        except (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
        ) as exc:
            raise RetryableError(str(exc)) from exc
        usage = response.usage
        return Completion(
            text=(response.choices[0].message.content or "") if response.choices else "",
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=(time.monotonic() - started) * 1000,
        )


def make_backend(settings: Settings) -> Backend:
    if settings.provider == "bedrock":
        return BedrockBackend(settings)
    if settings.provider == "openai":
        return OpenAIBackend(settings)
    raise ConfigError("no LLM provider configured; run 'pptx-to-md configure'")


# --------------------------------------------------------------------------- describer
class LLMDescriber:
    """Picture transcription/description and slide descriptions on top of any backend.

    Each call is minimal: one picture (plus the fixed prompt) for images, and only the text of
    one slide (plus short image summaries) for slides. The deck as a whole is never sent.
    """

    def __init__(self, settings: Settings, backend: Backend | None = None, usage: UsageTracker | None = None) -> None:
        self.model_id = settings.model_id
        self.backend = backend or make_backend(settings)
        pricing = None
        if settings.price_input_per_million is not None and settings.price_output_per_million is not None:
            pricing = Pricing(settings.price_input_per_million, settings.price_output_per_million)
        self.usage = usage or UsageTracker(pricing=pricing)

    # Describer protocol -------------------------------------------------
    def describe_image(self, blob: bytes, fmt: str) -> ImageInfo:
        raw = self._complete(IMAGE_PROMPT, (blob, fmt), max_tokens=2048, kind="image")
        text = _extract_tag(raw, "text")
        description = _extract_tag(raw, "description")
        if text.strip().upper() == "NONE":
            text = ""
        if not text and not description:
            description = raw.strip()  # model ignored the format; keep whatever it said
        return ImageInfo(text=text.strip(), description=description.strip())

    def describe_slide(self, number: int, slide_text: str, image_infos: list[ImageInfo]) -> str:
        images = ""
        if image_infos:
            lines = [
                f"- Image {i}: {info.text or info.description or 'no text'}" for i, info in enumerate(image_infos, 1)
            ]
            images = "Images on the slide:\n" + "\n".join(lines) + "\n\n"
        prompt = SLIDE_PROMPT.format(number=number, text=slide_text or "(no text)", images=images)
        return self._complete(prompt, None, max_tokens=1024, kind="slide").strip()

    def ping(self) -> None:
        """Cheap request used by `pptx-to-md configure` to verify credentials and model access."""
        self._complete("Reply with the single word OK.", None, max_tokens=16, kind="ping")

    # internals ------------------------------------------------------------
    def _complete(self, prompt: str, image, max_tokens: int, kind: str) -> str:
        """Retries throttling/transient errors with backoff; after MAX_ATTEMPTS (or on any other
        error) it raises, so a deck fails instead of silently losing data."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                result = self.backend.complete(prompt, image, max_tokens)
            except RetryableError as exc:
                if attempt == MAX_ATTEMPTS:
                    self.usage.record_failure(kind)
                    raise
                self.usage.record_throttle(kind)
                delay = min(60.0, 2.0**attempt) * (0.5 + random.random())
                log.warning(
                    "LLM busy (%s); attempt %d/%d, retrying in %.1fs", str(exc)[:120], attempt, MAX_ATTEMPTS, delay
                )
                time.sleep(delay)
                continue
            except Exception:
                self.usage.record_failure(kind)
                raise
            self.usage.record_call(kind, result.input_tokens, result.output_tokens, result.latency_ms)
            log.debug(
                "%s call: in=%s out=%s latency=%sms", kind, result.input_tokens, result.output_tokens, result.latency_ms
            )
            return result.text
        raise RuntimeError("unreachable")


def _extract_tag(raw: str, tag: str) -> str:
    match = _TAG_RE[tag].search(raw)
    return match.group(1) if match else ""
