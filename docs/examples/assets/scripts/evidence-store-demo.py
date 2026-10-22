"""Run the evidence store walkthrough against a real local Network Authority.

Starts a temporary NA with ``genesis-mesh init --env-file`` (``EVIDENCE_STORE=on``),
then: registers a secrets controller's executor key, evaluates two requests
under a vendor's attestation and submits the signed ``create`` and ``rotate``
evidence, revokes the vendor and shows evidence under the DENY refused,
reads the secret's history, exports the store and verifies the export
offline, shows an edited export failing, and copies the store anchors out to
show that an export with its newest entries removed passes alone but fails
against the anchors.

    python docs/examples/assets/scripts/evidence-store-demo.py

The transcript goes to ``docs/examples/assets/images/genesis-mesh-evidence-store.txt``
and, with Pillow installed, the GIF next to it. ``--no-gif`` skips the GIF.
"""

from __future__ import annotations

import argparse
import json

import nacl.encoding
import nacl.signing

from _local_na import LocalNA, Session, error_code
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.trust.execution import record_execution

CAPABILITY = "secret.manage"
RESOURCE = "kv:vendor-acme/api-key"


def _edit(value, field: str, new: str) -> bool:
    """Change ``field`` in the first ``execution_parameters`` found; True when done."""
    if isinstance(value, dict):
        params = value.get("execution_parameters")
        if isinstance(params, dict) and field in params:
            params[field] = new
            return True
        return any(_edit(v, field, new) for v in value.values())
    if isinstance(value, list):
        return any(_edit(v, field, new) for v in value)
    return False


