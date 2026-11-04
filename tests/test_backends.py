import base64
from types import SimpleNamespace

import pytest

from pptx_to_md.config import Settings
from pptx_to_md.llm import BedrockBackend, OpenAIBackend, RetryableError

PNG = b"\x89PNG-fake"


def test_bedrock_request_and_response():
    calls = []

    class Client:
        def converse(self, **kwargs):
            calls.append(kwargs)
            return {
                "output": {"message": {"content": [{"text": "hi "}, {"text": "there"}]}},
                "usage": {"inputTokens": 7, "outputTokens": 3},
                "metrics": {"latencyMs": 42},
            }

    backend = BedrockBackend(Settings(provider="bedrock"), client=Client())
    result = backend.complete("prompt", (PNG, "png"), 100)
    assert (result.text, result.input_tokens, result.output_tokens, result.latency_ms) == ("hi there", 7, 3, 42)
    sent = calls[0]
    assert sent["modelId"] == "us.amazon.nova-2-lite-v1:0"
    assert sent["messages"][0]["content"][0] == {"image": {"format": "png", "source": {"bytes": PNG}}}
    assert sent["messages"][0]["content"][1] == {"text": "prompt"}


def test_bedrock_throttling_is_retryable_and_other_errors_are_not():
    from botocore.exceptions import ClientError

    def failing(code):
        class Client:
            def converse(self, **kwargs):
                raise ClientError({"Error": {"Code": code, "Message": "x"}}, "Converse")

        return BedrockBackend(Settings(provider="bedrock"), client=Client())

    with pytest.raises(RetryableError):
        failing("ThrottlingException").complete("p", None, 10)
    with pytest.raises(ClientError):
        failing("AccessDeniedException").complete("p", None, 10)


def test_openai_request_and_response():
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content="answer")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message)],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=5),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    backend = OpenAIBackend(Settings(provider="openai"), client=client)
    result = backend.complete("prompt", (PNG, "png"), 100)
    assert (result.text, result.input_tokens, result.output_tokens) == ("answer", 11, 5)
    sent = calls[0]
    assert sent["model"] == "gpt-4o-mini"
    parts = sent["messages"][0]["content"]
    assert parts[0]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert parts[1] == {"type": "text", "text": "prompt"}


def test_openai_rate_limit_is_retryable():
    import openai

    try:  # the HTTP library depends on the installed openai version
        import httpx2 as httpx
    except ImportError:
        import httpx

    class Completions:
        def create(self, **kwargs):
            request = httpx.Request("POST", "http://x")
            raise openai.RateLimitError("slow", response=httpx.Response(429, request=request), body=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    with pytest.raises(RetryableError):
        OpenAIBackend(Settings(provider="openai"), client=client).complete("p", None, 10)


def test_openai_without_key_is_a_clear_error():
    from pptx_to_md.config import ConfigError

    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        OpenAIBackend(Settings(provider="openai"))
    # local servers (Ollama, LM Studio) need no key
    OpenAIBackend(Settings(provider="openai", base_url="http://localhost:11434/v1"))
