"""A network with its own root key, for NA key succession and audit pack tests (v1.5.0).

``_make_service`` signs the genesis block with the NA key itself (the root key
is the NA key there). Succession needs the two apart: ``Network`` holds a root
key, one genesis block and a database, and starts the NA with any key, as a
restart with a succeeded key would.
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import nacl.signing

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.models.key_succession import KeySuccessionRecord, NAKeyHistory
from genesis_mesh.na_service.server import NetworkAuthorityService
from genesis_mesh.trust.key_succession import verify_key_history


def public_b64(key: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(key.verify_key)).decode("ascii")


class Network:
    """One sovereign: a root key, a genesis block naming the first NA key, a database file."""

    def __init__(self, tmp_path: Path, *, na_valid_to: datetime | None = None, name: str = "TEST") -> None:
        self.root = nacl.signing.SigningKey.generate()
        self.na_keys = [nacl.signing.SigningKey.generate()]
        self.privileged = generate_keypair()
        self.standard = generate_keypair()
        self.reader = generate_keypair()
        now = datetime.now(timezone.utc)
        genesis = GenesisBlock(
            network_name=name, network_version="v0.1", root_public_key=public_b64(self.root),
            network_authority=NetworkAuthority(public_key=public_b64(self.na_keys[0]),
                                               valid_from=now - timedelta(days=1),
                                               valid_to=na_valid_to or now + timedelta(days=90)),
            policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
        )
        genesis.signatures.append(sign_model(genesis, self.root, "root"))
        self.genesis = genesis
        self.db_path = str(tmp_path / "na.db")

    def start(self, key: nacl.signing.SigningKey | None = None, *, key_id: str | None = None,
              **kwargs: Any) -> NetworkAuthorityService:
        key = key or self.na_keys[-1]
        index = self.na_keys.index(key) if key in self.na_keys else 0
        settings: dict[str, Any] = {
            "evidence_store": "on", "operator_public_keys": {
                "operator-test": self.privileged.public_key_b64, "operator-std": self.standard.public_key_b64,
                "operator-read": self.reader.public_key_b64},
            "operator_key_tiers": {"operator-test": "privileged", "operator-std": "standard",
                                   "operator-read": "read"},
            **kwargs,
        }
        service = NetworkAuthorityService(
            genesis_block=self.genesis, na_private_key=key, key_id=key_id or f"na-{index + 1}",
            db_path=self.db_path, **settings,
        )
        setattr(service, "_test_operator_keypair", self.privileged)
        setattr(service, "_std_keypair", self.standard)
        setattr(service, "_read_keypair", self.reader)
        return service

    def history(self, service: NetworkAuthorityService) -> NAKeyHistory:
        """The key history the NA serves, verified from the root key held out of band."""
        view = service.key_history.public_view()
        result = verify_key_history(view["genesis"], view["successions"], public_b64(self.root))
        assert result.verified and result.history is not None, result.to_dict()
        return result.history

    def succession(self, service: NetworkAuthorityService, *, effective_in: float = 2.0, valid_days: float = 365,
                   new_key: nacl.signing.SigningKey | None = None, sign_with: nacl.signing.SigningKey | None = None,
                   prove: bool = True, **overrides: Any) -> tuple[dict[str, Any], nacl.signing.SigningKey]:
        """A succession record for a new NA key, signed by the root key (as offline) and, with
        ``prove``, by the new key (its proof of possession)."""
        history = self.history(service)
        current = history.keys[-1]
        new_key = new_key or nacl.signing.SigningKey.generate()
        now = datetime.now(timezone.utc)
        effective = now + timedelta(seconds=effective_in)
        fields: dict[str, Any] = {
            "sovereign_id": history.sovereign_id, "key_sequence": current.key_sequence + 1,
            "previous_key_id": current.key_id or "na", "previous_public_key": current.public_key,
            "previous_succession_digest": history.successions[-1].digest() if history.successions else None,
            "new_key_id": f"na-{current.key_sequence + 1}", "new_public_key": public_b64(new_key),
            "effective_at": effective, "new_valid_to": effective + timedelta(days=valid_days), "issued_at": now,
            **overrides,
        }
        record = KeySuccessionRecord(**fields)
        signatures = [sign_model(record, sign_with or self.root, "root")]
        if prove:
            signatures.append(sign_model(record, new_key, str(fields["new_key_id"])))
        record = record.model_copy(update={"signatures": signatures})
        return record.to_wire(), new_key

    def adopt(self, key: nacl.signing.SigningKey) -> None:
        self.na_keys.append(key)


def wait_until(at: str | datetime, margin: float = 0.05) -> None:
    """Sleep until a time (ISO 8601 or a datetime) has passed."""
    moment = datetime.fromisoformat(at.replace("Z", "+00:00")) if isinstance(at, str) else at
    delay = (moment - datetime.now(timezone.utc)).total_seconds() + margin
    if delay > 0:
        time.sleep(delay)
