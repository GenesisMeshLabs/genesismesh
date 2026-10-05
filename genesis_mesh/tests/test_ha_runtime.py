"""Signer, key providers, HA-mode guard rails and readiness (v0.60)."""

from __future__ import annotations

import ast
import base64
import pathlib

import nacl.signing
import pytest

from genesis_mesh.crypto import verify_model_signature
from genesis_mesh.models import PolicyManifest
from genesis_mesh.na_service import key_provider
from genesis_mesh.na_service.key_provider import (
    KeyProviderConfig,
    KeyProviderError,
    Signer,
    load_from_azure_key_vault,
    load_signer,
)
from genesis_mesh.na_service.server import NetworkAuthorityService
from genesis_mesh.na_service.settings import load_settings

NA_SERVICE_DIR = pathlib.Path(key_provider.__file__).parent


def _seed_b64(key: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(key)).decode()


# ── Signer ────────────────────────────────────────────────────────────────────


def test_signer_signs_like_the_key_and_never_exposes_it(na_service):
    signer = na_service.signer
    assert isinstance(signer, Signer)
    assert na_service.na_private_key is signer  # legacy alias is the signer, not the key
    assert not hasattr(signer, "encode") and not hasattr(signer, "_signing_key")
    policy = na_service._get_default_policy()
    assert verify_model_signature(policy, policy.signatures[0], signer.public_key_b64)
    assert signer.fingerprint[:16] in repr(signer)
    assert _seed_b64(signer._key) not in repr(signer)


def test_na_code_never_handles_a_raw_signing_key():
    """Only the key provider may load or construct an Ed25519 private key."""
    offenders = []
    for path in NA_SERVICE_DIR.rglob("*.py"):
        if path.name == "key_provider.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in {"SigningKey", "load_private_key", "generate"} and "signing" in ast.unparse(fn):
                    offenders.append(f"{path.name}:{node.lineno}")
                if name == "load_private_key":
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


# ── providers ─────────────────────────────────────────────────────────────────


def test_file_provider_loads_the_key_file(tmp_path):
    key = nacl.signing.SigningKey.generate()
    path = tmp_path / "na.key"
    path.write_text("# NA key\n" + _seed_b64(key) + "\n")
    signer = load_signer(KeyProviderConfig(provider="file", key_id="na-1", key_file=str(path)))
    assert signer.provider == "file" and signer.key_id == "na-1"
    assert signer.verify_key == key.verify_key


def test_env_provider_reads_the_seed_without_a_file():
    key = nacl.signing.SigningKey.generate()
    signer = load_signer(KeyProviderConfig(provider="env", key_id="na-1"), environ={"NA_PRIVATE_KEY_SEED": _seed_b64(key)})
    assert signer.provider == "env" and signer.verify_key == key.verify_key


@pytest.mark.parametrize("seed", ["", "not base64!!", base64.b64encode(b"short").decode()])
def test_env_provider_refuses_missing_or_bad_seeds(seed):
    with pytest.raises(KeyProviderError):
        load_signer(KeyProviderConfig(provider="env"), environ={"NA_PRIVATE_KEY_SEED": seed} if seed else {})


def test_env_provider_reads_the_seed_from_a_secret_file(tmp_path):
    """NA_PRIVATE_KEY_SEED_FILE: a mounted secret, not an environment value (v1.0.2)."""
    key = nacl.signing.SigningKey.generate()
    secret = tmp_path / "na_seed"
    secret.write_text("# NA seed\n" + _seed_b64(key) + "\n")
    signer = load_signer(KeyProviderConfig(provider="env", key_id="na-1"),
                         environ={"NA_PRIVATE_KEY_SEED_FILE": str(secret)})
    assert signer.provider == "env" and signer.verify_key == key.verify_key


