"""Peer certificate and announcement identity helpers for node runtimes."""

import base64
import time
import uuid
from typing import Optional

from ..crypto import public_key_from_b64, sign_data, verify_model_signature, verify_signature
from ..gossip.crl_gossip import CRLGossip
from ..models.certificates import JoinCertificate
from ..transport.noise_handshake import NoiseHandshake
from ..transport.protocol import PeerInfo


class RuntimePeerIdentity:
    """Validate peer identity material for a running mesh node."""

    def __init__(
        self,
        node,
        node_id: str,
        crl_gossip: CRLGossip,
        peer_certs_by_id: dict[str, JoinCertificate],
        peer_certs_by_node_id: dict[str, JoinCertificate],
    ):
        """Bind identity validation to runtime certificate and CRL state."""
        self.node = node
        self.node_id = node_id
        self.crl_gossip = crl_gossip
        self.peer_certs_by_id = peer_certs_by_id
        self.peer_certs_by_node_id = peer_certs_by_node_id

    def validate_peer_cert(
        self,
        remote_cert_b64: str,
        remote_static_pub: bytes,
    ) -> JoinCertificate:
        """Validate a peer certificate and bind it to the Noise static key."""
        try:
            cert_json = base64.b64decode(remote_cert_b64.encode("utf-8"))
            cert = JoinCertificate.model_validate_json(cert_json)
        except Exception as exc:
            raise ValueError(f"Invalid peer certificate payload: {exc}") from exc

        if cert.network_name != self.node.genesis_block.network_name:
            raise ValueError("Peer certificate network mismatch")
        if not cert.is_valid():
            raise ValueError("Peer certificate is expired or not yet valid")
        if self.crl_gossip.is_certificate_revoked(cert.cert_id):
            raise ValueError("Peer certificate is revoked")

        na_public_key = public_key_from_b64(
            self.node.genesis_block.network_authority.public_key
        )
        if not any(
            verify_model_signature(cert, signature, na_public_key)
            for signature in cert.signatures
        ):
            raise ValueError("Peer certificate signature is invalid")

        verify_key = public_key_from_b64(cert.node_public_key)
        expected_static_pub = NoiseHandshake.public_key_from_join_cert_key(verify_key)
        if expected_static_pub != remote_static_pub:
            raise ValueError("Peer certificate key does not match Noise static key")

        return cert

    def local_peer_info(self, endpoint: str) -> PeerInfo:
        """Return the local peer announcement before signing."""
        cert = self.node.join_certificate
        if not cert:
            raise ValueError("Node has no join certificate")
        return PeerInfo(
            node_id=self.node_id,
            endpoint=endpoint,
            roles=cert.roles,
            cert_id=cert.cert_id,
            certificate_b64=self.certificate_b64(cert),
            announcement_issued_at=time.time(),
            announcement_nonce=str(uuid.uuid4()),
        )

    def sign_peer_info(self, peer_info: PeerInfo) -> PeerInfo:
        """Sign a local peer announcement with the node identity key."""
        peer_info.announcement_signature = sign_data(
            peer_info.announcement_canonical_json().encode("utf-8"),
            self.node.node_keypair.private_key,
        )
        return peer_info

    def verify_peer_info(self, peer_info: PeerInfo) -> tuple[bool, list[str]]:
        """Verify a peer announcement and return roles from its certificate."""
        cert = self.certificate_for_peer_info(peer_info)
        if not cert:
            return False, []
        if cert.node_public_key != peer_info.node_id:
            return False, []
        if cert.cert_id != peer_info.cert_id:
            return False, []
        if cert.network_name != self.node.genesis_block.network_name:
            return False, []
        if not cert.is_valid():
            return False, []
        if self.crl_gossip.is_certificate_revoked(cert.cert_id):
            return False, []

        na_public_key = public_key_from_b64(
            self.node.genesis_block.network_authority.public_key
        )
        if not any(
            verify_model_signature(cert, signature, na_public_key)
            for signature in cert.signatures
        ):
            return False, []
        if not peer_info.announcement_signature:
            return False, []
        if not verify_signature(
            peer_info.announcement_canonical_json().encode("utf-8"),
            peer_info.announcement_signature,
            cert.node_public_key,
        ):
            return False, []

        self.peer_certs_by_id[cert.cert_id] = cert
        self.peer_certs_by_node_id[cert.node_public_key] = cert
        return True, cert.roles

    def is_peer_revoked(self, node_id: str) -> bool:
        """Return whether a known peer node ID maps to a revoked certificate."""
        cert = self.peer_certs_by_node_id.get(node_id)
        return bool(cert and self.crl_gossip.is_certificate_revoked(cert.cert_id))

    def certificate_for_peer_info(
        self,
        peer_info: PeerInfo,
    ) -> Optional[JoinCertificate]:
        """Resolve an embedded or previously known peer announcement certificate."""
        if peer_info.certificate_b64:
            try:
                cert_json = base64.b64decode(peer_info.certificate_b64.encode("utf-8"))
                return JoinCertificate.model_validate_json(cert_json)
            except Exception:
                return None
        if peer_info.cert_id and peer_info.cert_id in self.peer_certs_by_id:
            return self.peer_certs_by_id[peer_info.cert_id]
        return self.peer_certs_by_node_id.get(peer_info.node_id)

    def local_cert_b64(self) -> str:
        """Return the local join certificate encoded for a Noise payload."""
        if not self.node.join_certificate:
            raise ValueError("Node has no join certificate")
        return self.certificate_b64(self.node.join_certificate)

    def noise_keypair(self):
        """Return the local Noise static keypair derived from the node key."""
        return NoiseHandshake.keypair_from_join_cert_key(
            self.node.node_keypair.private_key
        )

    @staticmethod
    def certificate_b64(cert: JoinCertificate) -> str:
        """Return a join certificate encoded for transport and discovery payloads."""
        return base64.b64encode(cert.model_dump_json().encode("utf-8")).decode("utf-8")
