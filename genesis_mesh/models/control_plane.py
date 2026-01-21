"""Control-plane message models."""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .genesis import Signature


class ControlCommand(str):
    """Control command types."""
    POLICY_UPDATE = "policy_update"
    REVOKE_CERTIFICATE = "revoke_certificate"
    REVOKE_NODE = "revoke_node"
    UPDATE_BOOTSTRAP = "update_bootstrap"
    SHUTDOWN_NODE = "shutdown_node"
    ROTATE_KEYS = "rotate_keys"


class ControlScope(str):
    """Control command scopes."""
    NETWORK = "network"  # Entire network
    REGION = "region"  # Regional scope
    NODE = "node"  # Single node
    SERVICE = "service"  # Service-specific


class ControlMessageModel(BaseModel):
    """
    Control-plane message for administrative operations.

    All control messages must be signed by an authorized key
    and have appropriate role permissions.
    """
    message_id: str = Field(..., description="Unique message ID")
    command: str = Field(..., description="Control command")
    scope: str = Field(..., description="Command scope")
    issuer: str = Field(..., description="Issuer key ID")
    issuer_roles: List[str] = Field(..., description="Issuer roles")
    issued_at: datetime = Field(..., description="Issue timestamp")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")
    target: Optional[str] = Field(None, description="Target node/service ID")
    data: Dict[str, Any] = Field(default_factory=dict, description="Command data")
    signatures: List[Signature] = Field(
        default_factory=list,
        description="Signatures"
    )

    def to_canonical_json(self) -> str:
        """Convert to canonical JSON for signing/verification."""
        data = self.model_dump(exclude={"signatures"}, mode='json')
        return json.dumps(data, sort_keys=True, separators=(',', ':'))

    def is_expired(self) -> bool:
        """Check if message is expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at

    @staticmethod
    def create_policy_update(
        issuer: str,
        issuer_roles: List[str],
        policy_data: Dict[str, Any],
        validity_hours: int = 24
    ) -> "ControlMessageModel":
        """Create a policy update message."""
        import uuid
        return ControlMessageModel(
            message_id=str(uuid.uuid4()),
            command=ControlCommand.POLICY_UPDATE,
            scope=ControlScope.NETWORK,
            issuer=issuer,
            issuer_roles=issuer_roles,
            issued_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=validity_hours),
            data={"policy": policy_data}
        )

    @staticmethod
    def create_revocation(
        issuer: str,
        issuer_roles: List[str],
        cert_id: str,
        reason: str
    ) -> "ControlMessageModel":
        """Create a certificate revocation message."""
        import uuid
        return ControlMessageModel(
            message_id=str(uuid.uuid4()),
            command=ControlCommand.REVOKE_CERTIFICATE,
            scope=ControlScope.NETWORK,
            issuer=issuer,
            issuer_roles=issuer_roles,
            issued_at=datetime.utcnow(),
            data={
                "certificate_id": cert_id,
                "reason": reason
            }
        )

    @staticmethod
    def create_node_shutdown(
        issuer: str,
        issuer_roles: List[str],
        target_node: str,
        reason: str
    ) -> "ControlMessageModel":
        """Create a node shutdown command."""
        import uuid
        return ControlMessageModel(
            message_id=str(uuid.uuid4()),
            command=ControlCommand.SHUTDOWN_NODE,
            scope=ControlScope.NODE,
            issuer=issuer,
            issuer_roles=issuer_roles,
            issued_at=datetime.utcnow(),
            target=target_node,
            data={"reason": reason}
        )


class RolePermissions(BaseModel):
    """Role-based permissions for control commands."""
    role: str = Field(..., description="Role name")
    allowed_commands: List[str] = Field(..., description="Allowed commands")
    allowed_scopes: List[str] = Field(..., description="Allowed scopes")


# Default role permissions
DEFAULT_ROLE_PERMISSIONS = [
    RolePermissions(
        role="role:operator",
        allowed_commands=[
            ControlCommand.POLICY_UPDATE,
            ControlCommand.UPDATE_BOOTSTRAP,
        ],
        allowed_scopes=[ControlScope.NETWORK, ControlScope.REGION]
    ),
    RolePermissions(
        role="role:admin",
        allowed_commands=[
            ControlCommand.POLICY_UPDATE,
            ControlCommand.REVOKE_CERTIFICATE,
            ControlCommand.REVOKE_NODE,
            ControlCommand.UPDATE_BOOTSTRAP,
            ControlCommand.SHUTDOWN_NODE,
        ],
        allowed_scopes=[ControlScope.NETWORK, ControlScope.REGION, ControlScope.NODE]
    ),
    RolePermissions(
        role="role:anchor",
        allowed_commands=[],  # Anchors don't issue commands
        allowed_scopes=[]
    ),
    RolePermissions(
        role="role:client",
        allowed_commands=[],  # Clients don't issue commands
        allowed_scopes=[]
    ),
]
