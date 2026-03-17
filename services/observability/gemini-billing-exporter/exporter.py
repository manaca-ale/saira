"""Prometheus exporter for Gemini API billing metrics from Google Cloud Monitoring."""
import json
import logging
import os
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests as http_requests
from prometheus_client import Gauge, start_http_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "9109"))
BRL_RATE = float(os.getenv("BRL_RATE", "5.7"))

_DEFAULT_PROJECTS = json.dumps([
    {"id": "gen-lang-client-0028842427", "name": "Saira"},
    {"id": "gen-lang-client-0487533939", "name": "Flora"},
    {"id": "gen-lang-client-0616161525", "name": "Teste"},
    {"id": "manafin", "name": "Manafin"},
])
GCP_PROJECTS: list[dict] = json.loads(os.getenv("GCP_PROJECTS", _DEFAULT_PROJECTS))

# Pricing (USD per 1M tokens)
PRICING = {
    "gemini-2.5-flash":      {"input": 0.15, "output": 0.60, "thinking": 3.50},
    "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30, "thinking": 0.0},
    "gemini-2.0-flash":      {"input": 0.10, "output": 0.40, "thinking": 0.0},
    "gemini-2.0-flash-exp":  {"input": 0.10, "output": 0.40, "thinking": 0.0},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30, "thinking": 0.0},
    "gemini-3-flash":        {"input": 0.15, "output": 0.60, "thinking": 3.50},
}
DEFAULT_PRICING = {"input": 0.15, "output": 0.60, "thinking": 0.0}
OUTPUT_INPUT_RATIO = float(os.getenv("OUTPUT_INPUT_RATIO", "0.05"))
THINKING_TOKENS_PER_REQUEST = int(os.getenv("THINKING_TOKENS_PER_REQUEST", "1105"))

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
INPUT_TOKENS = Gauge(
    "gemini_billing_input_tokens",
    "Total input tokens for the period",
    ["project", "model", "period"],
)
REQUEST_COUNT = Gauge(
    "gemini_billing_requests",
    "Total requests for the period",
    ["project", "model", "period"],
)
ESTIMATED_COST = Gauge(
    "gemini_billing_estimated_cost_usd",
    "Estimated cost in USD for the period",
    ["project", "model", "period"],
)
ESTIMATED_COST_BRL = Gauge(
    "gemini_billing_estimated_cost_brl",
    "Estimated cost in BRL for the period",
    ["project", "model", "period"],
)
LAST_SCRAPE = Gauge("gemini_billing_last_scrape_timestamp", "Unix timestamp of last successful scrape")
SCRAPE_ERRORS = Gauge("gemini_billing_scrape_errors_total", "Total scrape errors")

_scrape_error_count = 0

# ---------------------------------------------------------------------------
# GCP Auth — tries ADC first, falls back to gcloud CLI token
# ---------------------------------------------------------------------------
_credentials = None
_auth_request = None
_use_gcloud_cli = False
_cached_token = None
_token_expiry = 0


def _get_token_via_gcloud() -> str:
    """Get access token using gcloud CLI (works when user is logged in)."""
    global _cached_token, _token_expiry
    now = time.time()
    if _cached_token and now < _token_expiry:
        return _cached_token
    # On Windows gcloud is gcloud.cmd; shell=True resolves it
    result = subprocess.run(
        "gcloud auth print-access-token",
        capture_output=True, text=True, timeout=15, shell=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gcloud auth failed: {result.stderr.strip()}")
    _cached_token = result.stdout.strip()
    _token_expiry = now + 3000  # cache for ~50 min (tokens last 60 min)
    return _cached_token


def _get_token_via_adc() -> str:
    """Get access token using Application Default Credentials."""
    global _credentials, _auth_request
    import google.auth
    import google.auth.transport.requests
    if _credentials is None:
        _credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/monitoring.read"]
        )
        _auth_request = google.auth.transport.requests.Request()
    _credentials.refresh(_auth_request)
    return _credentials.token


def _get_headers():
    global _use_gcloud_cli
    if not _use_gcloud_cli:
        try:
            token = _get_token_via_adc()
            return {"Authorization": f"Bearer {token}"}
        except Exception as exc:
            logger.warning("ADC auth failed (%s), falling back to gcloud CLI", exc)
            _use_gcloud_cli = True
    token = _get_token_via_gcloud()
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Cloud Monitoring queries
# ---------------------------------------------------------------------------
METRICS = {
    "input_tokens": "generativelanguage.googleapis.com/quota/generate_content_paid_tier_input_token_count/usage",
    "requests": "generativelanguage.googleapis.com/quota/generate_requests_per_model/usage",
}


