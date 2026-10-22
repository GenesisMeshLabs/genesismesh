"""Run the pre-issued grants walkthrough against a real local Network Authority.

Starts a temporary NA with ``EVIDENCE_STORE=on``, ``EVIDENCE_OUT_OF_BAND=on``
and ``EVIDENCE_GRANTS=on``, activates a policy capping secret lifetimes at
90 days and registers a device key, then: issues a grant (lifetimes 1 to
60 days, three uses) and shows a 1 to 400 day envelope refused, signs two
uses offline, asks for a fresh time token, uploads the uses, shows a third
use outside the envelope quarantined, lists the grant's uses, has an
observer's reports of the two rotations matched to the uses, activates a
stricter policy that revokes the grant, and verifies an audit pack of the
store offline.

    python docs/examples/assets/scripts/pre-issued-grants-demo.py

The transcript goes to ``docs/examples/assets/images/genesis-mesh-pre-issued-grants.txt``
and, with Pillow installed, the GIF next to it. ``--no-gif`` skips the GIF.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone

import nacl.encoding
import nacl.signing

from _local_na import LocalNA, Session, error_code
from genesis_mesh.crypto import sign_model
from genesis_mesh.models.grants import CapabilityGrant, GrantExecutionEvidence, TimeToken, TimeTokenRequest
from genesis_mesh.models.out_of_band import ObservationRecord

CAPABILITY = "secret.manage"
SECRET = "kv:site-7/api-key"
SETTINGS = {"EVIDENCE_STORE": "on", "EVIDENCE_OUT_OF_BAND": "on", "EVIDENCE_GRANTS": "on"}


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(maximum: int) -> dict:
    return {"lifetime_days": {"number_range": {"number_type": "integer", "minimum": 1, "maximum": maximum}}}


def _policy(na: LocalNA, policy_id: str, max_days: int, now: datetime) -> tuple[int, dict]:
    status, policy = na.admin("POST", "/admin/boundary-policies", {
        "policy_id": policy_id, "description": "cap secret lifetimes",
        "valid_from": _iso(now - timedelta(hours=1)), "valid_until": _iso(now + timedelta(days=30)),
        "selector": {"capabilities": [CAPABILITY]},
        "gates": [{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.lifetime_days", "max": max_days}}]})
    return na.admin("POST", f"/admin/boundary-policies/{policy_id}/activate", {"version": policy["version"]})


class Device:
    """The site-7 device: its executor key, its grant, its time token and its use chain."""

    def __init__(self) -> None:
        self.key = nacl.signing.SigningKey.generate()
        self.public_key = self.key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
        self.grant: CapabilityGrant | None = None
        self.token: TimeToken | None = None
        self.uses: list[GrantExecutionEvidence] = []

    def use(self, lifetime: int, version: str) -> GrantExecutionEvidence:
        record = GrantExecutionEvidence(
            grant_id=self.grant.grant_id, grant_digest=self.grant.digest(), use_sequence=len(self.uses) + 1,
            prev_use_digest=self.uses[-1].digest() if self.uses else None, executor_sovereign_id="site-7",
            capability=CAPABILITY, request_parameters={"lifetime_days": lifetime}, resource_id=SECRET,
            resource_action="rotate", executed_at=datetime.now(timezone.utc), time_token=self.token,
            outcome="success", execution_parameters={"version_id": version},
        )
        signed = record.model_copy(update={"signature": sign_model(record, self.key, "site-7-device")})
        self.uses.append(signed)
        return signed

    def time_token_request(self) -> dict:
        record = TimeTokenRequest(grant_id=self.grant.grant_id, use_sequence=len(self.uses),
                                  use_head_digest=self.uses[-1].digest() if self.uses else None,
                                  requested_at=datetime.now(timezone.utc))
        return record.model_copy(update={"signature": sign_model(record, self.key, "site-7-device")}).to_wire()


def run(na: LocalNA, s: Session) -> None:
    now = datetime.now(timezone.utc)
    device = Device()

    s.step("1. The policy and the device's key")
    s.cmd("genesis-mesh na start --env-file na.env")
    s.dim("  EVIDENCE_STORE=on  EVIDENCE_OUT_OF_BAND=on  EVIDENCE_GRANTS=on")
    status, _ = _policy(na, "secret-lifetime", 90, now)
    s.cmd("POST /admin/boundary-policies  (secret-lifetime: lifetime_days <= 90), then activate")
    s.ok(f"{status}: secret-lifetime v1 active")
    status, _ = na.admin("POST", "/admin/evidence/executor-keys", {
        "key_id": "site-7-device", "public_key": device.public_key, "executor_sovereign_id": "site-7"})
    s.cmd('POST /admin/evidence/executor-keys {"key_id": "site-7-device", ...}')
    s.ok(f"{status}: device key registered")
    _, attestation = na.admin("POST", "/admin/attestations", {
        "subject_id": "vendor-acme", "roles": ["role:client"], "claims": {"capabilities": [CAPABILITY]}})

    s.step("2. The grant: four hours, three uses, lifetimes 1 to 60 days")
    grant_body = {
        "bearer_key_id": "site-7-device", "capabilities": [CAPABILITY],
        "attestation_id": attestation["attestation_id"], "valid_until": _iso(now + timedelta(hours=4)),
        "max_uses": 3, "max_uses_per_time_token": 2, "parameter_envelope": _envelope(60)}
    status, body = na.admin("POST", "/admin/grants", grant_body)
    s.cmd("POST /admin/grants  (lifetime_days 1..60, max_uses 3, max_uses_per_time_token 2)")
    device.grant = CapabilityGrant.model_validate(body["grant"])
    device.token = TimeToken.model_validate(body["time_token"])
    gates = ", ".join(f"{g['gate_id']}={g['outcome']}" for g in body["grant"]["policy_binding"]["gate_outcomes"])
    s.ok(f"{status}: grant {device.grant.grant_id[:8]}..., bound to secret-lifetime v1 ({gates})")
    status, body = na.admin("POST", "/admin/grants", {**grant_body, "parameter_envelope": _envelope(400)})
    s.cmd("POST /admin/grants  (lifetime_days 1..400)")
    s.no(f"{status} {error_code(body)}")

    s.step("3. Offline: two rotations, signed by the device")
    time.sleep(1)
    first = device.use(30, "v8")
    second = device.use(30, "v9")
    for use in (first, second):
        s.text(f"  use {use.use_sequence}: rotate {SECRET} lifetime_days=30 "
               f"version_id={use.execution_parameters['version_id']}")

    s.step("4. Reconnecting")
    status, body = na.public("POST", "/grants/time-tokens", {"request": device.time_token_request()})
    s.cmd('POST /grants/time-tokens  {"use_sequence": 2, "use_head_digest": "<second.digest()>"}')
    s.ok(f"{status}: fresh time token, use_sequence {body['time_token']['use_sequence']}")
    device.token = TimeToken.model_validate(body["time_token"])
    for use in (first, second):
        status, body = na.public("POST", "/evidence/grant-executions", {"evidence": use.to_wire()})
        s.cmd(f"POST /evidence/grant-executions  (use {use.use_sequence})")
        s.ok(f"{status}: resource_sequence {body.get('resource_sequence', error_code(body))}")
    third = device.use(400, "v10")
    status, body = na.public("POST", "/evidence/grant-executions", {"evidence": third.to_wire()})
    s.cmd("POST /evidence/grant-executions  (use 3, lifetime_days=400)")
    s.no(f"{status} {error_code(body)}, kept as quarantine {body['error']['details']['quarantine_id'][:8]}...")
    _, uses = na.admin("GET", f"/admin/grants/{device.grant.grant_id}/uses")
    s.cmd("GET /admin/grants/<grant_id>/uses")
    for use in uses["uses"]:
        if use["state"] == "quarantined":
            s.no(f"use {use['use_sequence']}  {use['state']}  {use.get('rejection_code')}")
        else:
            s.text(f"  use {use['use_sequence']}  {use['state']}")

    s.step("5. The observer agrees")
    observer_key = nacl.signing.SigningKey.generate()
    na.admin("POST", "/admin/evidence/executor-keys", {
        "key_id": "activity-log-observer", "executor_sovereign_id": "cloud-observer", "role": "observer",
        "public_key": observer_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()})
    for use in (first, second):
        version = use.execution_parameters["version_id"]
        seen = ObservationRecord(
            observer_sovereign_id="cloud-observer", resource_id=SECRET, action="rotate", capability=CAPABILITY,
            changed_at=use.executed_at, observed_at=datetime.now(timezone.utc), actor="site-7",
            source="cloud-activity-log", source_event_id=f"event-{version}", version_id=version,
            metadata={"lifetime_days": 30})
        seen = seen.model_copy(update={"signature": sign_model(seen, observer_key, "activity-log-observer")})
        status, body = na.public("POST", "/evidence/observations", {"observation": seen.to_wire()})
        judgement = body["judgement"]["payload"]
        s.cmd(f"POST /evidence/observations  (rotate {version})")
        (s.ok if judgement["verdict"] == "allow" else s.no)(
            f"{status}: governed_by={judgement['governed_by']} verdict={judgement['verdict']}")

    s.step("6. A stricter policy revokes the grant")
    status, _ = _policy(na, "tighter", 30, now)
    s.cmd("POST /admin/boundary-policies  (tighter: lifetime_days <= 30), then activate")
    s.ok(f"{status}: tighter v1 active")
    _, grant = na.admin("GET", f"/admin/grants/{device.grant.grant_id}")
    s.cmd("GET /admin/grants/<grant_id>")
    revocation = grant.get("revocation") or {}
    s.no(f"status={grant['status']} reason={revocation.get('reason')}")
    _, feed = na.public("GET", "/sovereign-revocation-feed")
    s.cmd("GET /sovereign-revocation-feed")
    s.text(f"  sequence={feed['sequence']} revoked_grant_ids={[g[:8] + '...' for g in feed.get('revoked_grant_ids') or []]}")

    s.step("7. The audit")
    code, out = na.cli("evidence", "anchors", "fetch", "--na", na.base, "--na-public-key", "home/keys/na.pub",
                       "--out", "anchors", "--anchor-now", "--operator-key", "home/keys/operator.key",
                       "--operator-key-id", "operator-local")
    s.cmd("genesis-mesh evidence anchors fetch ... --out anchors --anchor-now")
    s.output(out)
    code, out = na.cli("audit", "pack", "--na", na.base, "--out", "pack", "--from-sequence", "1",
                       "--operator-key", "home/keys/operator.key", "--operator-key-id", "operator-local")
    s.cmd("genesis-mesh audit pack --na http://127.0.0.1:18454 --out pack --from-sequence 1 ...")
    s.output(out, keep=3)
    code, out = na.cli("audit", "verify", "pack", "--anchor", "home/keys/root.pub", "--known-anchors", "anchors")
    s.cmd("genesis-mesh audit verify pack --anchor home/keys/root.pub --known-anchors anchors")
    s.output(out, ok=("Result     : VERIFIED",), no=("FAILED",))
    s.dim(f"exit {code}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18454, help="port for the temporary NA")
    parser.add_argument("--no-gif", action="store_true", help="write the transcript only")
    args = parser.parse_args()
    session = Session()
    with LocalNA(args.port, SETTINGS) as na:
        run(na, session)
    session.save("pre-issued-grants", "Genesis Mesh -- Pre-Issued Grants", render=not args.no_gif)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
