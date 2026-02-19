"""Network Authority REST API server."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import uuid

from flask import Flask, request, jsonify
import nacl.signing

from ..models import GenesisBlock, JoinCertificate, PolicyManifest
from ..crypto import load_private_key, sign_model, verify_model_signature

logger = logging.getLogger(__name__)


class NetworkAuthorityService:
    """
    Network Authority service for issuing and managing certificates.

    This service:
    - Issues short-lived join certificates to nodes
    - Signs policy manifests
    - Tracks connected nodes via heartbeats
    - Maintains audit logs of all operations
    """

    def __init__(
        self,
        genesis_block: GenesisBlock,
        na_private_key: nacl.signing.SigningKey,
        key_id: str = "na-2025-q1"
    ):
        """
        Initialize Network Authority service.

        Args:
            genesis_block: Genesis block for the network
            na_private_key: Network Authority private key
            key_id: Key identifier for signing
        """
        self.genesis_block = genesis_block
        self.na_private_key = na_private_key
        self.key_id = key_id
        self.app = Flask(__name__)
        self._setup_routes()

        # Track connected nodes: {cert_id: {node_info}}
        self.connected_nodes: dict[str, dict] = {}

        # Verify NA key matches genesis block
        na_pub_b64 = genesis_block.network_authority.public_key
        our_pub_b64 = self.na_private_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode('utf-8')

        if na_pub_b64 != our_pub_b64:
            raise ValueError("NA private key does not match genesis block")

        logger.info(f"Network Authority service initialized for network: {genesis_block.network_name}")

    VALID_ROLE_PREFIXES = ['role:anchor', 'role:bridge', 'role:client', 'role:operator', 'role:service:']

    def _validate_roles(self, roles: list[str]) -> tuple[bool, str | None]:
        """
        Validate that all roles use allowed prefixes.

        Returns:
            (is_valid, error_message) tuple
        """
        for role in roles:
            if not any(role.startswith(prefix) for prefix in self.VALID_ROLE_PREFIXES):
                return False, f"Invalid role: {role}"
        return True, None

    def _setup_routes(self):
        """Set up Flask routes."""

        @self.app.route('/health', methods=['GET'])
        def health():
            """Health check endpoint."""
            return jsonify({
                "status": "healthy",
                "network": self.genesis_block.network_name,
                "version": self.genesis_block.network_version
            })

        @self.app.route('/genesis', methods=['GET'])
        def get_genesis():
            """Return the genesis block."""
            return jsonify(self.genesis_block.model_dump(mode='json'))

        @self.app.route('/join', methods=['POST'])
        def request_join():
            """
            Issue a join certificate.

            Expected JSON body:
            {
                "node_public_key": "<base64-key>",
                "roles": ["role:anchor"],
                "validity_hours": 168  // optional, default 168 (7 days)
            }
            """
            try:
                data = request.json
                node_public_key = data.get('node_public_key')
                roles = data.get('roles', ['role:client'])
                validity_hours = data.get('validity_hours', 168)  # 7 days default

                if not node_public_key:
                    return jsonify({"error": "node_public_key required"}), 400

                # Validate roles
                valid, error = self._validate_roles(roles)
                if not valid:
                    return jsonify({"error": error}), 400

                # Create join certificate
                cert = self._issue_join_certificate(
                    node_public_key=node_public_key,
                    roles=roles,
                    validity_hours=validity_hours
                )

                # Track the issued certificate's roles and key binding
                self.connected_nodes[cert.cert_id] = {
                    "node_public_key": node_public_key,
                    "roles": roles,
                    "status": "joined",
                    "last_heartbeat": datetime.utcnow().isoformat(),
                    "remote_addr": request.remote_addr
                }

                logger.info(f"Issued join certificate {cert.cert_id} for roles {roles}")

                return jsonify(cert.model_dump(mode='json')), 201

            except Exception as e:
                logger.error(f"Error issuing certificate: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/policy', methods=['GET'])
        def get_policy():
            """Return the current policy manifest."""
            # For MVP, return a default policy
            policy = self._get_default_policy()
            return jsonify(policy.model_dump(mode='json'))

        @self.app.route('/heartbeat', methods=['POST'])
        def heartbeat():
            """
            Receive heartbeat from a node.

            Expected JSON body:
            {
                "cert_id": "<certificate-id>",
                "node_public_key": "<base64-key>",
                "status": "healthy"
            }
            """
            try:
                data = request.json
                cert_id = data.get('cert_id')
                node_public_key = data.get('node_public_key')
                status = data.get('status', 'unknown')

                if not cert_id or not node_public_key:
                    return jsonify({"error": "cert_id and node_public_key required"}), 400

                # Update node tracking
                now = datetime.utcnow()
                self.connected_nodes[cert_id] = {
                    "node_public_key": node_public_key,
                    "status": status,
                    "last_heartbeat": now.isoformat(),
                    "remote_addr": request.remote_addr
                }

                logger.debug(f"Heartbeat from node {cert_id[:8]}... status={status}")

                return jsonify({
                    "ack": True,
                    "server_time": now.isoformat()
                })

            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/renew', methods=['POST'])
        def renew_certificate():
            """
            Renew a node's join certificate.

            Roles are preserved from the original certificate. Clients cannot
            escalate privileges by requesting different roles during renewal.

            Expected JSON body:
            {
                "cert_id": "<current-certificate-id>",
                "node_public_key": "<base64-key>",
                "validity_hours": 168
            }
            """
            try:
                data = request.json
                cert_id = data.get('cert_id')
                node_public_key = data.get('node_public_key')
                validity_hours = data.get('validity_hours', 168)

                if not cert_id or not node_public_key:
                    return jsonify({"error": "cert_id and node_public_key required"}), 400

                # Require the cert to be known — unknown certs cannot be renewed
                if cert_id not in self.connected_nodes:
                    logger.warning(f"Renewal request from unknown cert {cert_id[:8]}...")
                    return jsonify({"error": "Unknown certificate. Cannot renew."}), 403

                existing_node = self.connected_nodes[cert_id]

                # Verify the public key matches what was originally registered
                if existing_node.get("node_public_key") != node_public_key:
                    logger.warning(
                        f"Renewal key mismatch for cert {cert_id[:8]}...: "
                        f"expected {existing_node.get('node_public_key', '?')[:8]}, "
                        f"got {node_public_key[:8]}"
                    )
                    return jsonify({"error": "Public key does not match certificate"}), 403

                # Roles are always preserved from server-side state — ignore
                # any client-supplied roles to prevent privilege escalation
                roles = existing_node.get('roles', ['role:client'])

                if 'roles' in data and sorted(data['roles']) != sorted(roles):
                    logger.warning(
                        f"Renewal role escalation attempt for cert {cert_id[:8]}...: "
                        f"requested {data['roles']}, authorized {roles}"
                    )
                    return jsonify({
                        "error": "Role changes are not permitted during renewal"
                    }), 403

                # Issue new certificate with preserved roles
                new_cert = self._issue_join_certificate(
                    node_public_key=node_public_key,
                    roles=roles,
                    validity_hours=validity_hours
                )

                # Update node tracking with new cert
                old_info = self.connected_nodes.pop(cert_id)
                self.connected_nodes[new_cert.cert_id] = {
                    **old_info,
                    "renewed_from": cert_id
                }

                logger.info(f"Renewed certificate {cert_id[:8]}... -> {new_cert.cert_id[:8]}...")

                return jsonify(new_cert.model_dump(mode='json')), 201

            except Exception as e:
                logger.error(f"Renewal error: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/nodes', methods=['GET'])
        def list_nodes():
            """Return list of connected nodes (for debugging/monitoring)."""
            # Clean up stale nodes (no heartbeat in 5 minutes)
            now = datetime.utcnow()
            stale_threshold = timedelta(minutes=5)
            active_nodes = {}

            for cert_id, info in self.connected_nodes.items():
                last_hb = datetime.fromisoformat(info['last_heartbeat'])
                if now - last_hb < stale_threshold:
                    active_nodes[cert_id] = info

            self.connected_nodes = active_nodes

            return jsonify({
                "count": len(active_nodes),
                "nodes": active_nodes
            })

    def _issue_join_certificate(
        self,
        node_public_key: str,
        roles: list[str],
        validity_hours: int
    ) -> JoinCertificate:
        """
        Issue a join certificate to a node.

        Args:
            node_public_key: Node's public key (base64)
            roles: List of roles to assign
            validity_hours: Certificate validity in hours

        Returns:
            Signed JoinCertificate
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=validity_hours)

        cert = JoinCertificate(
            cert_id=str(uuid.uuid4()),
            node_public_key=node_public_key,
            network_name=self.genesis_block.network_name,
            roles=roles,
            issued_at=now,
            expires_at=expires_at,
            issued_by=self.key_id,
            signatures=[]
        )

        # Sign the certificate
        signature = sign_model(cert, self.na_private_key, self.key_id)
        cert.signatures.append(signature)

        return cert

    def _get_default_policy(self) -> PolicyManifest:
        """Get the default policy manifest for MVP."""
        now = datetime.utcnow()

        policy = PolicyManifest(
            policy_id=f"policy-{self.genesis_block.network_name}-{self.genesis_block.network_version}",
            issued_at=now,
            issued_by=self.key_id,
            min_client_version="0.1.0",
            allowed_ports=[443, 8443],
            allowed_services=["service‑1", "service‑2"]
        )

        # Sign the policy
        signature = sign_model(policy, self.na_private_key, self.key_id)
        policy.signatures.append(signature)

        return policy

    def run(self, host: str = '0.0.0.0', port: int = 8443, **kwargs):
        """
        Run the Network Authority service.

        Args:
            host: Host to bind to
            port: Port to bind to
            **kwargs: Additional arguments for Flask app.run()
        """
        logger.info(f"Starting Network Authority service on {host}:{port}")
        self.app.run(host=host, port=port, **kwargs)


def main():
    """CLI entry point for NA service."""
    import argparse

    parser = argparse.ArgumentParser(description='Network Authority Service')
    parser.add_argument('--genesis', required=True, help='Path to signed genesis block JSON')
    parser.add_argument('--na-private-key', required=True, help='Path to NA private key')
    parser.add_argument('--key-id', default='na-2025-q1', help='Key identifier')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8443, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

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

    # Load NA private key
    na_private_key = load_private_key(args.na_private_key)

    # Create and run service
    service = NetworkAuthorityService(
        genesis_block=genesis_block,
        na_private_key=na_private_key,
        key_id=args.key_id
    )

    service.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