def test_env_provider_refuses_both_or_an_unreadable_seed_file(tmp_path):
    key = nacl.signing.SigningKey.generate()
    secret = tmp_path / "na_seed"
    secret.write_text(_seed_b64(key))
    with pytest.raises(KeyProviderError, match="not both"):
        load_signer(KeyProviderConfig(provider="env"),
                    environ={"NA_PRIVATE_KEY_SEED": _seed_b64(key), "NA_PRIVATE_KEY_SEED_FILE": str(secret)})
    with pytest.raises(KeyProviderError, match="cannot read"):
        load_signer(KeyProviderConfig(provider="env"),
                    environ={"NA_PRIVATE_KEY_SEED_FILE": str(tmp_path / "missing")})


def test_unknown_provider_is_refused():
    with pytest.raises(KeyProviderError):
        load_signer(KeyProviderConfig(provider="hsm"))


class FakeAzure:
    """Managed identity and Key Vault endpoints, recording requests."""

    def __init__(self, seed: str | None, token: str | None = "tok"):
        self.seed = seed
        self.token = token
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> dict:
        self.calls.append((url, headers))
        if "oauth2/token" in url or "/msi/token" in url or "identity" in url:
            return {"access_token": self.token} if self.token else {}
        assert headers["Authorization"] == f"Bearer {self.token}"
        return {"value": self.seed} if self.seed is not None else {}


def test_key_vault_provider_uses_the_vm_managed_identity():
    key = nacl.signing.SigningKey.generate()
    azure = FakeAzure(_seed_b64(key))
    signer = load_signer(
        KeyProviderConfig(provider="azure-keyvault", key_id="na-1",
                          vault_url="https://gm-na.vault.azure.net", secret_name="na-signing-seed"),
        http_get=azure, environ={},
    )
    assert signer.provider == "azure-keyvault" and signer.verify_key == key.verify_key
    token_url, token_headers = azure.calls[0]
    assert token_url.startswith(key_provider.IMDS_TOKEN_URL) and token_headers == {"Metadata": "true"}
    secret_url, _ = azure.calls[1]
    assert secret_url == "https://gm-na.vault.azure.net/secrets/na-signing-seed?api-version=7.4"


def test_key_vault_provider_uses_the_app_service_identity_and_client_id():
    key = nacl.signing.SigningKey.generate()
    azure = FakeAzure(_seed_b64(key))
    env = {"IDENTITY_ENDPOINT": "http://localhost:4141/msi/token", "IDENTITY_HEADER": "h", "AZURE_CLIENT_ID": "cid"}
    load_from_azure_key_vault("https://gm-na.vault.azure.net", "s", http_get=azure, environ=env)
    url, headers = azure.calls[0]
    assert url.startswith("http://localhost:4141/msi/token?") and "client_id=cid" in url
    assert headers == {"X-IDENTITY-HEADER": "h"}


@pytest.mark.parametrize(
    "azure, vault_url",
    [
        (FakeAzure("x", token=None), "https://v.vault.azure.net"),
        (FakeAzure(None), "https://v.vault.azure.net"),
        (FakeAzure("not-a-seed"), "https://v.vault.azure.net"),
        (FakeAzure("x"), "http://v.vault.azure.net"),
    ],
)
def test_key_vault_provider_fails_closed(azure, vault_url):
    with pytest.raises(KeyProviderError):
        load_from_azure_key_vault(vault_url, "s", http_get=azure, environ={})


def test_key_vault_network_errors_fail_closed_without_leaking():
    def broken(url, headers):
        raise OSError("connection refused to 169.254.169.254")

    with pytest.raises(KeyProviderError) as err:
        load_from_azure_key_vault("https://v.vault.azure.net", "s", http_get=broken, environ={})
    assert "OSError" in str(err.value)


def test_settings_default_to_the_v059_behaviour():
    s = load_settings({"GENESIS_FILE": "g.json", "NA_PRIVATE_KEY_FILE": "na.key"})
    assert s.database_url is None and s.ha_mode == "off" and s.rate_limit_store is None
    assert s.key.provider == "file" and s.key.key_file == "na.key"
    assert s.db_path == "genesis_mesh_na.db"


# ── HA mode guard rails ───────────────────────────────────────────────────────


