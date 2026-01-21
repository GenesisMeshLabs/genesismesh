"""Role-Based Access Control (RBAC) enforcement."""

import logging
from typing import List, Optional

from ..models.control_plane import (
    ControlMessageModel,
    RolePermissions,
    DEFAULT_ROLE_PERMISSIONS
)
from ..crypto import verify_model_signature


logger = logging.getLogger(__name__)


class RBACEnforcer:
    """
    Enforces role-based access control for control-plane messages.

    Validates that:
    1. Control message signature is valid
    2. Issuer has required role
    3. Command is allowed for the role
    4. Scope matches role permissions
    5. Message is not expired
    """

    def __init__(
        self,
        role_permissions: Optional[List[RolePermissions]] = None,
        require_all_signatures: bool = False,
        min_signatures: int = 1
    ):
        """
        Initialize RBAC enforcer.

        Args:
            role_permissions: Custom role permissions (uses defaults if None)
            require_all_signatures: Require all signatures to be valid (default: False)
            min_signatures: Minimum number of valid signatures required (default: 1)
        """
        self.role_permissions = role_permissions or DEFAULT_ROLE_PERMISSIONS
        self._permission_map = {
            rp.role: rp for rp in self.role_permissions
        }
        self.require_all_signatures = require_all_signatures
        self.min_signatures = min_signatures

    def validate_control_message(
        self,
        message: ControlMessageModel,
        public_key: str,
        additional_keys: Optional[dict] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Validate a control message with multi-signature support.

        Args:
            message: Control message to validate
            public_key: Primary public key to verify signature
            additional_keys: Dict of key_id -> public_key for additional signatures

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if expired
        if message.is_expired():
            return False, "Control message has expired"

        # Verify signatures
        if not message.signatures:
            return False, "Control message has no signature"

        # Build key lookup map
        key_map = {message.issuer: public_key}
        if additional_keys:
            key_map.update(additional_keys)

        # Verify all signatures
        valid_signatures = []
        invalid_signatures = []

        for signature in message.signatures:
            key_id = signature.key_id
            sig_public_key = key_map.get(key_id)

            if not sig_public_key:
                logger.warning(f"Unknown key ID in signature: {key_id}")
                invalid_signatures.append(key_id)
                continue

            try:
                if verify_model_signature(message, signature, sig_public_key):
                    valid_signatures.append(key_id)
                else:
                    invalid_signatures.append(key_id)
            except Exception as e:
                logger.error(f"Error verifying signature from {key_id}: {e}")
                invalid_signatures.append(key_id)

        # Check signature requirements
        if self.require_all_signatures:
            # All signatures must be valid
            if len(invalid_signatures) > 0:
                return False, (
                    f"Not all signatures are valid. "
                    f"Valid: {len(valid_signatures)}, Invalid: {len(invalid_signatures)}"
                )
        else:
            # Check minimum threshold
            if len(valid_signatures) < self.min_signatures:
                return False, (
                    f"Insufficient valid signatures: {len(valid_signatures)} "
                    f"(required: {self.min_signatures})"
                )

        logger.debug(
            f"Signature validation passed: {len(valid_signatures)} valid signatures "
            f"from {len(message.signatures)} total"
        )

        # Check role permissions
        has_permission = False
        for role in message.issuer_roles:
            if self._check_role_permission(role, message.command, message.scope):
                has_permission = True
                break

        if not has_permission:
            return False, f"Issuer roles {message.issuer_roles} not authorized for {message.command}"

        return True, None

    def _check_role_permission(
        self,
        role: str,
        command: str,
        scope: str
    ) -> bool:
        """
        Check if role has permission for command and scope.

        Args:
            role: Role to check
            command: Command to execute
            scope: Command scope

        Returns:
            True if authorized, False otherwise
        """
        permissions = self._permission_map.get(role)
        if not permissions:
            return False

        # Check command permission
        if command not in permissions.allowed_commands:
            return False

        # Check scope permission
        if scope not in permissions.allowed_scopes:
            return False

        return True

    def has_role_permission(
        self,
        roles: List[str],
        command: str,
        scope: str
    ) -> bool:
        """
        Check if any of the roles has permission.

        Args:
            roles: List of roles to check
            command: Command to execute
            scope: Command scope

        Returns:
            True if any role is authorized
        """
        for role in roles:
            if self._check_role_permission(role, command, scope):
                return True
        return False

    def get_allowed_commands(self, roles: List[str]) -> List[str]:
        """
        Get all commands allowed for given roles.

        Args:
            roles: List of roles

        Returns:
            List of allowed commands
        """
        allowed = set()
        for role in roles:
            permissions = self._permission_map.get(role)
            if permissions:
                allowed.update(permissions.allowed_commands)
        return list(allowed)

    def get_allowed_scopes(self, roles: List[str]) -> List[str]:
        """
        Get all scopes allowed for given roles.

        Args:
            roles: List of roles

        Returns:
            List of allowed scopes
        """
        allowed = set()
        for role in roles:
            permissions = self._permission_map.get(role)
            if permissions:
                allowed.update(permissions.allowed_scopes)
        return list(allowed)
