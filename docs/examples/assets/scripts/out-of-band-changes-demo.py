"""Run the changes-outside-the-controlled-path walkthrough against a real local Network Authority.

Starts a temporary NA with ``EVIDENCE_STORE=on``, ``EVIDENCE_OUT_OF_BAND=on``
and ``EVIDENCE_REMEDIATION=on``, activates a policy capping secret lifetimes
at 90 days (a DENY of its gate is cancelled after an hour), then follows one
secret through three kinds of change: a governed rotation the observer
matches, a console rotation judged after the fact and denied, and a
break-glass rotation judged on arrival. It lists the secret's changes, then
remediates the denied one (notice, forward rotation, signed remediation
record) and verifies the export offline.

    python docs/examples/assets/scripts/out-of-band-changes-demo.py

The transcript goes to ``docs/examples/assets/images/genesis-mesh-out-of-band-changes.txt``
and, with Pillow installed, the GIF next to it. ``--no-gif`` skips the GIF.
"""

from __future__ import annotations

import argparse
import time
import uuid
from datetime import datetime, timedelta, timezone

import nacl.encoding
import nacl.signing

from _local_na import LocalNA, Session, error_code
from genesis_mesh.crypto import sign_model
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.out_of_band import BreakGlassRecord, ObservationRecord
from genesis_mesh.models.remediation import RemediationRecord
from genesis_mesh.trust.execution import record_execution

CAPABILITY = "secret.manage"
SECRET = "kv:vendor-acme/api-key"
SETTINGS = {"EVIDENCE_STORE": "on", "EVIDENCE_OUT_OF_BAND": "on", "EVIDENCE_REMEDIATION": "on"}


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Signer:
    """A registered executor key: the secrets controller or the activity-log observer."""

    def __init__(self, na: LocalNA, key_id: str, sovereign: str, **extra: str) -> None:
        self.key = nacl.signing.SigningKey.generate()
        self.key_id, self.sovereign = key_id, sovereign
        public_key = self.key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
        self.status, _ = na.admin("POST", "/admin/evidence/executor-keys", {
            "key_id": key_id, "public_key": public_key, "executor_sovereign_id": sovereign, **extra})

    def sign(self, record):
        return record.model_copy(update={"signature": sign_model(record, self.key, self.key_id)})


def observe(observer: Signer, version: str, lifetime: int, changed_at: datetime) -> ObservationRecord:
    return observer.sign(ObservationRecord(
        observer_sovereign_id=observer.sovereign, resource_id=SECRET, action="rotate", capability=CAPABILITY,
        changed_at=changed_at, observed_at=datetime.now(timezone.utc), actor="principal-7f3a",
        source="cloud-activity-log", source_event_id=f"event-{uuid.uuid4().hex[:8]}", version_id=version,
        metadata={"operation": "SetSecret", "lifetime_days": lifetime},
    ))


def judgement_line(s: Session, status: int, body: dict) -> dict:
    payload = body["judgement"]["payload"]
    line = (f"{status}: governed_by={payload['governed_by']} verdict={payload['verdict']}"
            + (f" ({payload['reason']})" if payload["verdict"] != "allow" and payload.get("reason") else ""))
    (s.ok if payload["verdict"] == "allow" else s.no)(line)
    return payload


