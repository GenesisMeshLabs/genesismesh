"""Enrollment models for permissioned mesh joins."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class InviteToken(BaseModel):
    """Pre-authorized single-use token for node enrollment."""

    token_id: str = Field(..., description="Opaque invite token secret")
    assigned_roles: list[str] = Field(
        default_factory=list,
        description="Roles assigned to the node that redeems this token",
    )
    max_validity_hours: int = Field(..., description="Maximum certificate validity")
    created_at: datetime = Field(..., description="Invite creation time")
    expires_at: datetime = Field(..., description="Invite expiration time")
    used_at: Optional[datetime] = Field(None, description="Token redemption time")
    used_by_key: Optional[str] = Field(None, description="Redeeming node public key")
