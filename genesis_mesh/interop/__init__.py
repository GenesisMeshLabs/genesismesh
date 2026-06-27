"""GenesisMesh interop bridges to external trust ecosystems.

Bridges are lossy by design — not all GM fields map cleanly to external formats.
All bridge outputs include ``_gm_bridge_source`` so consumers know provenance.
Signature verification in external formats requires the original GM public keys.
"""
