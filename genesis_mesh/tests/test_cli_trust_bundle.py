"""Tests for trust bundle exchange CLI workflows."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from genesis_mesh.cli.main import cli

from .cli_ops_helpers import _running_na_from_config


def _init_sovereign(runner: CliRunner, tmp_path: Path, name: str) -> Path:
    """Create a local sovereign config for CLI workflow tests."""
    config_path = tmp_path / f"{name.lower()}.toml"
    home = tmp_path / name.lower()
    result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--network-name",
            name,
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    return config_path


def test_trust_bundle_export_inspect_and_validate(tmp_path):
    """A bundle can be exported, inspected offline, and validated live."""
    runner = CliRunner()
    config_path = _init_sovereign(runner, tmp_path, "USG-B")
    bundle_path = tmp_path / "usg-b-trust-bundle.json"

    with _running_na_from_config(config_path, tmp_path / "issuer.db") as endpoint:
        export_result = runner.invoke(
            cli,
            [
                "trust-bundle",
                "export",
                "--na",
                endpoint,
                "--output",
                str(bundle_path),
            ],
        )
        assert export_result.exit_code == 0, export_result.output
        assert "Trust bundle exported" in export_result.output

        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        assert bundle["bundle_type"] == "genesis-mesh.trust-bundle"
        assert bundle["bundle_version"] == "v1"
        assert bundle["sovereign_id"] == "USG-B"
        assert bundle["source_endpoint"] == endpoint
        assert bundle["revocation_feed"]["status"] == "ok"

        serialized = json.dumps(bundle)
        assert "operator_private_key" not in serialized
        assert "na_private_key" not in serialized
        assert "db_path" not in serialized
        assert ".key" not in serialized
        assert "invite_token" not in serialized
        assert "bearer" not in serialized.lower()

        inspect_result = runner.invoke(
            cli,
            ["trust-bundle", "inspect", "--bundle", str(bundle_path)],
        )
        assert inspect_result.exit_code == 0, inspect_result.output
        assert "Trust bundle inspection" in inspect_result.output
        assert "sovereign:  USG-B" in inspect_result.output
        assert "validation: ok" in inspect_result.output

        validate_result = runner.invoke(
            cli,
            ["trust-bundle", "validate", "--bundle", str(bundle_path), "--na", endpoint],
        )
        assert validate_result.exit_code == 0, validate_result.output
        assert "Trust bundle validation" in validate_result.output
        assert "validation: ok" in validate_result.output

        receipt_path = tmp_path / "trust-bundle-import-receipt.json"
        import_result = runner.invoke(
            cli,
            [
                "trust-bundle",
                "import",
                "--bundle",
                str(bundle_path),
                "--na",
                endpoint,
                "--output",
                str(receipt_path),
            ],
        )
        assert import_result.exit_code == 0, import_result.output
        assert "Trust bundle imported for review" in import_result.output
        assert "trust_granted: false" in import_result.output
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["workflow"] == "trust-bundle-import"
        assert receipt["trust_granted"] is False
        assert receipt["validation"]["errors"] == []


def test_trust_bundle_validate_rejects_mismatched_identity(tmp_path):
    """Validation catches inconsistent sovereign identity fields."""
    bundle_path = tmp_path / "broken-bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_type": "genesis-mesh.trust-bundle",
                "bundle_version": "v1",
                "created_at": "2026-06-05T00:00:00+00:00",
                "source_endpoint": "https://issuer.example",
                "sovereign_id": "USG-B",
                "sovereign_metadata": {
                    "sovereign_id": "USG-B",
                    "network_authority": {"public_key": "issuer-key"},
                },
                "genesis": {
                    "network_name": "USG-C",
                    "network_authority": {"public_key": "issuer-key"},
                },
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["trust-bundle", "validate", "--bundle", str(bundle_path)],
    )
    assert result.exit_code != 0
    assert "sovereign_metadata.sovereign_id differs from genesis.network_name" in result.output


def test_trust_bundle_validate_rejects_stale_live_endpoint(tmp_path):
    """Live validation catches bundles whose endpoint no longer matches."""
    runner = CliRunner()
    config_path = _init_sovereign(runner, tmp_path, "USG-B")
    bundle_path = tmp_path / "usg-b-trust-bundle.json"

    with _running_na_from_config(config_path, tmp_path / "issuer.db") as endpoint:
        export_result = runner.invoke(
            cli,
            [
                "trust-bundle",
                "export",
                "--na",
                endpoint,
                "--output",
                str(bundle_path),
            ],
        )
        assert export_result.exit_code == 0, export_result.output

        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle["source_endpoint"] = "https://stale.example.org"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

        validate_result = runner.invoke(
            cli,
            ["trust-bundle", "validate", "--bundle", str(bundle_path), "--na", endpoint],
        )
        assert validate_result.exit_code != 0
        assert "bundle source_endpoint differs from live endpoint" in validate_result.output


def test_trust_bundle_validate_rejects_unsupported_version(tmp_path):
    """Unsupported bundle versions fail closed."""
    bundle_path = tmp_path / "unsupported-bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_type": "genesis-mesh.trust-bundle",
                "bundle_version": "v99",
                "created_at": "2026-06-05T00:00:00+00:00",
                "source_endpoint": "https://issuer.example",
                "sovereign_metadata": {
                    "sovereign_id": "USG-B",
                    "network_authority": {"public_key": "issuer-key"},
                },
                "genesis": {
                    "network_name": "USG-B",
                    "network_authority": {"public_key": "issuer-key"},
                },
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["trust-bundle", "validate", "--bundle", str(bundle_path)],
    )
    assert result.exit_code != 0
    assert "unsupported bundle_version" in result.output


def test_federation_bootstrap_accepts_issuer_bundle(tmp_path):
    """A valid issuer bundle can seed federation bootstrap review."""
    runner = CliRunner()
    acceptor_config = _init_sovereign(runner, tmp_path, "USG-A")
    issuer_config = _init_sovereign(runner, tmp_path, "USG-B")
    bundle_path = tmp_path / "issuer-bundle.json"

    with _running_na_from_config(acceptor_config, tmp_path / "acceptor.db") as acceptor:
        with _running_na_from_config(issuer_config, tmp_path / "issuer.db") as issuer:
            export_result = runner.invoke(
                cli,
                [
                    "trust-bundle",
                    "export",
                    "--na",
                    issuer,
                    "--output",
                    str(bundle_path),
                ],
            )
            assert export_result.exit_code == 0, export_result.output

            bootstrap_result = runner.invoke(
                cli,
                [
                    "federation",
                    "bootstrap",
                    "--acceptor",
                    acceptor,
                    "--issuer-bundle",
                    str(bundle_path),
                    "--dry-run",
                    "--format",
                    "json",
                ],
            )
            assert bootstrap_result.exit_code == 0, bootstrap_result.output
            evidence = json.loads(bootstrap_result.output)
            assert evidence["dry_run"] is True
            assert evidence["issuer"]["sovereign_id"] == "USG-B"
            assert evidence["issuer_bundle"]["bundle_version"] == "v1"
            assert evidence["issuer_bundle"]["validation"]["errors"] == []


# ---------------------------------------------------------------------------
# F-18 regression — a trust bundle is unverified review material.
#
# Note these assert on DISCLOSURE, not on blocking. Per the recorded product
# decision the bundle stays unsigned and an attacker-authored bundle still
# passes; what must not happen is that it passes in silence.
# ---------------------------------------------------------------------------


def _attacker_bundle(sovereign_id: str = "evil-corp") -> dict:
    """A self-consistent bundle written entirely by one party, genesis unsigned."""
    return {
        "bundle_type": "genesis-mesh.trust-bundle",
        "bundle_version": "v1",
        "created_at": "2026-08-18T00:00:00+00:00",
        "source_endpoint": "https://evil.example.org",
        "sovereign_id": sovereign_id,
        "network_version": "v1",
        "sovereign_metadata": {
            "sovereign_id": sovereign_id,
            "network_version": "v1",
            "root_public_key": "QUFBQQ==",
            "network_authority": {"public_key": "QUFBQQ=="},
        },
        "genesis": {
            "network_name": sovereign_id,
            "network_version": "v1",
            "root_public_key": "QUFBQQ==",
            "network_authority": {"public_key": "QUFBQQ=="},
            "signatures": [],
        },
        "recognition_policy": {"status": "skipped"},
        "revocation_feed": {"status": "skipped"},
        "connectome": {},
        "endpoint_checks": {},
    }


def test_unsigned_genesis_is_reported_not_silent(tmp_path):
    """F-18: the Phase-1 artifact passed with errors=[] AND warnings=[]."""
    from genesis_mesh.workflows.trust_bundle import validate_trust_bundle

    report = validate_trust_bundle(_attacker_bundle())

    # Still accepted — the bundle format stays unsigned by decision.
    assert report["errors"] == []
    # But no longer silent about what was not checked.
    assert any("no signatures" in w for w in report["warnings"]), report["warnings"]


def test_validate_prints_the_unverified_caveat(tmp_path):
    """The caveat reaches the operator, not just the RFC."""
    bundle_path = tmp_path / "attacker-bundle.json"
    bundle_path.write_text(json.dumps(_attacker_bundle()), encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["trust-bundle", "validate", "--bundle", str(bundle_path)]
    )

    assert result.exit_code == 0, result.output
    assert "UNVERIFIED" in result.output
    assert "one party passes validation by construction" in result.output
    assert "Do not load bundle content into a trust store" in result.output


def test_import_prints_the_unverified_caveat(tmp_path):
    """The same caveat appears on the import path."""
    bundle_path = tmp_path / "attacker-bundle.json"
    bundle_path.write_text(json.dumps(_attacker_bundle()), encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["trust-bundle", "import", "--bundle", str(bundle_path)]
    )

    assert result.exit_code == 0, result.output
    assert "Trust bundle imported for review" in result.output
    assert "UNVERIFIED" in result.output


def test_signed_genesis_bundle_still_reports_validation_ok(tmp_path):
    """Negative control: the warning is a real signal, not noise on every bundle."""
    from genesis_mesh.workflows.trust_bundle import validate_trust_bundle

    bundle = _attacker_bundle()
    bundle["genesis"]["signatures"] = [{"key_id": "root", "sig": "QUFBQQ=="}]

    report = validate_trust_bundle(bundle)

    assert report["errors"] == []
    assert report["warnings"] == []