def run(na: LocalNA, s: Session) -> None:
    key = nacl.signing.SigningKey.generate()
    public_key = key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()

    s.step("Start the NA with EVIDENCE_STORE=on and register the controller")
    s.cmd("genesis-mesh na start --env-file na.env")
    s.text(f"  /health: evidence_store={na.public('GET', '/health')[1]['evidence_store']}")
    status, _ = na.admin("POST", "/admin/evidence/executor-keys", {
        "key_id": "ctrl-1", "public_key": public_key, "executor_sovereign_id": "secrets-controller"})
    s.cmd('POST /admin/evidence/executor-keys {"key_id": "ctrl-1", ...}')
    s.ok(f"{status}: executor key ctrl-1 registered")

    s.step("Authorize, act, submit evidence")
    _, attestation = na.admin("POST", "/admin/attestations", {
        "subject_id": "vendor-acme", "roles": ["role:client"], "claims": {"capabilities": [CAPABILITY]}})
    evaluate = {"attestation_id": attestation["attestation_id"], "requested_capability": CAPABILITY}
    previous = None
    for action, version in (("create", "7"), ("rotate", "8")):
        status, body = na.admin("POST", "/admin/boundary/evaluate", evaluate)
        decision = BoundaryDecision.model_validate(body["decision"])
        s.cmd(f'POST /admin/boundary/evaluate {{"requested_capability": "{CAPABILITY}"}}')
        s.ok(f"{status}: authorized={decision.authorized}")
        evidence = record_execution(
            decision, "secrets-controller", CAPABILITY, "success", key, issued_by="ctrl-1",
            execution_parameters={"secret_version": version}, resource_id=RESOURCE,
            resource_action=action, prior_resource_record=previous,
        )
        status, body = na.public("POST", "/evidence/execution", {"evidence": evidence.model_dump(mode="json")})
        s.cmd(f"POST /evidence/execution  ({action}, secret_version {version})")
        s.ok(f"{status}: store_sequence={body['entry']['store_sequence']} "
             f"resource_sequence={body['entry']['resource_sequence']}")
        previous = evidence

    s.step("Revoke the vendor")
    na.admin("POST", f"/admin/attestations/{attestation['attestation_id']}/revoke", {"reason": "contract_ended"})
    s.cmd("POST /admin/attestations/<vendor>/revoke")
    status, body = na.admin("POST", "/admin/boundary/evaluate", evaluate)
    denied = BoundaryDecision.model_validate(body["decision"])
    s.cmd("POST /admin/boundary/evaluate")
    s.no(f"{status}: authorized={denied.authorized} ({denied.denial_reason})")
    late = record_execution(
        denied, "secrets-controller", CAPABILITY, "success", key, issued_by="ctrl-1",
        execution_parameters={"secret_version": "9"}, resource_id=RESOURCE, resource_action="rotate",
        prior_resource_record=previous,
    )
    status, body = na.public("POST", "/evidence/execution", {"evidence": late.model_dump(mode="json")})
    s.cmd("POST /evidence/execution  (rotate under the DENY)")
    s.no(f"{status} {error_code(body)}")

    s.step("The secret's history, from the NA alone")
    status, history = na.admin("GET", f"/admin/evidence/resources/{RESOURCE}")
    s.cmd(f"GET /admin/evidence/resources/{RESOURCE}")
    for item in history["entries"]:
        entry = item["entry"]
        line = f"  store #{entry['store_sequence']}  {entry['entry_kind']:<13}"
        if entry["entry_kind"] == "execution":
            line += f"  {entry['resource_action']:<6}  resource #{entry['resource_sequence']}"
        else:
            line += f"  decision {entry['decision_id'][:8]}"
        s.text(line)
    verification = history["verification"]
    (s.ok if verification["verified"] else s.no)(
        f"verified={verification['verified']}: {verification['checked_entries']} entries, "
        f"{verification['decisions']} decisions, {verification['executions']} executions, "
        f"{len(verification['failures'])} failures")

    s.step("Export and verify offline")
    _, export = na.admin("GET", "/admin/evidence/export")
    (na.dir / "export.jsonl").write_text(export if isinstance(export, str) else json.dumps(export), encoding="utf-8")
    _, keys = na.admin("GET", "/admin/evidence/executor-keys")
    na.write_json("executor-keys.json", keys)
    lines = (na.dir / "export.jsonl").read_text(encoding="utf-8").splitlines()
    s.cmd("GET /admin/evidence/export > export.jsonl")
    s.text(f"  {len(lines)} gm.evidence.event lines")
    verify = ["evidence", "verify-export", "--file", "export.jsonl", "--na-public-key", "home/keys/na.pub",
              "--executor-keys", "executor-keys.json"]
    s.cmd("genesis-mesh evidence verify-export --file export.jsonl --na-public-key home/keys/na.pub "
          "--executor-keys executor-keys.json")
    code, out = na.cli(*verify)
    s.output(out, ok=("VERIFIED",), no=("FAILED",))

    s.step("Edit one record in the export")
    edited, done = [], False
    for line in lines:
        if not done and '"rotate"' in line:
            event = json.loads(line)
            done = _edit(event, "secret_version", "80")
            line = json.dumps(event)
        edited.append(line)
    (na.dir / "edited.jsonl").write_text("\n".join(edited) + "\n", encoding="utf-8")
    s.cmd("genesis-mesh evidence verify-export --file edited.jsonl ...   (secret_version 8 -> 80)")
    code, out = na.cli(*[("edited.jsonl" if a == "export.jsonl" else a) for a in verify])
    s.output(out, ok=("VERIFIED",), no=("FAILED", "  - "))
    s.dim(f"exit {code}")

    s.step("Copy the anchors out, then drop the newest entries")
    fetch = ["evidence", "anchors", "fetch", "--na", na.base, "--na-public-key", "home/keys/na.pub",
             "--out", "anchors", "--anchor-now", "--operator-key", "home/keys/operator.key",
             "--operator-key-id", "operator-local"]
    s.cmd("genesis-mesh evidence anchors fetch --na http://127.0.0.1:18454 --na-public-key home/keys/na.pub "
          "--out anchors --anchor-now --operator-key home/keys/operator.key --operator-key-id operator-local")
    code, out = na.cli(*fetch)
    s.output(out, keep=4)
    _, export = na.admin("GET", "/admin/evidence/export")
    full = (export if isinstance(export, str) else json.dumps(export)).splitlines()
    (na.dir / "short.jsonl").write_text("\n".join(full[:-3]) + "\n", encoding="utf-8")
    s.dim(f"short.jsonl: the first {len(full) - 3} of {len(full)} entries")
    short = [("short.jsonl" if a == "export.jsonl" else a) for a in verify]
    s.cmd("genesis-mesh evidence verify-export --file short.jsonl ...")
    code, out = na.cli(*short)
    s.output(out, ok=("VERIFIED",), no=("FAILED",))
    s.cmd("genesis-mesh evidence verify-export --file short.jsonl ... --known-anchors anchors")
    code, out = na.cli(*short, "--known-anchors", "anchors")
    s.output(out, ok=("VERIFIED",), no=("FAILED", "Anchors", "  - "))
    s.dim(f"exit {code}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18454, help="port for the temporary NA")
    parser.add_argument("--no-gif", action="store_true", help="write the transcript only")
    args = parser.parse_args()
    session = Session()
    with LocalNA(args.port) as na:
        run(na, session)
    session.save("evidence-store", "Genesis Mesh -- Evidence Store", render=not args.no_gif)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