def _service(na_service, **kwargs) -> NetworkAuthorityService:
    return NetworkAuthorityService(
        genesis_block=na_service.genesis_block,
        na_private_key=kwargs.pop("signer", na_service.signer),
        key_id=na_service.key_id,
        operator_public_keys=na_service.operator_public_keys,
        operator_key_tiers=na_service.operator_key_tiers,
        **kwargs,
    )


@pytest.mark.sqlite_only
def test_ha_mode_refuses_sqlite_file_keys_and_per_process_limits(na_service):
    with pytest.raises(ValueError) as err:
        _service(na_service, ha_mode="on", rate_limit_store="memory")
    message = str(err.value)
    assert "PostgreSQL" in message and "non-file provider" in message and "shared database store" in message


def test_unknown_modes_are_refused(na_service):
    with pytest.raises(ValueError):
        _service(na_service, ha_mode="maybe")
    with pytest.raises(ValueError):
        _service(na_service, rate_limit_store="redis")


@pytest.mark.postgres
def test_ha_mode_starts_on_postgres_with_an_env_key(na_service):
    env_signer = Signer(na_service.signer._key, na_service.key_id, "env")
    svc = _service(na_service, signer=env_signer, ha_mode="on")
    assert svc.db.backend == "postgres" and svc.rate_limiter.store == "database"
    ready, checks = svc.readiness()
    assert ready and checks["signing_key"]["provider"] == "env"


@pytest.mark.postgres
def test_ha_mode_refuses_a_file_key_on_postgres(na_service):
    with pytest.raises(ValueError, match="non-file provider"):
        _service(na_service, ha_mode="on")


# ── readiness ─────────────────────────────────────────────────────────────────


def test_readyz_reports_schema_key_and_backend(na_service):
    body = na_service.app.test_client().get("/readyz").get_json()
    assert body["status"] == "ready"
    assert body["database"]["writable"] is True
    assert body["database"]["schema_version"] == body["database"]["expected_schema_version"]
    assert body["signing_key"] == na_service.signer.describe()
    assert "seed" not in str(body).lower() and _seed_b64(na_service.signer._key) not in str(body)


def test_readyz_is_not_ready_when_schema_is_behind(na_service):
    with na_service.db.conn:
        na_service.db.conn.execute("DELETE FROM schema_version WHERE version = (SELECT MAX(version) FROM schema_version)")
    resp = na_service.app.test_client().get("/readyz")
    assert resp.status_code == 503
    assert resp.get_json()["error"]["details"]["database"]["error"] == "schema_version_mismatch"


def test_default_policy_is_signed_through_the_signer(na_service):
    policy: PolicyManifest = na_service._get_default_policy()
    assert policy.signatures[0].key_id == na_service.signer.key_id


class _ReadOnlySqlite:
    """A sqlite3 connection whose writes fail as on a read-only file."""

    def __init__(self, conn, message):
        self._conn, self._message = conn, message

    def execute(self, sql, *args):
        if sql.startswith(("BEGIN IMMEDIATE", "INSERT", "CREATE")):
            import sqlite3
            raise sqlite3.OperationalError(self._message)
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.mark.sqlite_only
def test_readyz_reports_an_unwritable_sqlite_database(na_service):
    """A database that answers SELECT but refuses writes is not ready (v1.0.2)."""
    na_service.db.conn = _ReadOnlySqlite(na_service.db.conn, "attempt to write a readonly database")
    resp = na_service.app.test_client().get("/readyz")
    assert resp.status_code == 503
    assert resp.get_json()["error"]["details"]["database"]["writable"] is False


@pytest.mark.sqlite_only
def test_readyz_treats_a_locked_sqlite_database_as_writable(na_service):
    """Another writer holding the lock proves the file is writable; readiness must not flap."""
    na_service.db.conn = _ReadOnlySqlite(na_service.db.conn, "database is locked")
    resp = na_service.app.test_client().get("/readyz")
    assert resp.status_code == 200
    assert resp.get_json()["database"]["writable"] is True


@pytest.mark.sqlite_only
def test_the_readiness_write_probe_leaves_no_trace(na_service):
    assert na_service.app.test_client().get("/readyz").status_code == 200
    assert "readiness_write_probe" not in na_service.db.table_names()
