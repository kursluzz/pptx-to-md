"""Thread-safe accounting of LLM calls: tokens, latency, retries, failures and estimated cost."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

_COUNTERS = ("calls", "input_tokens", "output_tokens", "latency_ms", "throttled", "failed")


@dataclass(frozen=True)
class Pricing:
    """USD per 1M tokens, supplied by the user (prices differ per model and change over time)."""

    input_per_million: float = 0.0
    output_per_million: float = 0.0

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_million + output_tokens * self.output_per_million) / 1_000_000


def _empty() -> dict:
    return {name: 0 for name in _COUNTERS}


@dataclass
class UsageTracker:
    pricing: Pricing | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _totals: dict = field(default_factory=_empty, repr=False)
    _by_kind: dict = field(default_factory=dict, repr=False)
    decks: dict = field(default_factory=dict)  # deck name -> usage snapshot (see record_deck)

    def record_call(self, kind: str, input_tokens: int, output_tokens: int, latency_ms: float) -> None:
        self._add(
            kind,
            {
                "calls": 1,
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "latency_ms": float(latency_ms),
            },
        )

    def record_throttle(self, kind: str) -> None:
        self._add(kind, {"throttled": 1})

    def record_failure(self, kind: str) -> None:
        self._add(kind, {"failed": 1})

    def _add(self, kind: str, values: dict) -> None:
        with self._lock:
            for name, value in values.items():
                self._totals[name] += value
                bucket = self._by_kind.setdefault(kind, _empty())
                bucket[name] += value

    def snapshot(self) -> dict:
        """Current totals, with per-kind breakdown and estimated cost."""
        with self._lock:
            totals = dict(self._totals)
            by_kind = {k: dict(v) for k, v in self._by_kind.items()}
        return _with_cost(totals, by_kind, self.pricing)

    def record_deck(self, name: str, before: dict, after: dict) -> dict:
        """Store the usage between two snapshots as the usage of one deck."""
        delta = diff(after, before)
        self.decks[name] = delta
        return delta


def diff(after: dict, before: dict) -> dict:
    totals = {k: after["totals"][k] - before["totals"][k] for k in _COUNTERS}
    by_kind = {}
    for kind, values in after["by_kind"].items():
        base = before["by_kind"].get(kind, _empty())
        by_kind[kind] = {k: values[k] - base.get(k, 0) for k in _COUNTERS}
    return _with_cost(totals, by_kind, _pricing_from(after))


def _pricing_from(snapshot: dict) -> Pricing | None:
    return Pricing(**snapshot["pricing"]) if snapshot.get("pricing") else None


def _with_cost(totals: dict, by_kind: dict, pricing: Pricing | None) -> dict:
    def finish(counters: dict) -> dict:
        counters = dict(counters)
        counters["estimated_cost_usd"] = (
            round(pricing.cost(counters["input_tokens"], counters["output_tokens"]), 6) if pricing else None
        )
        return counters

    return {
        "totals": finish(totals),
        "by_kind": {k: finish(v) for k, v in by_kind.items()},
        "pricing": (
            {"input_per_million": pricing.input_per_million, "output_per_million": pricing.output_per_million}
            if pricing
            else None
        ),
    }


def format_summary(usage: dict) -> str:
    t = usage["totals"]
    seconds = t["latency_ms"] / 1000

    def cost(c: dict) -> str:
        return f" estimated_cost=${c['estimated_cost_usd']:.4f}" if c["estimated_cost_usd"] is not None else ""

    lines = [
        f"calls={t['calls']} input_tokens={t['input_tokens']} output_tokens={t['output_tokens']} "
        f"throttled_retries={t['throttled']} failed={t['failed']} llm_time={seconds:.1f}s{cost(t)}"
    ]
    for kind, v in sorted(usage["by_kind"].items()):
        lines.append(
            f"  {kind}: calls={v['calls']} input_tokens={v['input_tokens']} output_tokens={v['output_tokens']}{cost(v)}"
        )
    return "\n".join(lines)
