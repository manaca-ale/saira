import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis import init_redis, close_redis
from app.api.v1.router import api_router
from app.services.billing_scheduler import (
    start_billing_scheduler, stop_billing_scheduler,
)
from app.services.export_scheduler import (
    start_export_scheduler, stop_export_scheduler,
)
from app.services.offline_monitor import (
    start_offline_monitor, stop_offline_monitor,
)

logger = logging.getLogger(__name__)
_BRT = ZoneInfo("America/Sao_Paulo")


async def _report_snapshot_loop() -> None:
    """Background task: once per day at REPORT_SNAPSHOT_HOUR_BRT, persist a PDF
    snapshot of yesterday's daily KPI report to REPORTS_OUTPUT_DIR/YYYY-MM-DD.pdf.

    Mirrors the polling pattern used by yolo-worker's _maybe_run_drive_sync —
    no APScheduler needed, single async task per process.
    """
    if not settings.REPORT_SNAPSHOT_ENABLED:
        return
    from app.services.daily_report_service import build_daily_report
    from app.services.pdf_renderer import render_pdf

    out_dir = Path(settings.REPORTS_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    last_done: str | None = None

    while True:
        try:
            now_brt = datetime.now(_BRT)
            yesterday = (now_brt - timedelta(days=1)).date()
            day_key = yesterday.isoformat()
            if now_brt.hour >= settings.REPORT_SNAPSHOT_HOUR_BRT and last_done != day_key:
                pdf_path = out_dir / f"{day_key}.pdf"
                try:
                    async with AsyncSessionLocal() as session:
                        report = await build_daily_report(session, yesterday)
                    pdf_bytes = render_pdf(report)
                    pdf_path.write_bytes(pdf_bytes)
                    last_done = day_key
                    logger.info("Daily report snapshot written: %s", pdf_path)
                except Exception:
                    logger.exception("Daily report snapshot failed for %s", day_key)
        except Exception:
            logger.exception("Snapshot loop iteration failed")
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    start_billing_scheduler()
    start_export_scheduler()
    start_offline_monitor()
    snapshot_task = asyncio.create_task(_report_snapshot_loop())
    try:
        yield
    finally:
        snapshot_task.cancel()
        try:
            await snapshot_task
        except (asyncio.CancelledError, Exception):
            pass
        stop_offline_monitor()
        stop_export_scheduler()
        stop_billing_scheduler()
        await close_redis()


# Criar aplicação FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="API para o Sistema de Monitoramento de Descarte Irregular (SAIRA)",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers da API v1
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Endpoint raiz - health check"""
    return {
        "message": "SAIRA API is running",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}
