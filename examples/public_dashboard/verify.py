"""Verify a downloaded evidence bundle offline against a separately pinned root."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .records import Snapshot, current_issuers, freshness, validate_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--root-key", required=True)
    args = parser.parse_args()
    try:
        snapshot = Snapshot.model_validate_json(args.bundle.read_text(encoding="utf-8"))
        validate_snapshot(snapshot, args.root_key)
        now = datetime.now(timezone.utc)
        print(f"Verified signed snapshot, {len(snapshot.authorities)} authorities, {len(snapshot.treaties)} treaties and {len(snapshot.feeds)} feeds.")
        states = {i: freshness(snapshot.feeds[i].issued_at if i in snapshot.feeds else None, now) for i in current_issuers(snapshot)}
        print("Required feed freshness: " + ", ".join(f"{i}={s}" for i, s in sorted(states.items())))
        if freshness(snapshot.updated_at, now) in {"missing", "stale"} or any(s in {"missing", "stale"} for s in states.values()):
            raise ValueError("stale_or_missing_evidence")
    except (ValueError, KeyError, OSError):
        raise SystemExit("Evidence verification failed (signature, schema, trust anchor or freshness).")


if __name__ == "__main__":
    main()
