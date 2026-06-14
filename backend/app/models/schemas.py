"""Pydantic request and response schemas."""

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TokenSet(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str
    expires_in: int
    scope: str
    api_domain: Optional[str] = None


class ZohoUserInfo(BaseModel):
    zoho_user_id: str
    email: str
    display_name: str


class PendingActionSchema(BaseModel):
    operation: Literal["create_task", "update_task", "delete_task"]
    description: str
    parameters: dict[str, Any]
    tool_call_id: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str = Field(..., description="Active session UUID")
    thread_id: Optional[str] = Field(None, description="Chat thread UUID; if omitted a new thread is created")
    hil_response: Optional[Literal["confirm", "cancel"]] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    thread_id: str
    pending_action: Optional[PendingActionSchema] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    timestamp: str


class ErrorResponse(BaseModel):
    error: str
    detail: str


class LongTermMemoryUpdate(BaseModel):
    last_active_project_id: Optional[str] = None
    session_summary_entry: dict[str, Any]


# ── Thread schemas ────────────────────────────────────────────────────────────

class ThreadCreate(BaseModel):
    title: str = Field(default="New Chat", max_length=255)


class ThreadResponse(BaseModel):
    id: str
    title: str
    created_at: datetime

    class Config:
        from_attributes = True


class ThreadMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ThreadMessagesResponse(BaseModel):
    thread_id: str
    messages: List[ThreadMessageResponse]
