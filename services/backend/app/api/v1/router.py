from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, cameras, detections, dashboard

api_router = APIRouter()

# Incluir routers de cada endpoint
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
api_router.include_router(detections.router, prefix="/detections", tags=["detections"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
