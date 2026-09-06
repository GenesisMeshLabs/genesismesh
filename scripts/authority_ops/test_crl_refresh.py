"""Run inside the reference authority image: python /ops/test_crl_refresh.py."""
import base64
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nacl.signing import SigningKey
from genesis_mesh.crypto import sign_model, verify_model_signature
from genesis_mesh.models import CertificateRevocationList, RevokedCertificate
from genesis_mesh.na_service.db import NADatabase


class RefreshTests(unittest.TestCase):
    def test_refresh_retains_revocations_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = SigningKey.generate()
            keyfile = root / 'key'
            keyfile.write_text(base64.b64encode(bytes(key)).decode())
            db = NADatabase(str(root / 'db'))
            db.migrate()
            now = datetime.now(timezone.utc)
            old = CertificateRevocationList(crl_id='old', sequence=7, issuer='authority',
                issued_at=now-timedelta(days=2), next_update=now-timedelta(days=1),
                revoked_certificates=[RevokedCertificate(certificate_id='revoked', revoked_at=now-timedelta(days=2), reason='key_compromise', issuer='authority')], signatures=[])
            old.signatures.append(sign_model(old, key, 'authority'))
            db.save_crl(old)
            command = [sys.executable, str(Path(__file__).with_name('refresh_authority_crl.py')),
                       '--database', str(root / 'db'), '--key-file', str(keyfile), '--issuer', 'authority']
            subprocess.run(command, check=True, capture_output=True)
            fresh = db.get_active_crl()
            self.assertEqual(fresh.sequence, 8)
            self.assertEqual(fresh.revoked_certificates, old.revoked_certificates)
            self.assertGreater(fresh.next_update, now)
            self.assertTrue(verify_model_signature(fresh, fresh.signatures[0], key.verify_key))
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(db.get_active_crl(), fresh)
            keyfile.write_text(base64.b64encode(bytes(SigningKey.generate())).decode())
            rejected = subprocess.run(command, capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(db.get_active_crl(), fresh)
            db.conn.close()


if __name__ == '__main__':
    unittest.main()
