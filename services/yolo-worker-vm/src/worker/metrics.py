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

# agent label values: "gate" (Agent-1 cascade gate) or "detail" (Agent-2 / direct Gemini call)
# camera_id is stringified camera.id (or "unknown" when camera cannot be resolved).
GEMINI_CALLS_TOTAL = Counter(
    "saira_gemini_calls_total",
    "Total Gemini API calls performed by the worker.",
    ["agent", "camera_id"],
)

GEMINI_ERRORS_TOTAL = Counter(
    "saira_gemini_errors_total",
    "Total Gemini call failures.",
    ["agent", "camera_id"],
)

GEMINI_TIMEOUT_TOTAL = Counter(
    "saira_gemini_timeout_total",
    "Total Gemini timeout failures.",
    ["agent", "camera_id"],
)

GEMINI_PARSE_FAIL_TOTAL = Counter(
    "saira_gemini_parse_fail_total",
    "Total Gemini JSON/schema parse failures.",
    ["agent", "camera_id"],
)

# Gemini errors broken down by provider-agnostic class so alerting can fire
# specifically on a dead gate (quota/credenciais) vs transient timeout/parse.
# error_type values: "quota" (429/RESOURCE_EXHAUSTED/prepayment), "auth"
# (RefreshError/credential/permission/401/403), "timeout", "parse", "other".
# camera_id is intentionally omitted to keep cardinality low — a quota/auth
# outage is fleet-wide, not per-camera.
GEMINI_ERROR_TYPE_TOTAL = Counter(
    "saira_gemini_error_type_total",
    "Gemini call failures by provider-agnostic error class.",
    ["agent", "error_type"],
)

GEMINI_INPUT_TOKENS_TOTAL = Counter(
    "saira_gemini_input_tokens_total",
    "Total Gemini input tokens consumed.",
    ["agent", "camera_id"],
)

GEMINI_OUTPUT_TOKENS_TOTAL = Counter(
    "saira_gemini_output_tokens_total",
    "Total Gemini output tokens consumed.",
    ["agent", "camera_id"],
)

GEMINI_COST_USD_TOTAL = Counter(
    "saira_gemini_estimated_cost_usd_total",
    "Estimated Gemini cumulative cost in USD.",
    ["agent", "camera_id"],
)

