"""Operator-owned reference-NA revocation consumer. Never creates treaties or needs signing keys.

Run beside the reference authority with access to its database and a read-only
peer configuration. Other implementations should implement the same acceptance
rules in their native revocation consumer; this adapter is explicitly Python-NA specific.
"""
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from authority_http import origin, read_json
from genesis_mesh.models import SovereignRevocationFeed
from genesis_mesh.na_service.db import NADatabase
from genesis_mesh.trust import verify_recognition_treaty, verify_sovereign_revocation_feed


def synchronize(db, local, peer, payload):
    feed = SovereignRevocationFeed.model_validate(payload)
    now = datetime.now(timezone.utc)
    if feed.issued_at > now + timedelta(minutes=5) or feed.issued_at < now - timedelta(hours=24):
        raise ValueError('feed_outside_freshness_window')
    result = verify_sovereign_revocation_feed(feed, [peer['public_key']], expected_issuer_sovereign_id=peer['network'])
    if not result.accepted:
        raise ValueError(result.reason)
    db.conn.execute('BEGIN IMMEDIATE')
    try:
        recognized = False
        for row in db.list_recognition_treaties(issuer_sovereign_id=local['network_name'], subject_sovereign_id=peer['network'], status='active'):
            treaty = row['treaty']
            result = verify_recognition_treaty(treaty, [local['network_authority']['public_key']],
                expected_issuer_sovereign_id=local['network_name'], expected_subject_sovereign_id=peer['network'])
            if result.accepted and peer['public_key'] in treaty.subject_public_keys and treaty.valid_from <= now < treaty.expires_at:
                recognized = True
                break
        if not recognized:
            raise ValueError('no_active_locally_signed_recognition_treaty')
        sequence = db.get_latest_sovereign_revocation_sequence(peer['network'])
        if sequence is not None and feed.sequence < sequence:
            raise ValueError('sequence_rollback')
        if sequence == feed.sequence:
            rows = db.list_sovereign_revocation_feeds(issuer_sovereign_id=peer['network'])
            previous = next(r['feed'] for r in rows if r['feed'].sequence == sequence)
            if previous.revoked_attestation_ids != feed.revoked_attestation_ids or previous.revocation_reasons != feed.revocation_reasons:
                raise ValueError('same_sequence_different_revocations')
            db.conn.rollback()
            return {'status': 'current', 'sequence': sequence, 'revoked_count': len(feed.revoked_attestation_ids)}
        db.save_sovereign_revocation_feed(feed)
        db.add_audit_event('sovereign_revocation_feed_imported', {'feed_id': feed.feed_id, 'issuer_sovereign_id': feed.issuer_sovereign_id,
            'sequence': feed.sequence, 'revoked_count': len(feed.revoked_attestation_ids), 'source': 'operator_revocation_consumer'})
        return {'status': 'imported', 'sequence': feed.sequence, 'revoked_count': len(feed.revoked_attestation_ids)}
    except Exception:
        db.conn.rollback()
        raise


def cycle(config):
    local = json.loads(Path(config['genesis_file']).read_text())
    db = NADatabase(config['database'])
    results = []
    try:
        for peer in config['peers']:
            row = {'network': peer['network'], 'checked_at': datetime.now(timezone.utc).isoformat()}
            try:
                base = origin(peer['origin'], peer.get('allow_http', False))
                path = peer.get('feed_path', '/sovereign-revocation-feed')
                if not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path:
                    raise ValueError('invalid_feed_path')
                row.update(synchronize(db, local, peer, read_json(base, path, peer.get('token_file'))))
            except Exception as error:
                row.update(status='failed', error=str(error) if isinstance(error, ValueError) else type(error).__name__)
            results.append(row)
    finally:
        db.conn.close()
    report = {'network': local['network_name'], 'checked_at': datetime.now(timezone.utc).isoformat(), 'peers': results,
              'healthy': all(r['status'] != 'failed' for r in results)}
    if config.get('status_file'):
        destination = Path(config['status_file'])
        temporary = destination.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2))
        temporary.replace(destination)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        config = json.loads(args.config.read_text())
        if not 1 <= len(config['peers']) <= 16:
            raise SystemExit('Configure between 1 and 16 explicitly approved peers')
        report = cycle(config)
        print(json.dumps(report), flush=True)
        if not args.watch:
            raise SystemExit(0 if report['healthy'] else 1)
        time.sleep(max(15, min(3600, int(config.get('interval_seconds', 60)))))


if __name__ == '__main__':
    main()