def run(na: LocalNA, s: Session) -> None:
    now = datetime.now(timezone.utc)

    s.step("Start the NA with the out-of-band and remediation records on")
    s.cmd("genesis-mesh na start --env-file na.env")
    s.dim("  EVIDENCE_STORE=on  EVIDENCE_OUT_OF_BAND=on  EVIDENCE_REMEDIATION=on")
    status, policy = na.admin("POST", "/admin/boundary-policies", {
        "policy_id": "secret-lifetime", "description": "cap secret lifetimes",
        "valid_from": _iso(now - timedelta(hours=1)), "valid_until": _iso(now + timedelta(days=30)),
        "selector": {"capabilities": [CAPABILITY]},
        "gates": [{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.lifetime_days", "max": 90}}],
        "remediation": {"max-lifetime": {"mode": "cancel", "grace_seconds": 3600}},
    })
    na.admin("POST", "/admin/boundary-policies/secret-lifetime/activate", {"version": policy["version"]})
    s.cmd('POST /admin/boundary-policies  (lifetime_days <= 90; "remediation": cancel, 3600 s)')
    s.ok(f"{status}: secret-lifetime v{policy['version']}, activated")

    s.step("Register the controller and the observer")
    controller = Signer(na, "ctrl-1", "secrets-controller")
    observer = Signer(na, "activity-log-observer", "cloud-observer", role="observer",
                      resource_prefix="kv:vendor-acme/")
    s.cmd('POST /admin/evidence/executor-keys {"key_id": "ctrl-1", ...}')
    s.ok(f"{controller.status}: controller key")
    s.cmd('POST /admin/evidence/executor-keys {"key_id": "activity-log-observer", "role": "observer", '
          '"resource_prefix": "kv:vendor-acme/", ...}')
    s.ok(f"{observer.status}: observer key")
    _, attestation = na.admin("POST", "/admin/attestations", {
        "subject_id": "vendor-acme", "roles": ["role:client"], "claims": {"capabilities": [CAPABILITY]}})
    attestation_id = attestation["attestation_id"]
    time.sleep(1.5)  # every change below happens after the activation

    def governed_rotation(version: str, prior):
        _, body = na.admin("POST", "/admin/boundary/evaluate", {
            "attestation_id": attestation_id, "requested_capability": CAPABILITY,
            "context": {"request_parameters": {"lifetime_days": 30}}})
        decision = BoundaryDecision.model_validate(body["decision"])
        evidence = record_execution(
            decision, controller.sovereign, CAPABILITY, "success", controller.key, issued_by=controller.key_id,
            execution_parameters={"version_id": version}, resource_id=SECRET, resource_action="rotate",
            prior_resource_record=prior)
        status, body = na.public("POST", "/evidence/execution", {"evidence": evidence.model_dump(mode="json")})
        return decision, evidence, status, body

    s.step("1. A governed rotation, seen by the observer")
    decision, v7, status, body = governed_rotation("v7", None)
    s.cmd('POST /admin/boundary/evaluate {"lifetime_days": 30}')
    s.ok(f"201: authorized={decision.authorized}")
    s.cmd("POST /evidence/execution  (rotate, version_id v7)")
    (s.ok if status == 201 else s.no)(f"{status}: {body.get('entry', {}).get('entry_kind', error_code(body))}")
    time.sleep(1)
    status, body = na.public("POST", "/evidence/observations",
                             {"observation": observe(observer, "v7", 30, v7.executed_at).to_wire()})
    s.cmd("POST /evidence/observations  (rotate v7, seen in the activity log)")
    judgement_line(s, status, body)

    s.step("2. A rotation in the cloud console, lifetime 400 days")
    time.sleep(1)
    console = observe(observer, "v8", 400, datetime.now(timezone.utc) - timedelta(seconds=1))
    status, body = na.public("POST", "/evidence/observations", {"observation": console.to_wire()})
    s.cmd("POST /evidence/observations  (rotate v8, no execution record names it)")
    denied = judgement_line(s, status, body)
    remediation = body["judgement"].get("remediation") or {}
    s.text(f"  remediation: state={remediation.get('state')} mode={remediation.get('mode')} "
           f"steps={remediation.get('steps')}")

    s.step("3. A break-glass rotation while the NA was unreachable")
    record = controller.sign(BreakGlassRecord(
        executor_sovereign_id=controller.sovereign, resource_id=SECRET, resource_action="rotate",
        capability=CAPABILITY, attestation_id=attestation_id, request_parameters={"lifetime_days": 30},
        justification="Key leaked in a public repository; NA unreachable",
        evaluation_request_digest="0" * 64, evaluation_failure="network_error",
        executed_at=datetime.now(timezone.utc) - timedelta(seconds=1), outcome="success",
        execution_parameters={"version_id": "v8b"},
    ))
    status, body = na.public("POST", "/evidence/break-glass", {"record": record.to_wire()})
    s.cmd("POST /evidence/break-glass  (submitted from the outbox when the NA is back)")
    judgement_line(s, status, body)

    s.step("The secret's changes")
    _, changes = na.admin("GET", f"/admin/evidence/changes/{SECRET}")
    s.cmd(f"GET /admin/evidence/changes/{SECRET}")
    for change in changes["changes"]:
        s.text(f"  {change['kind']:<12} {change.get('action', ''):<7} "
               f"governed_by={str(change.get('governed_by')):<15} state={change['state']}")

    s.step("4. Remediate the denied console rotation")
    _, queue = na.admin("GET", "/admin/evidence/remediations?state=remediation_due")
    s.cmd("GET /admin/evidence/remediations?state=remediation_due")
    for item in queue["remediations"]:
        s.text(f"  {item['change_kind']} by {item['actor']}: {item['mode']}, {item['steps']}, "
               f"due {item['remediation_due_at'][:19]}")
    status, _ = na.admin("POST", f"/admin/evidence/remediations/{denied['judgement_id']}/notified",
                         {"channel": "email"})
    s.cmd("POST /admin/evidence/remediations/<judgement>/notified")
    s.ok(f"{status}: actor notified")
    _, v9, status, _ = governed_rotation("v9", v7)
    s.cmd("POST /evidence/execution  (rotate forward under a governed decision, version_id v9)")
    s.ok(f"{status}: execution evidence for v9")
    s.dim("the controller then disables v8 in the vault; the NA never changes the secret itself")
    done = controller.sign(RemediationRecord(
        executor_sovereign_id=controller.sovereign, subject_kind="judgement", subject_id=denied["judgement_id"],
        change_kind="observation", change_id=console.observation_id, resource_id=SECRET, outcome="cancelled",
        steps="rotate_forward_then_disable", rotation_evidence_id=v9.evidence_id, version_id="v9",
        disabled_version_id="v8", remediated_at=datetime.now(timezone.utc),
    ))
    status, body = na.public("POST", "/evidence/remediations", {"record": done.to_wire()})
    s.cmd("POST /evidence/remediations  (cancelled: rotate_forward_then_disable)")
    (s.ok if status == 201 else s.no)(
        f"{status}: state={body.get('remediation', {}).get('state', error_code(body))}")

    s.step("Verify the export offline")
    _, export = na.admin("GET", "/admin/evidence/export")
    (na.dir / "export.jsonl").write_text(export, encoding="utf-8")
    _, keys = na.admin("GET", "/admin/evidence/executor-keys")
    na.write_json("executor-keys.json", keys)
    s.cmd("genesis-mesh evidence verify-export --file export.jsonl --na-public-key home/keys/na.pub "
          "--executor-keys executor-keys.json")
    code, out = na.cli("evidence", "verify-export", "--file", "export.jsonl", "--na-public-key",
                       "home/keys/na.pub", "--executor-keys", "executor-keys.json")
    s.output(out, ok=("VERIFIED",), no=("FAILED", "  - "))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18454, help="port for the temporary NA")
    parser.add_argument("--no-gif", action="store_true", help="write the transcript only")
    args = parser.parse_args()
    session = Session()
    with LocalNA(args.port, SETTINGS) as na:
        run(na, session)
    session.save("out-of-band-changes", "Genesis Mesh -- Changes Outside the Controlled Path",
                 render=not args.no_gif)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
