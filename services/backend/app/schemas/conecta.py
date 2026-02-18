from pydantic import BaseModel, Field


class ConectaLoginUrlResponse(BaseModel):
    authorization_url: str
    state: str


class ConectaExchangeTicketRequest(BaseModel):
    ticket: str = Field(..., min_length=16)


class ConectaLogoutUrlResponse(BaseModel):
    logout_url: str


class ConectaRevokeResponse(BaseModel):
    status: str
    message: str
