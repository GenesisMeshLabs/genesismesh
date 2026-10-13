"""Mesh node implementation."""

import json
import logging
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, List, Sequence

import requests

from ..crypto import (
    KeyPair,
    generate_keypair,
    public_key_from_b64,
    sign_data,
    verify_model_signature,
)
from ..models import GenesisBlock, JoinCertificate, PolicyManifest
from ..models.key_succession import NAKey, NAKeyHistory
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
        roles: Optional[List[str]] = None,
        key_history_cache: Optional[str | Path] = None,
    ):
        """
        Initialize a mesh node.

        Args:
            genesis_block: The network's genesis block
            node_keypair: Node's cryptographic keypair (generates new if None)
            roles: Node roles (default: ['role:client'])
            key_history_cache: File the NA's key history is kept in between runs (v1.5.0 review
                fixes); every read of it is verified from the genesis block's root key again
        """
        self.genesis_block = genesis_block
        self.node_keypair = node_keypair or generate_keypair()
        self.roles = roles or ['role:client']
        self.join_certificate: Optional[JoinCertificate] = None
        self.policy_manifest: Optional[PolicyManifest] = None
        self._running = False
        self._na_endpoint: Optional[str] = None
        self.key_history_cache = Path(key_history_cache) if key_history_cache else None

        # Verify genesis block signatures
        if not self._verify_genesis_block():
            raise ValueError("Genesis block signature verification failed")
        # v1.5.0 review fixes: the NA keys a node accepts follow the NA's key succession, verified
        # from the root key the genesis block names; until the node reads the history, the genesis key.
        self.key_history: NAKeyHistory = self._genesis_history()
        self._load_key_history_cache()

        logger.info(f"Node initialized for network: {genesis_block.network_name}")
        logger.info(f"Node public key: {self.node_keypair.public_key_b64}")
        logger.info(f"Requested roles before enrollment: {self.roles}")

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

    # -- the NA's key history (v1.5.0 review fixes) ------------------------------

    def _genesis_history(self) -> NAKeyHistory:
        authority = self.genesis_block.network_authority
        return NAKeyHistory(
            sovereign_id=self.genesis_block.network_name, root_public_key=self.genesis_block.root_public_key,
            keys=(NAKey(key_sequence=1, public_key=authority.public_key, key_id=None, valid_from=None,
                        succeeded_at=None, valid_to=authority.valid_to, valid_to_enforced=False),),
        )

    def adopt_key_history(self, successions: Sequence[Any]) -> bool:
        """Take the NA's successions when they verify from the root key the genesis block names and
        continue the history this node holds (a shorter or different history is refused)."""
        from ..trust.key_succession import verify_key_history

        result = verify_key_history(self.genesis_block.model_dump(mode="json"), list(successions),
                                    self.genesis_block.root_public_key)
        if not result.verified or result.history is None:
            failure = result.failures[0] if result.failures else {}
            logger.error("The NA's key history does not verify from the root key: %s", failure.get("reason"))
            return False
        held = [s.digest() for s in self.key_history.successions]
        offered = [s.digest() for s in result.history.successions]
        if offered[:len(held)] != held:
            logger.error("The NA's key history does not continue the one this node holds; keeping it")
            return False
        self.key_history = result.history
        if self.key_history_cache is not None and len(offered) > len(held):
            try:
                self.key_history_cache.parent.mkdir(parents=True, exist_ok=True)
                self.key_history_cache.write_text(
                    json.dumps({"successions": [s.to_wire() for s in result.history.successions]},
                               sort_keys=True, indent=2) + "\n", encoding="utf-8")
            except OSError as exc:
                logger.warning("Could not cache the NA key history: %s", exc)
        return True

    def _load_key_history_cache(self) -> None:
        if self.key_history_cache is None or not self.key_history_cache.is_file():
            return
        try:
            cached = json.loads(self.key_history_cache.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring the cached NA key history: %s", exc)
            return
        if isinstance(cached, dict) and isinstance(cached.get("successions"), list):
            self.adopt_key_history(cached["successions"])

    def refresh_key_history(self, na_endpoint: str) -> bool:
        """Read the NA's key history (``GET /na/key-history``) and adopt it when it verifies.

        An NA before 1.5.0 serves none: the genesis key stays the only one.
        """
        try:
            response = requests.get(f"{na_endpoint}/na/key-history", timeout=10)
        except requests.RequestException as exc:
            logger.warning("Could not read the NA key history: %s", exc)
            return False
        if response.status_code == 404:
            return False
        try:
            view = response.json()
        except ValueError:
            return False
        if not response.ok or not isinstance(view, dict) or not isinstance(view.get("successions"), list):
            return False
        return self.adopt_key_history(view["successions"])

    def na_keys_at(self, at: datetime) -> list[str]:
        """The NA public keys a record dated ``at`` may be signed with."""
        return self.key_history.keys_at(at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc))

    def verify_na_signed(self, model: Any, signatures: Sequence[Any], at: datetime) -> bool:
        """True when one of ``signatures`` is by the NA key valid at ``at`` (the record's issue time)."""
        return any(verify_model_signature(model, sig, key) for key in self.na_keys_at(at) for sig in signatures)

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
        self.refresh_key_history(na_endpoint)

        # Prepare join request
        request_data: dict[str, Any] = {
            "node_public_key": self.node_keypair.public_key_b64,
            "roles": self.roles,
            "validity_hours": validity_hours
        }
        if invite_token:
            request_data["invite_token"] = invite_token
        request_data = self._sign_request(request_data)

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

        # Verify signature: by the NA key valid when it was issued (v1.5.0 review fixes)
        if self.verify_na_signed(cert, cert.signatures, cert.issued_at):
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
        self.refresh_key_history(na_endpoint)

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
        if self.verify_na_signed(policy, policy.signatures, policy.issued_at):
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
