"""Generate the managed sovereign readiness demo assets."""

from __future__ import annotations

import argparse
import json
import tempfile
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

from click.testing import CliRunner
import nacl.encoding
import nacl.signing

from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import sign_model
from genesis_mesh.models import (
    GenesisBlock,
    NetworkAuthority,
    PolicyManifestRef,
    RecognitionTreaty,
    RecognitionTreatyScope,
)
from genesis_mesh.na_service.server import NetworkAuthorityService

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GIF_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-managed-sovereign.gif"
DEFAULT_PNG_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-managed-sovereign.png"


def _new_service(db_path: Path) -> NetworkAuthorityService:
    """Create a local managed-sovereign NA service for the drill."""
    na_key = nacl.signing.SigningKey(bytes([16]) * 32)
    na_public_key = na_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode("utf-8")
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="managed-demo",
        network_version="v0.16-demo",
        root_public_key=na_public_key,
        network_authority=NetworkAuthority(
            public_key=na_public_key,
            valid_from=now - timedelta(minutes=1),
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:demo", url=None),
    )
    service = NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=na_key,
        key_id="managed-demo-na",
        db_path=str(db_path),
        operator_public_keys={},
    )
    service.app.config["TESTING"] = True
    return service


def _treaty(treaty_id: str, subject_id: str = "customer-sovereign") -> RecognitionTreaty:
    """Build a signed treaty so Connectome state survives the restore drill."""
    signer = nacl.signing.SigningKey(bytes([17]) * 32)
    subject_public_key = signer.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode("utf-8")
    now = datetime.now(timezone.utc)
    treaty = RecognitionTreaty(
        treaty_id=treaty_id,
        issuer_sovereign_id="managed-demo",
        subject_sovereign_id=subject_id,
        subject_public_keys=[subject_public_key],
        scope=RecognitionTreatyScope(allowed_roles=["role:service:maintainer"]),
        status="active",
        issued_at=now,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=6),
        issued_by="managed-demo-na",
        metadata={"demo": "managed-sovereign-readiness"},
    )
    treaty.signatures.append(sign_model(treaty, signer, "managed-demo-na"))
    return treaty


def _run_cli(args: list[str]) -> tuple[int, dict]:
    """Run one CLI command and return exit code plus parsed JSON output."""
    result = CliRunner().invoke(cli, args)
    if result.exit_code != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.output}")
    return result.exit_code, json.loads(result.output)