GEMINI_LATENCY_SECONDS = Histogram(
    "saira_gemini_latency_seconds",
    "Gemini call latency in seconds.",
    ["agent", "camera_id"],
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

# BGSUB pre-filter (OpenCV) — counts each evaluation by reason and mode.
# reason values: "filtered" (suppressed), "passed" (let through), "skipped_no_polygon",
# "skipped_no_model", "skipped_disabled", "error".
# mode values: "single" (legacy single MOG2) or "dual" (dual-rate MOG2).
BGSUB_EVAL_TOTAL = Counter(
    "saira_bgsub_eval_total",
    "Total BGSUB pre-filter evaluations performed before the Gemini gate.",
    ["camera_id", "reason", "mode"],
)

# Adaptive-baseline update counter — emitted after Gemini gate returns.
# reason values: applied | persisted | skipped_disabled | skipped_low_confidence
#                | skipped_no_model | skipped_positive | skipped_zone_not_clean | error
# skipped_zone_not_clean: clean-zone-only device, but the pile zone still held
#   litter (prior_had_litter or last_frame_has_litter) so absorption was skipped.
BGSUB_ADAPTIVE_UPDATES_TOTAL = Counter(
    "saira_bgsub_adaptive_updates_total",
    "BGSUB MOG2 adaptive-baseline update outcomes per camera.",
    ["camera_id", "reason"],
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


def observe_gemini_call(*, agent: str = "detail", camera_id: str = "unknown") -> None:
    GEMINI_CALLS_TOTAL.labels(agent=agent, camera_id=camera_id).inc()


def observe_gemini_success(
    *,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float,
    agent: str = "detail",
    camera_id: str = "unknown",
) -> None:
    GEMINI_LATENCY_SECONDS.labels(agent=agent, camera_id=camera_id).observe(
        max(0.0, float(latency_ms) / 1000.0)
    )
    GEMINI_INPUT_TOKENS_TOTAL.labels(agent=agent, camera_id=camera_id).inc(max(0, int(input_tokens)))
    GEMINI_OUTPUT_TOKENS_TOTAL.labels(agent=agent, camera_id=camera_id).inc(max(0, int(output_tokens)))
    GEMINI_COST_USD_TOTAL.labels(agent=agent, camera_id=camera_id).inc(max(0.0, float(estimated_cost_usd)))
    GEMINI_LAST_INPUT_TOKENS.set(max(0, int(input_tokens)))
    GEMINI_LAST_OUTPUT_TOKENS.set(max(0, int(output_tokens)))
    GEMINI_LAST_ESTIMATED_COST_USD.set(max(0.0, float(estimated_cost_usd)))


def classify_gemini_error(msg: str) -> str:
    """Provider-agnostic error class for alerting (works for AI Studio + Vertex).

    `msg` should already be lower-cased. Precedence: timeout/parse first
    (transient), then the outage classes quota/auth that mean the gate is dead
    and should page operators. Feeds GEMINI_ERROR_TYPE_TOTAL.
    """
    if "timeout" in msg:
        return "timeout"
    if "validation" in msg or "json" in msg:
        return "parse"
    if any(k in msg for k in ("resource_exhausted", "quota", "prepayment", "exhausted", "429")):
        return "quota"
    if any(
        k in msg
        for k in (
            "refresh", "credential", "default credentials", "unauthenticated",
            "permission", "reauth", "401", "403",
        )
    ):
        return "auth"
    return "other"


def observe_gemini_error(
    *,
    timeout: bool,
    parse_fail: bool,
    agent: str = "detail",
    camera_id: str = "unknown",
    error_type: str = "other",
) -> None:
    GEMINI_ERRORS_TOTAL.labels(agent=agent, camera_id=camera_id).inc()
    if timeout:
        GEMINI_TIMEOUT_TOTAL.labels(agent=agent, camera_id=camera_id).inc()
    if parse_fail:
        GEMINI_PARSE_FAIL_TOTAL.labels(agent=agent, camera_id=camera_id).inc()
    GEMINI_ERROR_TYPE_TOTAL.labels(agent=agent, error_type=error_type).inc()


def set_gemini_avg_latency_ms(value: float) -> None:
    GEMINI_AVG_LATENCY_MS.set(max(0.0, float(value)))


# -----------------------------------------------------------------------------
# Car-stopped shadow detector — parallel to Gemini, never persists to DB.
# -----------------------------------------------------------------------------

CAR_SHADOW_WINDOWS_TOTAL = Counter(
    "saira_car_shadow_windows_total",
    "Total windows processed by the car-stopped shadow detector.",
    ["camera_id"],
)

CAR_SHADOW_EVENTS_TOTAL = Counter(
    "saira_car_shadow_events_total",
    "Stopped-vehicle events resolved by level.",
    ["camera_id", "level"],
)

CAR_SHADOW_COMPARISON_TOTAL = Counter(
    "saira_car_shadow_comparison_total",
    "Window-by-window comparison Gemini vs Car-Stopped.",
    ["camera_id", "class"],
)

CAR_SHADOW_INFERENCE_SECONDS = Histogram(
    "saira_car_shadow_inference_seconds",
    "YOLO inference latency per window for the car-stopped detector.",
    ["camera_id"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10),
)

CAR_SHADOW_ERRORS_TOTAL = Counter(
    "saira_car_shadow_errors_total",
    "Errors raised inside the car-stopped shadow detector.",
    ["camera_id"],
)


def observe_car_shadow_window(camera_id: str, inference_seconds: float) -> None:
    CAR_SHADOW_WINDOWS_TOTAL.labels(camera_id=camera_id).inc()
    CAR_SHADOW_INFERENCE_SECONDS.labels(camera_id=camera_id).observe(
        max(0.0, float(inference_seconds))
    )


def observe_car_shadow_events(camera_id: str, levels: list[str]) -> None:
    for level in levels:
        CAR_SHADOW_EVENTS_TOTAL.labels(camera_id=camera_id, level=level).inc()


def observe_car_shadow_comparison(camera_id: str, comparison_class: str) -> None:
    CAR_SHADOW_COMPARISON_TOTAL.labels(camera_id=camera_id, **{"class": comparison_class}).inc()


def observe_car_shadow_error(camera_id: str) -> None:
    CAR_SHADOW_ERRORS_TOTAL.labels(camera_id=camera_id).inc()


def observe_bgsub_evaluation(*, camera_id: str, reason: str, mode: str = "single") -> None:
    """Record one BGSUB pre-filter evaluation outcome.

    mode: "single" or "dual" — which MOG2 configuration was active.
    """
    BGSUB_EVAL_TOTAL.labels(camera_id=camera_id, reason=reason, mode=mode).inc()


def observe_bgsub_adaptive_update(*, camera_id: str, reason: str) -> None:
    """Record one BGSUB adaptive-baseline update attempt outcome."""
    BGSUB_ADAPTIVE_UPDATES_TOTAL.labels(camera_id=camera_id, reason=reason).inc()
