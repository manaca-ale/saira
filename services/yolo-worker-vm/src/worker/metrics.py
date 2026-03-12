"""Prometheus metrics for SAIRA worker."""
from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from . import config

logger = logging.getLogger("worker.metrics")

_METRICS_SERVER_STARTED = False

WORKER_SCAN_CYCLES_TOTAL = Counter(
    "saira_worker_scan_cycles_total",
    "Total scan cycles executed by the worker.",
)

WORKER_IMAGES_PROCESSED_TOTAL = Counter(
    "saira_worker_images_processed_total",
    "Total images processed by the worker.",
)

WORKER_SCAN_ERRORS_TOTAL = Counter(
    "saira_worker_scan_errors_total",
    "Unhandled errors in worker scan loop.",
)

WORKER_LAST_CYCLE_IMAGES = Gauge(
    "saira_worker_last_cycle_images",
    "Number of images processed in the last completed cycle.",
)

GEMINI_CALLS_TOTAL = Counter(
    "saira_gemini_calls_total",
    "Total Gemini API calls performed by the worker.",
)

GEMINI_ERRORS_TOTAL = Counter(
    "saira_gemini_errors_total",
    "Total Gemini call failures.",
)

GEMINI_TIMEOUT_TOTAL = Counter(
    "saira_gemini_timeout_total",
    "Total Gemini timeout failures.",
)

GEMINI_PARSE_FAIL_TOTAL = Counter(
    "saira_gemini_parse_fail_total",
    "Total Gemini JSON/schema parse failures.",
)

GEMINI_INPUT_TOKENS_TOTAL = Counter(
    "saira_gemini_input_tokens_total",
    "Total Gemini input tokens consumed.",
)

GEMINI_OUTPUT_TOKENS_TOTAL = Counter(
    "saira_gemini_output_tokens_total",
    "Total Gemini output tokens consumed.",
)

GEMINI_COST_USD_TOTAL = Counter(
    "saira_gemini_estimated_cost_usd_total",
    "Estimated Gemini cumulative cost in USD.",
)

GEMINI_LATENCY_SECONDS = Histogram(
    "saira_gemini_latency_seconds",
    "Gemini call latency in seconds.",
    buckets=(0.25, 0.5, 1, 1.5, 2, 3, 5, 8, 13, 21, 34),
)

GEMINI_AVG_LATENCY_MS = Gauge(
    "saira_gemini_avg_latency_ms",
    "Average Gemini latency in milliseconds.",
)

GEMINI_LAST_INPUT_TOKENS = Gauge(
    "saira_gemini_last_input_tokens",
    "Input tokens from last successful Gemini response.",
)

GEMINI_LAST_OUTPUT_TOKENS = Gauge(
    "saira_gemini_last_output_tokens",
    "Output tokens from last successful Gemini response.",
)

GEMINI_LAST_ESTIMATED_COST_USD = Gauge(
    "saira_gemini_last_estimated_cost_usd",
    "Estimated USD cost for last successful Gemini response.",
)


def start_metrics_server() -> None:
    global _METRICS_SERVER_STARTED
    if _METRICS_SERVER_STARTED or not config.WORKER_METRICS_ENABLED:
        return
    try:
        start_http_server(addr=config.WORKER_METRICS_HOST, port=config.WORKER_METRICS_PORT)
    except OSError as exc:
        logger.warning("Failed to start Prometheus metrics server: %s", exc)
        return
    _METRICS_SERVER_STARTED = True
    logger.info(
        "Prometheus metrics enabled at http://%s:%s/metrics",
        config.WORKER_METRICS_HOST,
        config.WORKER_METRICS_PORT,
    )


def observe_scan_cycle(processed_images: int) -> None:
    WORKER_SCAN_CYCLES_TOTAL.inc()
    WORKER_LAST_CYCLE_IMAGES.set(max(0, int(processed_images)))
    if processed_images > 0:
        WORKER_IMAGES_PROCESSED_TOTAL.inc(int(processed_images))


def observe_scan_error() -> None:
    WORKER_SCAN_ERRORS_TOTAL.inc()


def observe_gemini_call() -> None:
    GEMINI_CALLS_TOTAL.inc()


def observe_gemini_success(
    *,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float,
) -> None:
    GEMINI_LATENCY_SECONDS.observe(max(0.0, float(latency_ms) / 1000.0))
    GEMINI_INPUT_TOKENS_TOTAL.inc(max(0, int(input_tokens)))
    GEMINI_OUTPUT_TOKENS_TOTAL.inc(max(0, int(output_tokens)))
    GEMINI_COST_USD_TOTAL.inc(max(0.0, float(estimated_cost_usd)))
    GEMINI_LAST_INPUT_TOKENS.set(max(0, int(input_tokens)))
    GEMINI_LAST_OUTPUT_TOKENS.set(max(0, int(output_tokens)))
    GEMINI_LAST_ESTIMATED_COST_USD.set(max(0.0, float(estimated_cost_usd)))


def observe_gemini_error(*, timeout: bool, parse_fail: bool) -> None:
    GEMINI_ERRORS_TOTAL.inc()
    if timeout:
        GEMINI_TIMEOUT_TOTAL.inc()
    if parse_fail:
        GEMINI_PARSE_FAIL_TOTAL.inc()


def set_gemini_avg_latency_ms(value: float) -> None:
    GEMINI_AVG_LATENCY_MS.set(max(0.0, float(value)))