def run_demo() -> list[str]:
    """Run the managed sovereign drill and return transcript lines."""
    lines: list[str] = []

    def emit(line: str = "") -> None:
        lines.append(line)
        print(line)

    with tempfile.TemporaryDirectory(prefix="gm-managed-demo-", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        db_path = root / "na.db"
        backup_path = root / "backups" / "managed-demo-backup.db"
        pre_restore_path = root / "backups" / "pre-restore.db"
        audit_path = root / "audit" / "managed-demo-audit.jsonl"

        service = _new_service(db_path)
        try:
            service.db.save_recognition_treaty(_treaty("restored-managed-treaty"))
            service.db.add_audit_event(
                "recognition_treaty_issued",
                {
                    "treaty_id": "restored-managed-treaty",
                    "issuer_sovereign_id": "managed-demo",
                    "subject_sovereign_id": "customer-sovereign",
                },
            )
            client = service.app.test_client()
            ready = client.get("/readyz").get_json()
            connectome = client.get("/connectome.json").get_json()
        finally:
            service.db.conn.close()

        emit("==> Managed sovereign initialized")
        emit(f"    readyz:      {ready['status']}")
        emit(f"    db:          {db_path.name}")
        emit(f"    treaties:    {connectome['summary']['recognition_edge_count']}")

        _, backup = _run_cli(
            [
                "managed",
                "backup",
                "--db-path",
                str(db_path),
                "--output",
                str(backup_path),
            ]
        )
        emit()
        emit("==> Online backup created")
        emit(f"    backup:      {Path(backup['backup_path']).name}")

        service = _new_service(db_path)
        try:
            service.db.save_recognition_treaty(_treaty("mutated-after-backup", "bad-import"))
            service.db.add_audit_event(
                "sovereign_revocation_feed_rejected",
                {
                    "feed_id": "bad-feed",
                    "issuer_sovereign_id": "bad-import",
                    "admin_signature": "must-not-export",
                    "request_body": {"private_key": "must-not-export"},
                },
            )
            mutated = service.app.test_client().get("/connectome.json").get_json()
        finally:
            service.db.conn.close()

        emit()
        emit("==> State mutated after backup")
        emit(f"    treaties:    {mutated['summary']['recognition_edge_count']}")
        emit("    audit:       bad feed rejection captured")

        _, audit = _run_cli(
            [
                "managed",
                "audit-export",
                "--db-path",
                str(db_path),
                "--output",
                str(audit_path),
            ]
        )
        exported = audit_path.read_text(encoding="utf-8")
        emit()
        emit("==> Redacted audit export written")
        emit(f"    events:      {audit['event_count']}")
        emit(f"    redacted:    {'must-not-export' not in exported}")

        _, restore = _run_cli(
            [
                "managed",
                "restore",
                "--db-path",
                str(db_path),
                "--backup",
                str(backup_path),
                "--pre-restore-backup",
                str(pre_restore_path),
                "--yes",
            ]
        )
        emit()
        emit("==> Database restored from known-good backup")
        emit(f"    restored:    {Path(restore['restored_from']).name}")
        emit(f"    preserved:   {Path(restore['pre_restore_backup']).name}")

        service = _new_service(db_path)
        try:
            client = service.app.test_client()
            healthz = client.get("/healthz").get_json()
            readyz = client.get("/readyz").get_json()
            restored = client.get("/connectome.json").get_json()
        finally:
            service.db.conn.close()

        emit()
        emit("==> Restored NA reopened cleanly")
        emit(f"    healthz:     {healthz['status']}")
        emit(f"    readyz:      {readyz['status']}")
        emit(f"    treaties:    {restored['summary']['recognition_edge_count']}")
        emit(f"    active edges: {restored['summary']['active_edge_count']}")
        emit()
        emit("Result: managed sovereign backup, audit export, restore, and endpoint drill passed.")
    return lines


def _pillow():
    """Import Pillow lazily so transcript mode has no image dependency."""
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _wrapped_lines(lines: list[str]) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=92, replace_whitespace=False) or [""])
    return wrapped


def _render_terminal_frame(lines: list[str], width: int, height: int):
    Image, ImageDraw, ImageFont = _pillow()
    margin = 28
    line_height = 24
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 17)
        bold = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 17)
    except Exception:
        font = ImageFont.load_default()
        bold = font

    img = Image.new("RGB", (width, height), "#08111f")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 54), fill="#111827")
    draw.text((margin, 18), "Genesis Mesh managed sovereign drill", fill="#e5e7eb", font=bold)
    draw.ellipse((width - 88, 20, width - 76, 32), fill="#ef4444")
    draw.ellipse((width - 66, 20, width - 54, 32), fill="#f59e0b")
    draw.ellipse((width - 44, 20, width - 32, 32), fill="#22c55e")

    y = 78
    for text in lines:
        color = "#d1d5db"
        selected_font = font
        lowered = text.lower()
        if text.startswith("==>"):
            color = "#93c5fd"
            selected_font = bold
        elif text.startswith("Result:"):
            color = "#86efac"
            selected_font = bold
        elif "healthz:     ok" in lowered or "readyz:      ready" in lowered:
            color = "#86efac"
            selected_font = bold
        elif "redacted:    true" in lowered:
            color = "#86efac"
            selected_font = bold
        elif "backup" in lowered or "restore" in lowered:
            color = "#c4b5fd"
        elif "audit" in lowered:
            color = "#fbbf24"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = _wrapped_lines(lines)[-34:]
    _render_terminal_frame(visible, 1120, 820).save(output)


def render_gif(lines: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapped = _wrapped_lines(lines)
    frames = []
    for index in range(1, len(wrapped) + 1):
        visible = wrapped[max(0, index - 34):index]
        frames.append(_render_terminal_frame(visible, 1120, 820))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=420,
        loop=0,
        optimize=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_GIF_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--no-assets", action="store_true")
    args = parser.parse_args()

    lines = run_demo()
    if not args.no_assets:
        render_png(lines, args.png_output)
        render_gif(lines, args.output)
        print(f"PNG written to {args.png_output}")
        print(f"GIF written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
