"""Reference adapter safety and persistence checks; uses isolated temporary stores."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import RecognitionTreaty, RecognitionTreatyScope, SovereignRevocationFeed
from genesis_mesh.na_service.db import NADatabase
from sync_authority_revocations import synchronize


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = str(Path(self.folder.name) / 'na.db')
        self.db = NADatabase(self.path)
        self.db.migrate()
        self.local_key = generate_keypair()
        self.peer_key = generate_keypair()
        self.local = {'network_name': 'a', 'network_authority': {'public_key': self.local_key.public_key_b64}}
        self.peer = {'network': 'b', 'public_key': self.peer_key.public_key_b64}

    def tearDown(self):
        self.db.conn.close()
        self.folder.cleanup()

    def recognize(self, expired=False):
        now = datetime.now(timezone.utc)
        treaty = RecognitionTreaty(treaty_id='ab', issuer_sovereign_id='a', subject_sovereign_id='b',
            subject_public_keys=[self.peer_key.public_key_b64], scope=RecognitionTreatyScope(allowed_roles=['role:client']),
            status='active', issued_at=now-timedelta(days=2), valid_from=now-timedelta(days=2),
            expires_at=now+timedelta(hours=-1 if expired else 1), issued_by='a-na')
        treaty.signatures.append(sign_model(treaty, self.local_key.private_key, 'a-na'))
        self.db.save_recognition_treaty(treaty)

    def feed(self, sequence=1, revoked=None, stale=False):
        feed = SovereignRevocationFeed(feed_id='b-'+str(sequence), issuer_sovereign_id='b', sequence=sequence,
            issued_at=datetime.now(timezone.utc)-timedelta(hours=25 if stale else 0),
            revoked_attestation_ids=revoked or [], revocation_reasons={}, issued_by='b-na')
        feed.signatures.append(sign_model(feed, self.peer_key.private_key, 'b-na'))
        return feed.model_dump(mode='json')

    def test_requires_active_local_recognition(self):
        with self.assertRaisesRegex(ValueError, 'no_active'):
            synchronize(self.db, self.local, self.peer, self.feed())
        self.recognize(expired=True)
        with self.assertRaisesRegex(ValueError, 'no_active'):
            synchronize(self.db, self.local, self.peer, self.feed())
        self.assertIsNone(self.db.get_latest_sovereign_revocation_sequence('b'))

    def test_rejects_bad_signature_wrong_issuer_and_stale_feed(self):
        self.recognize()
        for field, value in [('sequence', 99), ('issuer_sovereign_id', 'other')]:
            payload = self.feed()
            payload[field] = value
            with self.assertRaises(ValueError):
                synchronize(self.db, self.local, self.peer, payload)
        with self.assertRaisesRegex(ValueError, 'freshness'):
            synchronize(self.db, self.local, self.peer, self.feed(stale=True))
        self.assertIsNone(self.db.get_latest_sovereign_revocation_sequence('b'))

    def test_retains_high_water_mark_across_restart_rejects_rollback_and_equivocation(self):
        self.recognize()
        payload = self.feed(2, ['revoked-member'])
        self.assertEqual(synchronize(self.db, self.local, self.peer, payload)['status'], 'imported')
        self.db.conn.close()
        self.db = NADatabase(self.path)
        self.assertEqual(synchronize(self.db, self.local, self.peer, payload)['status'], 'current')
        for bad in [self.feed(1), self.feed(2, ['different-member'])]:
            with self.assertRaises(ValueError):
                synchronize(self.db, self.local, self.peer, bad)
        self.assertEqual(self.db.get_latest_sovereign_revocation_sequence('b'), 2)
        self.assertEqual(self.db.list_sovereign_revocation_feeds(issuer_sovereign_id='b')[0]['feed'].revoked_attestation_ids, ['revoked-member'])


if __name__ == '__main__':
    unittest.main()
