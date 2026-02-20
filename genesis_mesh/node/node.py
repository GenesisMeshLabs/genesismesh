"""Mesh node implementation."""

import json
import logging
import signal
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

import requests
import nacl.signing

from ..models import GenesisBlock, JoinCertificate, PolicyManifest
from ..crypto import (
    generate_keypair,
    KeyPair,
    load_private_key,
    load_public_key,
    verify_model_signature,
    public_key_from_b64,
    sign_data
)
import uuid as _uuid

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

    def join_network(self, na_endpoint: str, validity_hours: int = 168) -> JoinCertificate:
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
        request_data = {
            "node_public_key": self.node_keypair.public_key_b64,
            "roles": self.roles,
            "validity_hours": validity_hours
        }

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
        payload["timestamp"] = datetime.utcnow().isoformat()
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

        time_until_expiry = self.join_certificate.expires_at - datetime.utcnow()
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
        self._na_endpoint = na_endpoint
        self._running = True

        def signal_handler(signum, frame):
            logger.info("Shutdown signal received")
            self._running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info(f"Node running in persistent mode (heartbeat every {heartbeat_interval}s)")

        last_heartbeat = 0
        heartbeat_failures = 0
        max_failures = 5

        while self._running:
            now = time.time()

            # Send heartbeat
            if now - last_heartbeat >= heartbeat_interval:
                if self.send_heartbeat(na_endpoint):
                    heartbeat_failures = 0
                else:
                    heartbeat_failures += 1
                    logger.warning(f"Heartbeat failure {heartbeat_failures}/{max_failures}")

                    if heartbeat_failures >= max_failures:
                        logger.error("Too many heartbeat failures, attempting reconnect...")
                        # Try to rejoin
                        try:
                            self.join_network(na_endpoint)
                            heartbeat_failures = 0
                        except Exception as e:
                            logger.error(f"Reconnect failed: {e}")

                last_heartbeat = now

            # Check certificate renewal
            if self.should_renew_certificate(renewal_threshold_hours):
                logger.info("Certificate nearing expiry, renewing...")
                if not self.renew_certificate(na_endpoint):
                    logger.error("Certificate renewal failed!")

            # Sleep a bit before next iteration
            time.sleep(1)

        logger.info("Node shutdown complete")

    def stop(self):
        """Stop the node's run loop."""
        self._running = False


def main():
    """CLI entry point for mesh node."""
    import argparse

    parser = argparse.ArgumentParser(description='Genesis Mesh Node')
    parser.add_argument('--genesis', required=True,
                        help='Path to signed genesis block JSON')
    parser.add_argument('--node-key',
                        help='Path to node private key (generates new if not provided)')
    parser.add_argument('--bootstrap', required=True,
                        help='Network Authority endpoint for bootstrap')
    parser.add_argument('--role', action='append', dest='roles',
                        help='Node roles (can be specified multiple times)')
    parser.add_argument('--validity-hours', type=int, default=168,
                        help='Certificate validity hours')
    parser.add_argument('--persistent', action='store_true',
                        help='Run in persistent mode with heartbeats')
    parser.add_argument('--heartbeat-interval', type=int, default=30,
                        help='Heartbeat interval in seconds (default: 30)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load genesis block
    with open(args.genesis, 'r') as f:
        genesis_data = json.load(f)
        genesis_block = GenesisBlock(**genesis_data)

    # Load or generate node keypair
    node_keypair = None
    if args.node_key:
        private_key = load_private_key(args.node_key)
        node_keypair = KeyPair(
            private_key=private_key,
            public_key=private_key.verify_key
        )
        logger.info(f"Loaded node key from {args.node_key}")
    else:
        logger.info("Generating new node keypair")

    # Set roles (auto-prefix with 'role:' if not already prefixed)
    if args.roles:
        roles = [
            r if r.startswith('role:') else f'role:{r}'
            for r in args.roles
        ]
    else:
        roles = ['role:client']

    # Create node
    node = MeshNode(
        genesis_block=genesis_block,
        node_keypair=node_keypair,
        roles=roles
    )

    # Join network
    try:
        node.join_network(args.bootstrap, args.validity_hours)
        node.fetch_policy(args.bootstrap)

        # Print status
        status = node.get_status()
        print("\n=== Node Status ===")
        for key, value in status.items():
            print(f"{key}: {value}")

        logger.info("Node successfully joined the network")

        # Run in persistent mode if requested
        if args.persistent:
            print("\n=== Running in persistent mode (Ctrl+C to stop) ===")
            node.run(
                na_endpoint=args.bootstrap,
                heartbeat_interval=args.heartbeat_interval
            )

    except Exception as e:
        logger.error(f"Failed to join network: {e}")
        return 1

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
