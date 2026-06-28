"""
Observability: structured logging, Prometheus metrics, Sentry error tracking.

Call `configure_observability(settings)` once at app startup. After that:
  - All stdlib `logging` calls are routed through structlog.
  - The ASGI `prometheus_metrics_middleware` counts requests and latencies.
  - Sentry captures unhandled exceptions when SENTRY_DSN is set.

Nothing here hard-depends on structlog / prometheus_client / sentry_sdk being
installed. Missing packages produce a WARNING and graceful fallback.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("visiblehand.observability")

# ── Prometheus counters (populated lazily) ────────────────────────────────────
_request_counter = None
_request_latency = None
_score_counter = None
_prometheus_ok = False


def _init_prometheus() -> bool:
    global _request_counter, _request_latency, _score_counter, _prometheus_ok
    try:
        from prometheus_client import Counter, Histogram
        _request_counter = Counter(
            "visiblehand_http_requests_total",
            "Total HTTP requests",
            ["method", "path", "status"],
        )
        _request_latency = Histogram(
            "visiblehand_http_request_duration_seconds",
            "HTTP request latency",
            ["method", "path"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
        )
        _score_counter = Counter(
            "visiblehand_scores_computed_total",
            "Country scores computed",
            ["country"],
        )
        _prometheus_ok = True
        return True
    except ImportError:
        return False


def record_request(method: str, path: str, status: int, duration: float) -> None:
    if not _prometheus_ok:
        return
    try:
        _request_counter.labels(method=method, path=path, status=str(status)).inc()
        _request_latency.labels(method=method, path=path).observe(duration)
    except Exception:
        pass


def record_score(country: str) -> None:
    if not _prometheus_ok:
        return
    try:
        _score_counter.labels(country=country).inc()
    except Exception:
        pass


# ── Structlog ─────────────────────────────────────────────────────────────────

def _configure_structlog(json_logs: bool) -> bool:
    try:
        import structlog

        processors: list = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
        ]
        if json_logs:
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        return True
    except ImportError:
        return False


# ── Sentry ────────────────────────────────────────────────────────────────────

def _configure_sentry(dsn: str, environment: str, release: str) -> bool:
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=0.1,
            profiles_sample_rate=0.0,
            send_default_pii=False,
        )
        log.info("Sentry initialised (env=%s)", environment)
        return True
    except ImportError:
        log.warning("sentry-sdk not installed — error tracking disabled")
        return False


# ── Main setup call ───────────────────────────────────────────────────────────

def configure_observability(settings) -> None:
    """Wire up all observability backends based on settings."""
    if _configure_structlog(getattr(settings, "structured_logging", False)):
        log.info("structlog configured (json=%s)", getattr(settings, "structured_logging", False))
    else:
        log.info("structlog not installed — using stdlib logging")

    if getattr(settings, "prometheus_enabled", True):
        if _init_prometheus():
            log.info("Prometheus metrics enabled")
        else:
            log.warning("prometheus_client not installed — /metrics disabled")

    _configure_sentry(
        dsn=getattr(settings, "sentry_dsn", ""),
        environment=getattr(settings, "environment", "development"),
        release=f"visiblehand@{getattr(settings, '__version__', '0.3.0')}",
    )


# ── ASGI middleware ───────────────────────────────────────────────────────────

class PrometheusMiddleware:
    """Thin ASGI middleware that records per-request metrics."""

    def __init__(self, app: "ASGIApp") -> None:
        self.app = app

    async def __call__(self, scope: "Scope", receive: "Receive", send: "Send") -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500

        async def send_with_capture(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_capture)
        finally:
            duration = time.perf_counter() - start
            path = scope.get("path", "")
            method = scope.get("method", "")
            # Normalise parameterised paths to avoid cardinality explosion
            normalised = _normalise_path(path)
            record_request(method, normalised, status_code, duration)


def _normalise_path(path: str) -> str:
    """Replace path parameters with placeholders for metric label cardinality."""
    import re
    path = re.sub(r"/risk/[A-Z]{2}/", "/risk/{code}/", path)
    path = re.sub(r"/risk/[A-Z]{2}$", "/risk/{code}", path)
    path = re.sub(r"/governance/[A-Z]{2}", "/governance/{code}", path)
    path = re.sub(r"/dashboard/[A-Z]{2}", "/dashboard/{code}", path)
    return path
