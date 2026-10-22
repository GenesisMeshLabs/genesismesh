"""Run the declarative boundary policy walkthrough against a real local Network Authority.

Starts a temporary NA with ``genesis-mesh init --env-file`` (which sets
``BOUNDARY_POLICY_ENFORCEMENT=required`` and ``EVIDENCE_STORE=on``), then:
lists the gate types, validates the page's policy offline, publishes and
activates it, evaluates a 2 500 transfer (denied by the amount cap),
explains the decision and verifies the signed policy with the CLI, shows
the legacy route refused, and publishes version 2, activates it and rolls
back to version 1.

    python docs/examples/assets/scripts/boundary-policy-demo.py

The transcript goes to ``docs/examples/assets/images/genesis-mesh-boundary-policy.txt``
and, with Pillow installed, the GIF next to it. ``--no-gif`` skips the GIF.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from _local_na import LocalNA, Session, error_code

CAPABILITY = "payments.transfer"


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def policy_intent(now: datetime, max_amount: int = 1000) -> dict:
    """The page's transfer-limits policy, valid from an hour ago for a year."""
    return {
        "policy_id": "transfer-limits",
        "description": "Cap transfers and require MFA",
        "valid_from": _iso(now - timedelta(hours=1)),
        "valid_until": _iso(now + timedelta(days=365)),
        "selector": {"capabilities": ["payments.*"]},
        "gates": [
            {"gate_id": "amount-cap", "gate_type": "max_value.v1", "order": 0,
             "config": {"path": "request_parameters.amount", "max": max_amount}},
            {"gate_id": "mfa", "gate_type": "boolean_required.v1", "order": 1,
             "config": {"path": "attributes.mfa_verified"}},
            {"gate_id": "business-hours", "gate_type": "time_window.v1", "order": 2, "mode": "observe",
             "config": {"weekdays": [1, 2, 3, 4, 5], "utc_hour_start": 7, "utc_hour_end": 19}},
        ],
    }


def run(na: LocalNA, s: Session) -> None:
    now = datetime.now(timezone.utc)

    s.step("Gate types this NA can run")
    s.cmd("genesis-mesh trust boundary-policy gate-types")
    s.output(na.cli("trust", "boundary-policy", "gate-types")[1], keep=4)

    s.step("Validate the policy offline")
    na.write_json("transfer-limits.json", policy_intent(now))
    s.cmd("genesis-mesh trust boundary-policy validate --file transfer-limits.json")
    code, out = na.cli("trust", "boundary-policy", "validate", "--file", "transfer-limits.json")
    s.output(out, ok=("Valid   : yes",), no=("Valid   : no",))
    bad = policy_intent(now)
    bad["gates"][0]["gate_type"] = "max_value.v9"
    na.write_json("transfer-limits-bad.json", bad)
    s.cmd("genesis-mesh trust boundary-policy validate --file transfer-limits-bad.json")
    code, out = na.cli("trust", "boundary-policy", "validate", "--file", "transfer-limits-bad.json")
    s.output(out, ok=("Valid   : yes",), no=("Valid   : no",))
    s.dim(f"exit {code}")

    s.step("Start the NA with BOUNDARY_POLICY_ENFORCEMENT=required")
    s.cmd("genesis-mesh na start --env-file na.env")
    health = na.public("GET", "/health")[1]
    s.text(f"  /health: boundary_policy_enforcement={health['boundary_policy_enforcement']} "
           f"boundary_policies={health['boundary_policies']}")

    s.step("Publish and activate version 1")
    status, signed = na.admin("POST", "/admin/boundary-policies", policy_intent(now))
    na.write_json("transfer-limits.signed.json", signed)
    s.cmd("POST /admin/boundary-policies  (transfer-limits.json)")
    s.ok(f"{status}: version {signed['version']}, signed by {signed['signature']['key_id']}, inactive")
    status, body = na.admin("POST", "/admin/boundary-policies/transfer-limits/activate", {"version": 1})
    s.cmd('POST /admin/boundary-policies/transfer-limits/activate {"version": 1}')
    s.ok(f"{status}: active={body['active']} previous_version={body['previous_version']}")

    s.step("Evaluate a transfer of 2500")
    status, attestation = na.admin("POST", "/admin/attestations", {
        "subject_id": "vendor-acme", "roles": ["role:client"],
        "claims": {"capabilities": [CAPABILITY]}})
    status, response = na.admin("POST", "/admin/boundary/evaluate", {
        "attestation_id": attestation["attestation_id"], "requested_capability": CAPABILITY,
        "context": {"request_parameters": {"amount": 2500}, "attributes": {"mfa_verified": True}}})
    na.write_json("evaluate-response.json", response)
    decision = response["decision"]
    s.cmd('POST /admin/boundary/evaluate  {"amount": 2500, "mfa_verified": true}')
    s.no(f"{status}: authorized={decision['authorized']}")
    s.no(f"denial_reason: {decision['denial_reason']}")

    s.step("Explain the decision and verify the signed policy")
    s.cmd("genesis-mesh trust boundary-policy explain --decision evaluate-response.json")
    s.output(na.cli("trust", "boundary-policy", "explain", "--decision", "evaluate-response.json")[1],
             ok=("PASS ",), no=("FAIL ", "Authorized : False"))
    s.cmd("genesis-mesh trust boundary-policy verify --file transfer-limits.signed.json "
          "--public-key home/keys/na.pub")
    code, out = na.cli("trust", "boundary-policy", "verify", "--file", "transfer-limits.signed.json",
                       "--public-key", "home/keys/na.pub")
    s.output(out, ok=("Result  : VALID",), no=("INVALID",))

    s.step("The policy-free legacy route is refused")
    status, body = na.admin("POST", "/admin/boundary/decide", {
        "agreement": {}, "requested_capability": CAPABILITY})
    s.cmd("POST /admin/boundary/decide")
    s.no(f"{status} {error_code(body)}")

    s.step("Version 2, then roll back to version 1")
    status, v2 = na.admin("POST", "/admin/boundary-policies", policy_intent(now, max_amount=5000))
    s.cmd("POST /admin/boundary-policies  (amount cap 5000)")
    s.ok(f"{status}: version {v2['version']}")
    for version in (2, 1):
        status, body = na.admin("POST", "/admin/boundary-policies/transfer-limits/activate", {"version": version})
        s.cmd(f'POST /admin/boundary-policies/transfer-limits/activate {{"version": {version}}}')
        s.ok(f"{status}: version {body['version']} active, previous_version={body['previous_version']}")
    status, history = na.admin("GET", "/admin/boundary-policies/transfer-limits/history")
    s.cmd("GET /admin/boundary-policies/transfer-limits/history")
    for entry in history["versions"]:
        s.text(f"  version {entry['version']}  active={entry.get('active')}  "
               f"digest={str(entry.get('policy_digest', ''))[:16]}...")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18454, help="port for the temporary NA")
    parser.add_argument("--no-gif", action="store_true", help="write the transcript only")
    args = parser.parse_args()
    session = Session()
    with LocalNA(args.port) as na:
        run(na, session)
    session.save("boundary-policy", "Genesis Mesh -- Declarative Boundary Policy", render=not args.no_gif)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
