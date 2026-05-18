from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    users,
    cameras,
    detections,
    dashboard,
    notifications,
    offenders,
    test,
    conecta,
    geocoding,
    reports,
    billing,
)

api_router = APIRouter()

# Incluir routers de cada endpoint
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
api_router.include_router(detections.router, prefix="/detections", tags=["detections"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(offenders.router, prefix="/offenders", tags=["offenders"])
api_router.include_router(test.router, prefix="/test", tags=["test"])
api_router.include_router(conecta.router, prefix="/integrations/conecta", tags=["conecta"])
api_router.include_router(geocoding.router, prefix="/geocoding", tags=["geocoding"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
