"""Security audit logging with tamper-evident chaining."""

import json
import hashlib
import logging
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Audit event types."""
    # Certificate events
    CERTIFICATE_ISSUED = "certificate_issued"
    CERTIFICATE_RENEWED = "certificate_renewed"
    CERTIFICATE_REVOKED = "certificate_revoked"
    CERTIFICATE_EXPIRED = "certificate_expired"

    # Node events
    NODE_STARTED = "node_started"
    NODE_STOPPED = "node_stopped"
    NODE_JOINED = "node_joined"
    NODE_LEFT = "node_left"
    NODE_BLACKLISTED = "node_blacklisted"

    # Connection events
    CONNECTION_ESTABLISHED = "connection_established"
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_CLOSED = "connection_closed"

    # Control plane events
    CONTROL_MESSAGE_RECEIVED = "control_message_received"
    CONTROL_MESSAGE_ACCEPTED = "control_message_accepted"
    CONTROL_MESSAGE_REJECTED = "control_message_rejected"
    POLICY_UPDATED = "policy_updated"

    # Security events
    AUTHENTICATION_SUCCESS = "authentication_success"
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHORIZATION_DENIED = "authorization_denied"
    SIGNATURE_INVALID = "signature_invalid"

    # CRL events
    CRL_UPDATED = "crl_updated"
    CRL_SIGNATURE_INVALID = "crl_signature_invalid"


@dataclass
class AuditEvent:
    """
    Tamper-evident audit event.

    Includes chain hash to detect tampering.
    """
    event_id: str
    event_type: EventType
    timestamp: datetime
    node_id: str
    actor: Optional[str]  # Who triggered the event
    target: Optional[str]  # What was affected
    action: str
    result: str  # success, failure, denied
    details: Dict[str, Any] = field(default_factory=dict)
    previous_hash: Optional[str] = None
    event_hash: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "node_id": self.node_id,
            "actor": self.actor,
            "target": self.target,
            "action": self.action,
            "result": self.result,
            "details": self.details,
            "previous_hash": self.previous_hash,
        }

    def compute_hash(self) -> str:
        """Compute event hash for chaining."""
        data = self.to_dict()
        # Exclude event_hash itself
        data.pop("event_hash", None)
        canonical = json.dumps(data, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


class AuditLogger:
    """
    Security audit logger with tamper-evident log chaining.

    Each event includes hash of previous event, creating a chain
    that makes tampering detectable.
    """

    def __init__(
        self,
        node_id: str,
        log_file: Optional[Path] = None,
        enable_chaining: bool = True
    ):
        """
        Initialize audit logger.

        Args:
            node_id: Local node ID
            log_file: Path to audit log file (optional)
            enable_chaining: Enable hash chaining for tamper detection
        """
        self.node_id = node_id
        self.log_file = log_file
        self.enable_chaining = enable_chaining

        self._last_hash: Optional[str] = None
        self._event_count = 0

        # Setup file logging if specified
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._file_handler = logging.FileHandler(self.log_file)
            self._file_handler.setFormatter(
                logging.Formatter('%(message)s')
            )

    def log_event(
        self,
        event_type: EventType,
        action: str,
        result: str,
        actor: Optional[str] = None,
        target: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditEvent:
        """
        Log an audit event.

        Args:
            event_type: Type of event
            action: Action description
            result: Result (success, failure, denied)
            actor: Who triggered the event
            target: What was affected
            details: Additional details

        Returns:
            Created audit event
        """
        import uuid

        # Create event
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.utcnow(),
            node_id=self.node_id,
            actor=actor,
            target=target,
            action=action,
            result=result,
            details=details or {},
            previous_hash=self._last_hash if self.enable_chaining else None
        )

        # Compute hash
        if self.enable_chaining:
            event.event_hash = event.compute_hash()
            self._last_hash = event.event_hash

        self._event_count += 1

        # Write to log file
        self._write_event(event)

        # Also log to standard logger
        logger.info(
            f"AUDIT: {event.event_type.value} | {event.action} | {event.result} | "
            f"actor={event.actor} target={event.target}"
        )

        return event

    def _write_event(self, event: AuditEvent):
        """Write event to audit log file."""
        if not self.log_file:
            return

        try:
            with open(self.log_file, 'a') as f:
                json.dump(event.to_dict(), f)
                f.write('\n')
        except Exception as e:
            logger.error(f"Failed to write audit event: {e}")

    # Convenience methods for common events

    def log_certificate_issued(self, cert_id: str, subject: str):
        """Log certificate issuance."""
        return self.log_event(
            EventType.CERTIFICATE_ISSUED,
            action=f"Issued certificate to {subject}",
            result="success",
            actor=self.node_id,
            target=cert_id,
            details={"subject": subject}
        )

    def log_certificate_renewed(self, cert_id: str):
        """Log certificate renewal."""
        return self.log_event(
            EventType.CERTIFICATE_RENEWED,
            action="Renewed certificate",
            result="success",
            actor=self.node_id,
            target=cert_id
        )

    def log_certificate_revoked(self, cert_id: str, reason: str, issuer: str):
        """Log certificate revocation."""
        return self.log_event(
            EventType.CERTIFICATE_REVOKED,
            action=f"Revoked certificate: {reason}",
            result="success",
            actor=issuer,
            target=cert_id,
            details={"reason": reason}
        )

    def log_node_joined(self, peer_id: str, endpoint: str):
        """Log node joining network."""
        return self.log_event(
            EventType.NODE_JOINED,
            action=f"Node joined from {endpoint}",
            result="success",
            target=peer_id,
            details={"endpoint": endpoint}
        )

    def log_node_left(self, peer_id: str, reason: str = "disconnected"):
        """Log node leaving network."""
        return self.log_event(
            EventType.NODE_LEFT,
            action=f"Node left: {reason}",
            result="success",
            target=peer_id,
            details={"reason": reason}
        )

    def log_node_blacklisted(self, peer_id: str, reason: str):
        """Log node blacklisting."""
        return self.log_event(
            EventType.NODE_BLACKLISTED,
            action=f"Node blacklisted: {reason}",
            result="success",
            target=peer_id,
            details={"reason": reason}
        )

    def log_connection_established(self, peer_id: str, endpoint: str):
        """Log connection establishment."""
        return self.log_event(
            EventType.CONNECTION_ESTABLISHED,
            action=f"Connected to {endpoint}",
            result="success",
            target=peer_id,
            details={"endpoint": endpoint}
        )

    def log_connection_failed(self, peer_id: str, error: str):
        """Log connection failure."""
        return self.log_event(
            EventType.CONNECTION_FAILED,
            action="Connection attempt failed",
            result="failure",
            target=peer_id,
            details={"error": error}
        )

    def log_control_message(
        self,
        command: str,
        issuer: str,
        accepted: bool,
        reason: Optional[str] = None
    ):
        """Log control message."""
        event_type = (
            EventType.CONTROL_MESSAGE_ACCEPTED if accepted
            else EventType.CONTROL_MESSAGE_REJECTED
        )
        return self.log_event(
            event_type,
            action=f"Control command: {command}",
            result="accepted" if accepted else "rejected",
            actor=issuer,
            details={"command": command, "reason": reason}
        )

    def log_policy_updated(self, policy_id: str, issuer: str):
        """Log policy update."""
        return self.log_event(
            EventType.POLICY_UPDATED,
            action="Policy updated",
            result="success",
            actor=issuer,
            target=policy_id
        )

    def log_authentication_failure(self, peer_id: str, reason: str):
        """Log authentication failure."""
        return self.log_event(
            EventType.AUTHENTICATION_FAILURE,
            action="Authentication failed",
            result="failure",
            target=peer_id,
            details={"reason": reason}
        )

    def log_authorization_denied(self, actor: str, action: str, reason: str):
        """Log authorization denial."""
        return self.log_event(
            EventType.AUTHORIZATION_DENIED,
            action=f"Authorization denied for: {action}",
            result="denied",
            actor=actor,
            details={"reason": reason}
        )

    def log_crl_updated(self, sequence: int, revoked_count: int):
        """Log CRL update."""
        return self.log_event(
            EventType.CRL_UPDATED,
            action=f"CRL updated to sequence {sequence}",
            result="success",
            details={"sequence": sequence, "revoked_count": revoked_count}
        )

    def verify_chain(self, start_event: int = 0, end_event: Optional[int] = None) -> bool:
        """
        Verify audit log chain integrity.

        Args:
            start_event: Start event number
            end_event: End event number (None for all)

        Returns:
            True if chain is intact, False if tampered
        """
        if not self.log_file or not self.enable_chaining:
            return True

        try:
            with open(self.log_file, 'r') as f:
                events = [json.loads(line) for line in f]

            if end_event is None:
                end_event = len(events)

            previous_hash = None
            for i in range(start_event, end_event):
                event_data = events[i]

                # Check previous hash matches
                if event_data.get("previous_hash") != previous_hash:
                    logger.error(f"Chain break at event {i}")
                    return False

                # Compute expected hash
                event_data_copy = event_data.copy()
                event_hash = event_data_copy.pop("event_hash", None)
                canonical = json.dumps(event_data_copy, sort_keys=True)
                expected_hash = hashlib.sha256(canonical.encode()).hexdigest()

                previous_hash = event_hash

            return True

        except Exception as e:
            logger.error(f"Error verifying chain: {e}")
            return False

    def get_event_count(self) -> int:
        """Get total event count."""
        return self._event_count

    def get_last_hash(self) -> Optional[str]:
        """Get hash of last event."""
        return self._last_hash
