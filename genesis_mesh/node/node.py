"""Mesh node implementation."""

import json
import logging
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, List

import requests

from ..crypto import (
    KeyPair,
    generate_keypair,
    public_key_from_b64,
    sign_data,
    verify_model_signature,
)
from ..models import GenesisBlock, JoinCertificate, PolicyManifest
from .persistent_runner import run_persistent_node

logger = logging.getLogger(__name__)


class MeshNode:
    """
    Genesis Mesh network node.

    A node can act as:
    - Anchor: Gateway/relay node
    - Bridge: Edge resiliency node
    - Client: Endpoint node
    """

    def __init__(
        self,
        genesis_block: GenesisBlock,
        node_keypair: Optional[KeyPair] = None,
        roles: Optional[List[str]] = None
    ):
        """
        Initialize a mesh node.

        Args:
            genesis_block: The network's genesis block
            node_keypair: Node's cryptographic keypair (generates new if None)
            roles: Node roles (default: ['role:client'])
        """
        self.genesis_block = genesis_block
        self.node_keypair = node_keypair or generate_keypair()
        self.roles = roles or ['role:client']
        self.join_certificate: Optional[JoinCertificate] = None
        self.policy_manifest: Optional[PolicyManifest] = None
        self._running = False
        self._na_endpoint: Optional[str] = None

        # Verify genesis block signatures
        if not self._verify_genesis_block():
            raise ValueError("Genesis block signature verification failed")

        logger.info(f"Node initialized for network: {genesis_block.network_name}")
        logger.info(f"Node public key: {self.node_keypair.public_key_b64}")
        logger.info(f"Roles: {self.roles}")

    def _verify_genesis_block(self) -> bool:
        """
        Verify the genesis block signatures.

        Returns:
            True if all signatures are valid
        """
        if not self.genesis_block.signatures:
            logger.error("Genesis block has no signatures")
            return False

        root_public_key = public_key_from_b64(self.genesis_block.root_public_key)

        for sig in self.genesis_block.signatures:
            if not verify_model_signature(self.genesis_block, sig, root_public_key):
                logger.error(f"Invalid signature from key {sig.key_id}")
                return False

        logger.info("Genesis block signatures verified successfully")
        return True

    def join_network(
        self,
        na_endpoint: str,
        validity_hours: int = 168,
        invite_token: Optional[str] = None,
    ) -> JoinCertificate:
        """
        Request a join certificate from the Network Authority.

        Args:
            na_endpoint: Network Authority endpoint (e.g., http://localhost:8443)
            validity_hours: Requested certificate validity in hours

        Returns:
            JoinCertificate from NA

        Raises:
            Exception if join request fails
        """
        logger.info(f"Requesting join certificate from {na_endpoint}")

        # Prepare join request
        request_data: dict[str, Any] = {
            "node_public_key": self.node_keypair.public_key_b64,
            "roles": self.roles,
            "validity_hours": validity_hours
        }
        if invite_token:
            request_data["invite_token"] = invite_token

        # Send join request
        try:
            response = requests.post(
                f"{na_endpoint}/join",
                json=request_data,
                timeout=10
            )
            response.raise_for_status()

            # Parse certificate
            cert_data = response.json()
            self.join_certificate = JoinCertificate(**cert_data)

            # Verify certificate signature
            if not self._verify_join_certificate(self.join_certificate):
                raise ValueError("Join certificate signature verification failed")

            logger.info(f"Received valid join certificate: {self.join_certificate.cert_id}")
            logger.info(f"Valid until: {self.join_certificate.expires_at}")

            return self.join_certificate

        except requests.RequestException as e:
            logger.error(f"Join request failed: {e}")
            raise

    def _verify_join_certificate(self, cert: JoinCertificate) -> bool:
        """
        Verify a join certificate signature.

        Args:
            cert: Certificate to verify

        Returns:
            True if certificate is valid
        """
        # Verify network name matches
        if cert.network_name != self.genesis_block.network_name:
            logger.error("Certificate network name mismatch")
            return False

        # Verify certificate is not expired
        if not cert.is_valid():
            logger.error("Certificate is expired or not yet valid")
            return False

        # Verify signature
        na_public_key = public_key_from_b64(self.genesis_block.network_authority.public_key)

        for sig in cert.signatures:
            if verify_model_signature(cert, sig, na_public_key):
                return True

        logger.error("No valid signatures found on certificate")
        return False

    def fetch_policy(self, na_endpoint: str) -> PolicyManifest:
        """
        Fetch and verify the policy manifest from NA.

        Args:
            na_endpoint: Network Authority endpoint

        Returns:
            PolicyManifest

        Raises:
            Exception if fetch or verification fails
        """
        logger.info(f"Fetching policy manifest from {na_endpoint}")

        try:
            response = requests.get(f"{na_endpoint}/policy", timeout=10)
            response.raise_for_status()

            policy_data = response.json()
            self.policy_manifest = PolicyManifest(**policy_data)

            # Verify policy signature
            if not self._verify_policy_manifest(self.policy_manifest):
                raise ValueError("Policy manifest signature verification failed")

            logger.info(f"Received valid policy manifest: {self.policy_manifest.policy_id}")
            return self.policy_manifest

        except requests.RequestException as e:
            logger.error(f"Policy fetch failed: {e}")
            raise

    def _verify_policy_manifest(self, policy: PolicyManifest) -> bool:
        """
        Verify a policy manifest signature.

        Args:
            policy: Policy to verify

        Returns:
            True if policy is valid
        """
        na_public_key = public_key_from_b64(self.genesis_block.network_authority.public_key)

        for sig in policy.signatures:
            if verify_model_signature(policy, sig, na_public_key):
                return True

        logger.error("No valid signatures found on policy manifest")
        return False

    def is_certificate_valid(self) -> bool:
        """
        Check if the current join certificate is valid.

        Returns:
            True if certificate exists and is valid
        """
        if not self.join_certificate:
            return False
        return self.join_certificate.is_valid()

    def get_status(self) -> dict:
        """
        Get node status information.

        Returns:
            Dictionary with node status
        """
        return {
            "network": self.genesis_block.network_name,
            "network_version": self.genesis_block.network_version,
            "node_public_key": self.node_keypair.public_key_b64,
            "roles": self.roles,
            "certificate_valid": self.is_certificate_valid(),
            "certificate_id": self.join_certificate.cert_id if self.join_certificate else None,
            "certificate_expires": self.join_certificate.expires_at.isoformat() if self.join_certificate else None,
            "policy_id": self.policy_manifest.policy_id if self.policy_manifest else None
        }

    def _sign_request(self, payload: dict) -> dict:
        """
        Add authentication fields (timestamp, nonce, signature) to a request payload.

        Args:
            payload: Request payload to sign

        Returns:
            Payload with timestamp, nonce, and signature added
        """
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        payload["nonce"] = str(_uuid.uuid4())

        # Build canonical form (everything except 'signature', sorted)
        canonical = json.dumps(
            {k: v for k, v in sorted(payload.items()) if k != 'signature'},
            sort_keys=True,
            separators=(',', ':')
        )
        payload["signature"] = sign_data(
            canonical.encode('utf-8'),
            self.node_keypair.private_key
        )
        return payload

    def send_heartbeat(self, na_endpoint: str) -> bool:
        """
        Send a signed heartbeat to the Network Authority.

        Args:
            na_endpoint: Network Authority endpoint

        Returns:
            True if heartbeat was acknowledged
        """
        if not self.join_certificate:
            logger.warning("Cannot send heartbeat without join certificate")
            return False

        try:
            payload = {
                "cert_id": self.join_certificate.cert_id,
                "node_public_key": self.node_keypair.public_key_b64,
                "status": "healthy"
            }
            signed_payload = self._sign_request(payload)

            response = requests.post(
                f"{na_endpoint}/heartbeat",
                json=signed_payload,
                timeout=5
            )
            response.raise_for_status()
            return response.json().get("ack", False)

        except requests.RequestException as e:
            logger.warning(f"Heartbeat failed: {e}")
            return False

    def renew_certificate(self, na_endpoint: str, validity_hours: int = 168) -> bool:
        """
        Renew the join certificate before it expires.

        Args:
            na_endpoint: Network Authority endpoint
            validity_hours: Requested validity for new certificate

        Returns:
            True if renewal was successful
        """
        if not self.join_certificate:
            logger.error("Cannot renew without existing certificate")
            return False

        logger.info(f"Renewing certificate {self.join_certificate.cert_id[:8]}...")

        try:
            payload = {
                "cert_id": self.join_certificate.cert_id,
                "node_public_key": self.node_keypair.public_key_b64,
                "roles": self.roles,
                "validity_hours": validity_hours
            }
            signed_payload = self._sign_request(payload)

            response = requests.post(
                f"{na_endpoint}/renew",
                json=signed_payload,
                timeout=10
            )
            response.raise_for_status()

            cert_data = response.json()
            new_cert = JoinCertificate(**cert_data)

            # Verify the new certificate
            if not self._verify_join_certificate(new_cert):
                logger.error("New certificate failed verification")
                return False

            old_cert_id = self.join_certificate.cert_id
            self.join_certificate = new_cert
            logger.info(f"Certificate renewed: {old_cert_id[:8]}... -> {new_cert.cert_id[:8]}...")
            logger.info(f"New expiry: {new_cert.expires_at}")
            return True

        except requests.RequestException as e:
            logger.error(f"Certificate renewal failed: {e}")
            return False

    def should_renew_certificate(self, threshold_hours: int = 24) -> bool:
        """
        Check if certificate should be renewed.

        Args:
            threshold_hours: Renew if less than this many hours until expiry

        Returns:
            True if certificate should be renewed
        """
        if not self.join_certificate:
            return False

        time_until_expiry = self.join_certificate.expires_at - datetime.now(timezone.utc)
        return time_until_expiry < timedelta(hours=threshold_hours)

    def run(
        self,
        na_endpoint: str,
        heartbeat_interval: int = 30,
        renewal_threshold_hours: int = 24
    ):
        """
        Run the node in persistent mode with heartbeats and auto-renewal.

        Args:
            na_endpoint: Network Authority endpoint
            heartbeat_interval: Seconds between heartbeats
            renewal_threshold_hours: Renew cert if less than this many hours remain
        """
        run_persistent_node(
            self,
            na_endpoint,
            heartbeat_interval=heartbeat_interval,
            renewal_threshold_hours=renewal_threshold_hours,
        )

    def stop(self):
        """Stop the node's run loop."""
        self._running = False
