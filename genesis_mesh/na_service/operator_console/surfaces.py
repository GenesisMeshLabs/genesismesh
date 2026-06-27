"""Structured Network Authority surface metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SurfaceGroup = Literal["safe", "node_agent", "operator", "managed"]
AccessKind = Literal["browser_safe", "node_signed", "operator_signed", "cli"]


@dataclass(frozen=True)
class Surface:
    """Describe one HTTP or CLI surface shown by the operator console."""

    method: str
    target: str
    title: str
    purpose: str
    group: SurfaceGroup
    access: AccessKind
    auth_hint: str
    clickable: bool = False
    curated: bool = False
    query_hint: str | None = None

    @property
    def is_http(self) -> bool:
        """Return whether this surface is an HTTP route."""
        return self.method != "CLI"


HTTP_SURFACES: tuple[Surface, ...] = (
    Surface("GET", "/health", "Health summary", "Expanded service health summary.", "safe", "browser_safe", "None", True),
    Surface("GET", "/healthz", "Liveness", "Process-level health probe.", "safe", "browser_safe", "None", True, True),
    Surface("GET", "/readyz", "Readiness", "Database and migration readiness.", "safe", "browser_safe", "None", True, True),
    Surface("GET", "/metrics", "Metrics", "Prometheus-compatible runtime metrics.", "safe", "browser_safe", "None", True),
    Surface("GET", "/sovereign.json", "Sovereign metadata", "Operator-safe public trust material.", "safe", "browser_safe", "None", True, True),
    Surface("GET", "/genesis", "Genesis", "Signed network trust root.", "safe", "browser_safe", "None", True),
    Surface("GET", "/policy", "Policy", "Active DB-backed policy manifest.", "safe", "browser_safe", "None", True),
    Surface("GET", "/crl", "Revocation list", "Current signed certificate revocation list.", "safe", "browser_safe", "None", True),
    Surface("GET", "/nodes", "Nodes", "Recently active node inventory.", "safe", "browser_safe", "None", True),
    Surface("GET", "/dashboard", "Sovereign dashboard", "Read-only sovereign health and trust view.", "safe", "browser_safe", "None", True, True),
    Surface("GET", "/dashboard.json", "Dashboard JSON", "Machine-readable sovereign health and trust summary.", "safe", "browser_safe", "None", True),
    Surface("GET", "/connectome", "Connectome", "Human-readable recognition and revocation view.", "safe", "browser_safe", "None", True, True),
    Surface("GET", "/connectome.json", "Connectome JSON", "Machine-readable Connectome summary.", "safe", "browser_safe", "None", True),
    Surface("GET", "/atlas", "Trust Atlas", "Read-only recognition graph explorer with evidence overlay.", "safe", "browser_safe", "None", True, True),
    Surface("GET", "/atlas.json", "Atlas JSON", "Machine-readable Atlas summary with graph digest.", "safe", "browser_safe", "None", True),
    Surface(
        "GET",
        "/connectome/trust-path",
        "Trust path",
        "Explain recognition between two sovereigns.",
        "safe",
        "browser_safe",
        "None",
        False,
        False,
        "Requires from and to query parameters.",
    ),
    Surface("GET", "/recognition-graph", "Recognition graph", "Source graph for trust explanations.", "safe", "browser_safe", "None", True),
    Surface("GET", "/recognition-treaties", "Recognition treaties", "List persisted sovereign treaties.", "safe", "browser_safe", "None", True),
    Surface("GET", "/recognition-policy", "Recognition policy", "Current portable-trust acceptance policy.", "safe", "browser_safe", "None", True),
    Surface("GET", "/sovereign-revocation-feed", "Sovereign revocation feed", "Export revocations issued by a sovereign.", "safe", "browser_safe", "None", True),
    Surface("GET", "/attestations", "Membership attestations", "List issued portable membership attestations.", "safe", "browser_safe", "None", True),
    Surface("GET", "/agents", "Agent discovery", "List registered agent descriptors.", "safe", "browser_safe", "None", True, True),
    Surface("GET", "/agents/{node_public_key}", "Agent lookup", "Read one agent descriptor.", "safe", "browser_safe", "None"),
    Surface("GET", "/swagger.json", "OpenAPI metadata", "Generated HTTP protocol surface metadata.", "safe", "browser_safe", "None", True),
    Surface("GET", "/api-reference", "API reference", "Read-only HTTP API reference.", "safe", "browser_safe", "None", True, True),
    Surface("GET", "/cli-reference", "CLI reference", "Generated CLI command reference.", "safe", "browser_safe", "None", True, True),
    Surface("POST", "/join", "Join", "Issue a certificate from a single-use invite.", "node_agent", "node_signed", "Node PoP", curated=True),
    Surface("POST", "/heartbeat", "Heartbeat", "Update authenticated node liveness.", "node_agent", "node_signed", "Node PoP"),
    Surface("POST", "/renew", "Renew", "Renew a non-revoked node certificate.", "node_agent", "node_signed", "Node PoP"),
    Surface("POST", "/agents", "Register agent", "Publish an authenticated agent descriptor.", "node_agent", "node_signed", "Node PoP", curated=True),
    Surface("DELETE", "/agents/{node_public_key}", "Remove agent", "Delete an authenticated descriptor.", "node_agent", "node_signed", "Node PoP"),
    Surface("POST", "/admin/invite", "Invite", "Create a scoped enrollment token.", "operator", "operator_signed", "Operator signature", curated=True),
    Surface("POST", "/admin/revoke", "Revoke", "Publish a new signed CRL.", "operator", "operator_signed", "Operator signature", curated=True),
    Surface("POST", "/admin/policy", "Policy publish", "Activate a signed policy version.", "operator", "operator_signed", "Operator signature"),
    Surface("GET", "/admin/policy/history", "Policy history", "Inspect persisted policy versions.", "operator", "operator_signed", "Operator signature"),
    Surface("POST", "/admin/policy/rollback", "Policy rollback", "Reactivate a previous policy.", "operator", "operator_signed", "Operator signature"),
    Surface("POST", "/admin/attestations", "Issue attestation", "Issue portable membership evidence.", "operator", "operator_signed", "Operator signature", curated=True),
    Surface("POST", "/admin/attestations/{attestation_id}/revoke", "Revoke attestation", "Publish sovereign-level attestation revocation.", "operator", "operator_signed", "Operator signature"),
    Surface("POST", "/admin/recognition-policy", "Set recognition policy", "Set portable trust acceptance policy.", "operator", "operator_signed", "Operator signature"),
    Surface("POST", "/admin/recognition-treaties", "Issue treaty", "Create a direct-recognition treaty for another sovereign.", "operator", "operator_signed", "Operator signature", curated=True),
    Surface("POST", "/admin/recognition-treaties/{treaty_id}/revoke", "Revoke treaty", "End a persisted recognition treaty.", "operator", "operator_signed", "Operator signature"),
    Surface("POST", "/admin/sovereign-revocation-feeds/import", "Import revocation feed", "Import revoked trust material from a recognized sovereign.", "operator", "operator_signed", "Operator signature", curated=True),
    Surface("POST", "/recognition-treaties/verify", "Verify treaty", "Verify a signed recognition treaty.", "operator", "operator_signed", "Signed HTTP client"),
    Surface("POST", "/attestations/verify", "Verify attestation", "Verify a signed membership attestation.", "operator", "operator_signed", "Signed HTTP client"),
    Surface("POST", "/attestations/verify-with-treaty", "Verify with treaty", "Verify an attestation using a recognition treaty.", "operator", "operator_signed", "Signed HTTP client"),
)


CLI_SURFACES: tuple[Surface, ...] = (
    Surface("CLI", "genesis-mesh federation bootstrap", "Federation bootstrap", "Review a sovereign and issue a direct-recognition treaty.", "operator", "cli", "Operator signature", curated=True),
    Surface("CLI", "genesis-mesh treaty list", "Treaty list", "Review treaty lifecycle state and expiry risk.", "operator", "cli", "Public GET"),
    Surface("CLI", "genesis-mesh treaty inspect", "Treaty inspect", "Inspect one treaty lifecycle and scope.", "operator", "cli", "Public GET"),
    Surface("CLI", "genesis-mesh treaty renew", "Treaty renew", "Issue a successor treaty and retire the old one.", "operator", "cli", "Operator signature"),
    Surface("CLI", "genesis-mesh trust-bundle export", "Trust bundle export", "Package public sovereign trust material for review.", "operator", "cli", "Public GET"),
    Surface("CLI", "genesis-mesh trust-bundle import", "Trust bundle import", "Record a reviewed bundle without granting trust.", "operator", "cli", "Local shell"),
    Surface("CLI", "genesis-mesh trust-bundle validate", "Trust bundle validate", "Validate shared trust material before federation review.", "operator", "cli", "Public GET"),
    Surface("CLI", "genesis-mesh trust decide", "Trust decide", "Evaluate trust toward a sovereign and print a verdict with signals.", "operator", "cli", "Public GET", curated=True),
    Surface("CLI", "genesis-mesh trust evidence", "Trust evidence", "Sign and emit a TrustEvidence record binding verdict to graph state.", "operator", "cli", "Operator signature", curated=True),
    Surface("CLI", "genesis-mesh trust verify-evidence", "Verify evidence", "Verify a TrustEvidence signature and optional graph-digest binding.", "operator", "cli", "Public GET", curated=True),
    Surface("CLI", "genesis-mesh atlas build", "Atlas build", "Build a self-contained static Atlas from a recognition graph export.", "operator", "cli", "Public GET", curated=True),
    Surface("CLI", "genesis-mesh managed backup", "Backup", "Create a consistent online NA DB backup.", "managed", "cli", "Local shell", curated=True),
    Surface("CLI", "genesis-mesh managed restore", "Restore", "Restore a validated backup while the NA is stopped.", "managed", "cli", "Local shell", curated=True),
    Surface("CLI", "genesis-mesh managed audit-export", "Audit export", "Export redacted audit events.", "managed", "cli", "Local shell", curated=True),
)


ALL_SURFACES: tuple[Surface, ...] = HTTP_SURFACES + CLI_SURFACES


def surfaces_by_group(group: SurfaceGroup, *, curated_only: bool = False) -> list[Surface]:
    """Return surfaces for a console group."""
    return [
        surface
        for surface in ALL_SURFACES
        if surface.group == group and (surface.curated or not curated_only)
    ]


def browser_safe_count() -> int:
    """Return count of browser-openable safe HTTP routes."""
    return sum(1 for surface in HTTP_SURFACES if surface.clickable)