def _query_metric(project_id: str, metric_type: str, start: str, end: str, alignment: str) -> dict:
    url = (
        f"https://monitoring.googleapis.com/v3/projects/{project_id}/timeSeries"
        f"?filter=metric.type%3D%22{metric_type}%22"
        f"&interval.startTime={start}"
        f"&interval.endTime={end}"
        f"&aggregation.alignmentPeriod={alignment}"
        f"&aggregation.perSeriesAligner=ALIGN_SUM"
    )
    resp = http_requests.get(url, headers=_get_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def _extract_by_model(data: dict) -> dict[str, int]:
    """Sum all points per model across the period, dedup by limit_name."""
    seen_limits: dict[str, str] = {}  # model -> first limit_name seen
    result: dict[str, int] = defaultdict(int)
    for ts in data.get("timeSeries", []):
        labels = ts.get("metric", {}).get("labels", {})
        model = labels.get("model", "unknown")
        limit_name = labels.get("limit_name", "")
        # Skip duplicate limit_name variants (PerMinutePerUser mirrors PerMinute)
        if model in seen_limits and seen_limits[model] != limit_name:
            continue
        seen_limits[model] = limit_name
        for pt in ts.get("points", []):
            val = int(pt["value"].get("int64Value", 0))
            result[model] += val
    return dict(result)


def _compute_cost(model: str, input_tokens: int, requests: int) -> float:
    prices = PRICING.get(model, DEFAULT_PRICING)
    est_output = int(input_tokens * OUTPUT_INPUT_RATIO)
    est_thinking = requests * THINKING_TOKENS_PER_REQUEST if prices["thinking"] > 0 else 0
    return (
        (input_tokens / 1e6) * prices["input"]
        + (est_output / 1e6) * prices["output"]
        + (est_thinking / 1e6) * prices["thinking"]
    )


# ---------------------------------------------------------------------------
# Scrape loop
# ---------------------------------------------------------------------------
def _period_bounds(period: str) -> tuple[str, str, str]:
    """Return (start_iso, end_iso, alignment_seconds) for the period."""
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Use Z suffix (not +00:00) and fixed 1-day alignment; sum points in code
    start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return start_str, end_str, "86400s"


def scrape():
    global _scrape_error_count
    logger.info("Starting scrape for %d projects", len(GCP_PROJECTS))

    for period in ("today", "month"):
        start_iso, end_iso, alignment = _period_bounds(period)

        for proj in GCP_PROJECTS:
            proj_id = proj["id"]
            proj_name = proj["name"]

            try:
                tokens_data = _query_metric(proj_id, METRICS["input_tokens"], start_iso, end_iso, alignment)
                reqs_data = _query_metric(proj_id, METRICS["requests"], start_iso, end_iso, alignment)

                tokens_by_model = _extract_by_model(tokens_data)
                reqs_by_model = _extract_by_model(reqs_data)

                all_models = set(tokens_by_model) | set(reqs_by_model)

                for model in all_models:
                    inp = tokens_by_model.get(model, 0)
                    reqs = reqs_by_model.get(model, 0)
                    cost = _compute_cost(model, inp, reqs)

                    INPUT_TOKENS.labels(project=proj_name, model=model, period=period).set(inp)
                    REQUEST_COUNT.labels(project=proj_name, model=model, period=period).set(reqs)
                    ESTIMATED_COST.labels(project=proj_name, model=model, period=period).set(round(cost, 6))
                    ESTIMATED_COST_BRL.labels(project=proj_name, model=model, period=period).set(round(cost * BRL_RATE, 2))

                logger.info(
                    "Scraped %s (%s) period=%s models=%d",
                    proj_name, proj_id, period, len(all_models),
                )
            except Exception:
                _scrape_error_count += 1
                SCRAPE_ERRORS.set(_scrape_error_count)
                logger.exception("Error scraping %s (%s) period=%s", proj_name, proj_id, period)

    LAST_SCRAPE.set(time.time())
    logger.info("Scrape complete")


def main():
    logger.info("Starting Gemini Billing Exporter on port %d (poll every %ds)", EXPORTER_PORT, POLL_INTERVAL)
    start_http_server(EXPORTER_PORT)

    while True:
        try:
            scrape()
        except Exception:
            logger.exception("Unhandled error in scrape loop")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
