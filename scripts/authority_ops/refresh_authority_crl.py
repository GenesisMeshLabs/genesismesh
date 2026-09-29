"""Refresh an authority's signed CRL without discarding revocations.

Run in the reference authority's Python environment once per hour. The signing
key remains on its authority host. A SQLite write transaction serializes refresh
with other writers, including multiple instances of this maintenance command.
"""
import argparse
import uuid
from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto import load_private_key, sign_model, verify_model_signature
from genesis_mesh.models import CertificateRevocationList
from genesis_mesh.na_service.db import NADatabase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--key-file', required=True)
    parser.add_argument('--issuer', required=True)
    args = parser.parse_args()
    key = load_private_key(args.key_file)
    db = NADatabase(args.database)
    try:
        db.conn.execute('BEGIN IMMEDIATE')
        previous = db.get_active_crl()
        if previous and not any(s.key_id == args.issuer and verify_model_signature(previous, s, key.verify_key) for s in previous.signatures):
            raise ValueError('Signing key does not authenticate the stored CRL')
        now = datetime.now(timezone.utc)
        if previous and previous.next_update > now + timedelta(hours=2):
            db.conn.rollback()
            print('CRL fresh; no update needed')
            return
        if previous and previous.issuer != args.issuer:
            raise ValueError('Configured issuer does not match stored CRL')
        crl = CertificateRevocationList(
            crl_id=str(uuid.uuid4()), sequence=previous.sequence + 1 if previous else 0,
            issued_at=now, next_update=now + timedelta(hours=24), issuer=args.issuer,
            revoked_certificates=previous.revoked_certificates if previous else [], signatures=[])
        crl.signatures.append(sign_model(crl, key, args.issuer))
        db.save_crl(crl, active=True)
        print('Refreshed signed CRL sequence', crl.sequence, 'with', len(crl.revoked_certificates), 'retained revocations')
    except Exception:
        db.conn.rollback()
        raise
    finally:
        db.conn.close()


if __name__ == '__main__':
    main()
