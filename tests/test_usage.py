import pytest

from pptx_to_md.config import Settings
from pptx_to_md.converter import convert_file
from pptx_to_md.llm import MAX_ATTEMPTS, Completion, LLMDescriber, RetryableError
from pptx_to_md.usage import Pricing, UsageTracker, format_summary


def test_pricing_cost():
    assert round(Pricing(0.33, 2.75).cost(1_000_000, 1_000_000), 4) == 3.08


def test_tracker_totals_kinds_and_throttles():
    t = UsageTracker(Pricing(1.0, 2.0))
    t.record_call("image", 1000, 100, 200)
    t.record_call("slide", 500, 50, 100)
    t.record_throttle("slide")
    t.record_failure("slide")
    snap = t.snapshot()
    assert snap["totals"]["calls"] == 2
    assert snap["totals"]["input_tokens"] == 1500
    assert snap["totals"]["throttled"] == 1 and snap["totals"]["failed"] == 1
    assert snap["by_kind"]["image"]["calls"] == 1
    assert snap["totals"]["estimated_cost_usd"] == round((1500 * 1 + 150 * 2) / 1e6, 6)
    assert "calls=2" in format_summary(snap) and "estimated_cost" in format_summary(snap)


def test_no_prices_means_no_cost():
    t = UsageTracker()
    t.record_call("image", 10, 10, 1)
    snap = t.snapshot()
    assert snap["totals"]["estimated_cost_usd"] is None
    assert "estimated_cost" not in format_summary(snap)


def test_per_deck_usage_is_delta(sample_pptx, tmp_path, fake_backend):
    describer = LLMDescriber(Settings(provider="bedrock"), backend=fake_backend)
    convert_file(sample_pptx, tmp_path / "a", describer=describer)
    convert_file(sample_pptx, tmp_path / "b", describer=describer)
    total = describer.usage.snapshot()["totals"]
    deck = describer.usage.decks["deck.pptx"]["totals"]
    assert deck["calls"] == total["calls"] // 2
    assert deck["input_tokens"] == 100 * deck["calls"]
    assert total["calls"] == len(fake_backend.calls)


class Flaky:
    def __init__(self, failures):
        self.failures = failures

    def complete(self, prompt, image, max_tokens):
        if self.failures:
            self.failures -= 1
            raise RetryableError("throttled")
        return Completion("fine", 1, 1, 1)


def test_retryable_error_is_retried_and_counted(monkeypatch):
    monkeypatch.setattr("pptx_to_md.llm.time.sleep", lambda s: None)
    describer = LLMDescriber(Settings(provider="bedrock"), backend=Flaky(1))
    assert describer.describe_slide(1, "text", []) == "fine"
    totals = describer.usage.snapshot()["totals"]
    assert totals["throttled"] == 1 and totals["calls"] == 1 and totals["failed"] == 0


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("pptx_to_md.llm.time.sleep", lambda s: None)
    describer = LLMDescriber(Settings(provider="bedrock"), backend=Flaky(10_000))
    with pytest.raises(RetryableError):
        describer.describe_slide(1, "text", [])
    totals = describer.usage.snapshot()["totals"]
    assert totals["failed"] == 1 and totals["throttled"] == MAX_ATTEMPTS - 1
