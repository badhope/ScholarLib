"""Pydantic schemas for the notifications module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.schemas import MessageResponse, PaginationMeta


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    body: str | None = None
    related_type: str | None = None
    related_id: str | None = None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    data: list[NotificationResponse]
    meta: PaginationMeta


class UnreadCountResponse(BaseModel):
    unread: int


class ReadAllResponse(BaseModel):
    updated: int


__all__ = [
    "MessageResponse",
    "NotificationListResponse",
    "NotificationResponse",
    "PaginationMeta",
    "ReadAllResponse",
    "UnreadCountResponse",
]
