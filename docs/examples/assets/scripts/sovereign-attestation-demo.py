"""Run a local two-sovereign membership attestation smoke demo.

The demo intentionally runs both sovereigns in one Python process so it is fast
and repeatable in CI or from a laptop. Each sovereign still has its own genesis
block, Network Authority key, operator key, SQLite database, and local
recognition policy.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.encoding
import nacl.signing

from genesis_mesh.crypto import KeyPair, generate_keypair, sign_data
from genesis_mesh.models import (
    GenesisBlock,
    NetworkAuthority,
    PolicyManifestRef,
    RecognitionPolicy,
    RecognizedIssuer,
)
from genesis_mesh.na_service.server import NetworkAuthorityService


def _admin_headers(body: dict, operator_keypair: KeyPair, key_id: str) -> dict:
    """Create operator-auth headers for an admin request body."""
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {
            "body": body,
            "key_id": key_id,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": sign_data(
            canonical.encode("utf-8"),
            operator_keypair.private_key,
        ),
    }


def _new_sovereign(name: str, db_path: Path) -> tuple[NetworkAuthorityService, KeyPair]:
    """Create an isolated Network Authority for a sovereign trust domain."""
    na_key = nacl.signing.SigningKey.generate()
    operator_keypair = generate_keypair()
    na_public_key = na_key.verify_key.encode(
        encoder=nacl.encoding.Base64Encoder,
    ).decode("utf-8")
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name=name,
        network_version="v0.9-demo",
        root_public_key=na_public_key,
        network_authority=NetworkAuthority(
            public_key=na_public_key,
            valid_from=now,
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:demo", url=None),
    )
    service = NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=na_key,
        key_id=f"{name}-na-key",
        db_path=str(db_path),
        operator_public_keys={f"{name}-operator": operator_keypair.public_key_b64},
    )
    service.app.config["TESTING"] = True
    return service, operator_keypair


def _post_admin(client, path: str, body: dict, operator: KeyPair, key_id: str):
    """Post an operator-authenticated admin request."""
    return client.post(path, json=body, headers=_admin_headers(body, operator, key_id))


def main() -> int:
    """Execute the two-sovereign attestation flow and print proof."""
    with tempfile.TemporaryDirectory(prefix="gm-sovereign-demo-", ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        sovereign_a, operator_a = _new_sovereign("sovereign-a", tmp_path / "a.db")
        sovereign_b, operator_b = _new_sovereign("sovereign-b", tmp_path / "b.db")
        client_a = sovereign_a.app.test_client()
        client_b = sovereign_b.app.test_client()

        try:
            print("==> Sovereigns initialized")
            print("    sovereign-a: independent genesis, NA key, operator key, DB")
            print("    sovereign-b: independent genesis, NA key, operator key, DB")

            issue_body = {
                "subject_id": "alice",
                "subject_public_key": "alice-public-key",
                "roles": ["role:service:maintainer"],
                "claims": {"project": "demo-package"},
                "validity_hours": 24,
            }
            issue = _post_admin(
                client_a,
                "/admin/attestations",
                issue_body,
                operator_a,
                "sovereign-a-operator",
            )
            if issue.status_code != 201:
                raise RuntimeError(f"issue failed: {issue.status_code} {issue.get_data(as_text=True)}")
            attestation = issue.get_json()
            print("\n==> Sovereign A issued membership attestation")
            print(f"    attestation: {attestation['attestation_id']}")
            print(f"    subject:     {attestation['subject_id']}")
            print(f"    roles:       {', '.join(attestation['roles'])}")

            policy = RecognitionPolicy(
                local_sovereign_id="sovereign-b",
                recognized_issuers=[
                    RecognizedIssuer(
                        sovereign_id="sovereign-a",
                        public_keys=[sovereign_a.genesis_block.network_authority.public_key],
                        allowed_roles=["role:service:maintainer"],
                    )
                ],
            )
            policy_body = {
                "policy_id": "sovereign-b-recognizes-a",
                "recognition_policy": json.loads(policy.model_dump_json()),
            }
            save_policy = _post_admin(
                client_b,
                "/admin/recognition-policy",
                policy_body,
                operator_b,
                "sovereign-b-operator",
            )
            if save_policy.status_code != 200:
                raise RuntimeError(
                    f"policy save failed: {save_policy.status_code} {save_policy.get_data(as_text=True)}"
                )
            print("\n==> Sovereign B recognized Sovereign A locally")
            print("    policy: sovereign-b-recognizes-a")

            accepted = client_b.post("/attestations/verify", json={"attestation": attestation})
            accepted_json = accepted.get_json()
            if accepted_json["reason"] != "accepted":
                raise RuntimeError(f"expected acceptance, got {accepted_json}")
            print("\n==> Sovereign B verified A's attestation")
            print(f"    accepted: {accepted_json['accepted']}")
            print(f"    reason:   {accepted_json['reason']}")

            revoke_body = {"reason": "membership_removed"}
            revoke = _post_admin(
                client_a,
                f"/admin/attestations/{attestation['attestation_id']}/revoke",
                revoke_body,
                operator_a,
                "sovereign-a-operator",
            )
            if revoke.status_code != 200:
                raise RuntimeError(f"revoke failed: {revoke.status_code} {revoke.get_data(as_text=True)}")
            print("\n==> Sovereign A revoked the attestation")
            print(f"    reason: {revoke_body['reason']}")

            revoked_policy = policy.model_copy(
                update={"revoked_attestation_ids": {attestation["attestation_id"]}}
            )
            revoked_policy_body = {
                "policy_id": "sovereign-b-recognizes-a",
                "recognition_policy": json.loads(revoked_policy.model_dump_json()),
            }
            save_revoked_policy = _post_admin(
                client_b,
                "/admin/recognition-policy",
                revoked_policy_body,
                operator_b,
                "sovereign-b-operator",
            )
            if save_revoked_policy.status_code != 200:
                raise RuntimeError(
                    "revocation input failed: "
                    f"{save_revoked_policy.status_code} {save_revoked_policy.get_data(as_text=True)}"
                )
            rejected = client_b.post("/attestations/verify", json={"attestation": attestation})
            rejected_json = rejected.get_json()
            if rejected_json["reason"] != "locally_revoked":
                raise RuntimeError(f"expected revocation rejection, got {rejected_json}")
            print("\n==> Sovereign B rejected the same attestation after revocation input")
            print(f"    accepted: {rejected_json['accepted']}")
            print(f"    reason:   {rejected_json['reason']}")

            print("\nResult: cross-sovereign membership trust is portable and revocable.")
            return 0
        finally:
            sovereign_a.db.conn.close()
            sovereign_b.db.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
