"""Request timing and small caches for the API.

Server-Timing: every response carries how long the request took in total and
how much of that was spent in each backing service, so a slow request can be
traced without a profiler:

    Server-Timing: total;dur=41.2, dynamodb;dur=18.0, healthimaging;dur=0, s3;dur=9.4, auth;dur=0.3

The providers are wrapped in Timed proxies (create_app does it), which add the
time of each call to the request's accumulator. Time spent in a background task
after the response is sent is not counted. Calls made from a worker thread the
request started are counted only if the thread runs inside the request's
context (copy_context().run); none of the request paths in core/api.py needs it.

TTLCache: a small thread-safe cache with an expiry and a size bound.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import contextvars
import functools
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

SERVICES = ("dynamodb", "healthimaging", "s3", "auth")

_current: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar("timings", default=None)


def begin() -> tuple[dict[str, float], contextvars.Token]:
    acc = {s: 0.0 for s in SERVICES}
    return acc, _current.set(acc)


def end(token: contextvars.Token) -> None:
    _current.reset(token)


def server_timing(total_ms: float, acc: dict[str, float]) -> str:
    parts = [f"total;dur={total_ms:.1f}"] + [f"{s};dur={acc.get(s, 0.0):.1f}" for s in SERVICES]
    return ", ".join(parts)


class Timed:
    """Delegates to `target`; every method call adds its duration to `service`
    in the current request's accumulator. Attributes that are not callable pass
    through, so isinstance-free code (hasattr, getattr) keeps working."""

    def __init__(self, target: Any, service: str,
                 after: dict[str, Callable[..., None]] | None = None):
        """after: {method name: hook}, called with the method's arguments once
        the method has returned (create_app drops its caches on a table write)."""
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_service", service)
        object.__setattr__(self, "_after", after or {})

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        if not callable(attr):
            return attr

        hook = self._after.get(name)

        @functools.wraps(attr)
        def call(*a, **k):
            acc = _current.get()
            t = time.perf_counter()
            try:
                out = attr(*a, **k)
            finally:
                if acc is not None:
                    acc[self._service] += (time.perf_counter() - t) * 1000
            if hook is not None:
                hook(*a, **k)
            return out

        return call

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target, name, value)


class TTLCache:
    """key -> value for `ttl` seconds, at most `size` entries (oldest out)."""

    def __init__(self, ttl: float, size: int = 256, clock: Callable[[], float] = time.monotonic):
        self.ttl, self.size, self.clock = ttl, size, clock
        self._d: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            hit = self._d.get(key)
            if hit is None:
                return default
            if self.clock() - hit[0] > self.ttl:
                del self._d[key]
                return default
            self._d.move_to_end(key)
            return hit[1]

    def put(self, key: Any, value: Any) -> Any:
        with self._lock:
            self._d[key] = (self.clock(), value)
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)
        return value

    def drop(self, key: Any) -> None:
        with self._lock:
            self._d.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def drop_where(self, pred: Callable[[Any], bool]) -> None:
        with self._lock:
            for k in [k for k in self._d if pred(k)]:
                del self._d[k]
