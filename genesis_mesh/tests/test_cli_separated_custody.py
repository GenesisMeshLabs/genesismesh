"""Two independent operators run a cross-sovereign flow, each with only their own key (v1.0.2).

The issuing sovereign attests and revokes a member; the accepting sovereign
signs its treaty and imports the issuer's signed revocation feed under the key
that treaty pinned. Neither operator ever holds the other's private keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests
from click.testing import CliRunner

from genesis_mesh.cli.config import load_config
from genesis_mesh.cli.main import cli
from genesis_mesh.cli.support import _signed_admin_headers

from .cli_ops_helpers import _running_na_from_config
from .test_cli_treaty_lifecycle import _init_sovereign


def _operator(config_path: Path) -> list[str]:
    config = load_config(str(config_path), required=True)
    return ["--operator-key", config["paths"]["operator_private_key"],
            "--operator-key-id", config["operator"]["key_id"]]


def _na_public_key(config_path: Path) -> str:
    config = load_config(str(config_path), required=True)
    return json.loads(Path(config["paths"]["genesis"]).read_text(encoding="utf-8"))["network_authority"]["public_key"]


def test_two_operators_run_attestation_treaty_and_revocation_with_their_own_keys(tmp_path):
    runner = CliRunner()
    alpha = _init_sovereign(runner, tmp_path, "ALPHA")
    beta = _init_sovereign(runner, tmp_path, "BETA")

    with _running_na_from_config(alpha, tmp_path / "alpha.db") as alpha_na, \
            _running_na_from_config(beta, tmp_path / "beta.db") as beta_na:
        # Alpha's operator: a treaty recognizing beta, pinning beta's NA key.
        config = load_config(str(alpha), required=True)
        body = {
            "subject_sovereign_id": "BETA",
            "subject_public_keys": [_na_public_key(beta)],
            "scope": {"allowed_roles": ["role:client"], "accepted_statuses": ["active"]},
            "validity_hours": 24,
        }
        treaty = requests.post(
            f"{alpha_na}/admin/recognition-treaties", json=body, timeout=10,
            headers=_signed_admin_headers(
                config["operator"]["key_id"], Path(config["paths"]["operator_private_key"]), body,
                method="POST", base_url=alpha_na, path="/admin/recognition-treaties",
            ),
        )
        assert treaty.status_code == 201, treaty.text
        treaty_path = tmp_path / "treaty.json"
        treaty_path.write_text(treaty.text, encoding="utf-8")

        # Beta's operator: attest a member.
        attestation_path = tmp_path / "attestation.json"
        issued = runner.invoke(cli, [
            "attestation", "issue", "--na", beta_na, "--subject-id", "alice", "--role", "role:client",
            "--output", str(attestation_path), *_operator(beta),
        ])
        assert issued.exit_code == 0, issued.output
        attestation_id = json.loads(attestation_path.read_text(encoding="utf-8"))["attestation_id"]

        # Anyone: alpha's NA accepts the member through its own treaty.
        verify_args = ["attestation", "verify-with-treaty", "--na", alpha_na,
                       "--attestation", str(attestation_path), "--treaty", str(treaty_path)]
        accepted = runner.invoke(cli, verify_args)
        assert accepted.exit_code == 0, accepted.output
        assert json.loads(accepted.output)["trust_basis"] == "this_authority"

        # Beta's operator revokes; alpha's operator imports beta's signed feed.
        revoked = runner.invoke(cli, ["attestation", "revoke", "--na", beta_na, attestation_id,
                                      "--reason", "offboarded", *_operator(beta)])
        assert revoked.exit_code == 0, revoked.output
        imported = runner.invoke(cli, ["treaty", "import-feed", "--na", alpha_na, "--from", beta_na,
                                       "--expected-issuer", "BETA", *_operator(alpha)])
        assert imported.exit_code == 0, imported.output

        refused = runner.invoke(cli, verify_args)
        assert refused.exit_code == 1
        assert json.loads(refused.output)["reason"] == "attestation_locally_revoked"


def test_import_feed_needs_exactly_one_source(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["treaty", "import-feed", "--na", "http://127.0.0.1:1", "--operator-key", "k"])
    assert result.exit_code != 0
    assert "exactly one of --from or --feed" in result.output
