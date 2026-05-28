from __future__ import annotations

import logging
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class Metrics:
    processed: int = 0
    spam: int = 0
    safe: int = 0
    suspicious: int = 0
    route_counts: Counter[str] = field(default_factory=Counter)
    latencies_ms: list[int] = field(default_factory=list)
    confidence_buckets: Counter[str] = field(default_factory=Counter)

    def record(self, route: str, verdict: str, confidence: float, latency_ms: int) -> None:
        self.processed += 1
        if verdict == "spam":
            self.spam += 1
        elif verdict == "safe":
            self.safe += 1
        else:
            self.suspicious += 1
        self.route_counts[route] += 1
        self.latencies_ms.append(latency_ms)
        bucket = f"{int(confidence * 10) / 10:.1f}"
        self.confidence_buckets[bucket] += 1
        logger.info("metrics route=%s verdict=%s confidence=%.3f latency_ms=%s", route, verdict, confidence, latency_ms)

    def snapshot(self) -> dict[str, object]:
        avg_latency = sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0
        return {
            "processed": self.processed,
            "spam_ratio": self.spam / self.processed if self.processed else 0.0,
            "agent_vs_fast_path": dict(self.route_counts),
            "avg_latency_ms": avg_latency,
            "confidence_distribution": dict(self.confidence_buckets),
        }


metrics = Metrics()


@contextmanager
def latency_timer() -> Iterator[callable]:
    start = time.perf_counter()
    yield lambda: int((time.perf_counter() - start) * 1000)
