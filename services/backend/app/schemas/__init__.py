from app.schemas.auth import Token, TokenData, LoginRequest
from app.schemas.user import UserBase, UserCreate, UserUpdate, UserResponse, UserInDB
from app.schemas.camera import CameraBase, CameraCreate, CameraUpdate, CameraResponse
from app.schemas.detection import DetectionBase, DetectionCreate, DetectionUpdate, DetectionResponse, DetectionStatus
from app.schemas.dashboard import DashboardStats, OccurrencesByMonth, RecurrentLocation, VolumeByRPA
from app.schemas.conecta import (
    ConectaLoginUrlResponse,
    ConectaExchangeTicketRequest,
    ConectaLogoutUrlResponse,
    ConectaRevokeResponse,
)

__all__ = [
    "Token",
    "TokenData",
    "LoginRequest",
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserInDB",
    "CameraBase",
    "CameraCreate",
    "CameraUpdate",
    "CameraResponse",
    "DetectionBase",
    "DetectionCreate",
    "DetectionUpdate",
    "DetectionResponse",
    "DetectionStatus",
    "DashboardStats",
    "OccurrencesByMonth",
    "RecurrentLocation",
    "VolumeByRPA",
    "ConectaLoginUrlResponse",
    "ConectaExchangeTicketRequest",
    "ConectaLogoutUrlResponse",
    "ConectaRevokeResponse",
]
