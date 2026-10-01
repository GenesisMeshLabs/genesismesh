"""The Network Authority's signing key: one ``Signer``, several providers (v0.60).

Every NA signature goes through a ``Signer``. It exposes the operations NA
code needs -- ``sign(message)`` (the same shape as ``nacl.signing.SigningKey``,
so the trust layer's ``sign_model`` works unchanged), ``verify_key``,
``key_id`` and a public fingerprint -- and never the seed itself. A future
remote-signing provider (an HSM with Ed25519, for example) can implement the
same interface without changing any caller.

Providers load the seed:

* ``file``: today's behaviour, a local key file (``NA_PRIVATE_KEY_FILE``).
* ``env``: a base64 seed injected by the platform's secret store into the
  process environment (``NA_PRIVATE_KEY_SEED``); nothing is written to disk.
* ``azure-keyvault``: the seed is a Key Vault secret, read at start-up with
  the instance's managed identity and held in memory only.

HA mode refuses ``file`` so several hosts cannot quietly share key files.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

import nacl.encoding
import nacl.signing

from ..crypto import load_private_key, sign_model
from ..models.genesis import Signature

KEY_PROVIDERS = ("file", "env", "azure-keyvault")

#: Azure Key Vault data-plane API version used to read the secret.
KEY_VAULT_API_VERSION = "7.4"
KEY_VAULT_RESOURCE = "https://vault.azure.net"
IMDS_TOKEN_URL = "http://169.254.169.254/metadata/identity/oauth2/token"


class KeyProviderError(RuntimeError):
    """The signing key could not be loaded. The NA must not start without it."""


class Signer:
    """The NA signing key, usable for signing and never readable.

    Deliberately not a ``nacl.signing.SigningKey``: there is no ``encode()``
    and no seed accessor, so code holding the signer cannot export the key.
    """

    __slots__ = ("_key", "key_id", "provider")

    def __init__(self, signing_key: nacl.signing.SigningKey, key_id: str, provider: str) -> None:
        self._key = signing_key
        self.key_id = key_id
        self.provider = provider

    @property
    def verify_key(self) -> nacl.signing.VerifyKey:
        return self._key.verify_key

    @property
    def public_key_b64(self) -> str:
        return self._key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode("utf-8")

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the raw public key, hex; safe to publish and compare across instances."""
        return hashlib.sha256(self._key.verify_key.encode()).hexdigest()

    def sign(self, message: bytes) -> nacl.signing.SignedMessage:
        """Sign ``message`` (same contract as ``nacl.signing.SigningKey.sign``)."""
        return self._key.sign(message)

    def sign_model(self, model: Any) -> Signature:
        """Sign a protocol model's canonical form with this key and key id."""
        return sign_model(model, self, self.key_id)  # type: ignore[arg-type]

    def describe(self) -> dict[str, str]:
        return {"key_id": self.key_id, "provider": self.provider, "fingerprint": self.fingerprint}

    def __repr__(self) -> str:
        return f"Signer(key_id={self.key_id!r}, provider={self.provider!r}, fingerprint={self.fingerprint[:16]}…)"


def _seed_from_text(text: str) -> nacl.signing.SigningKey:
    """Parse a base64 Ed25519 seed (comment lines starting with '#' ignored)."""
    body = "".join(line.strip() for line in text.splitlines() if not line.startswith("#"))
    try:
        seed = base64.b64decode(body, validate=True)
    except ValueError as exc:
        raise KeyProviderError("signing key is not valid base64") from exc
    if len(seed) != 32:
        raise KeyProviderError(f"signing key must be a 32-byte Ed25519 seed, got {len(seed)} bytes")
    return nacl.signing.SigningKey(seed)


HttpGet = Callable[[str, dict[str, str]], dict[str, Any]]


def _http_get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed Azure endpoints
        return json.loads(response.read().decode("utf-8"))


def _managed_identity_token(http_get: HttpGet, environ: dict[str, str]) -> str:
    """Get a Key Vault access token for the instance's managed identity.

    App Service and Container Apps expose ``IDENTITY_ENDPOINT`` and
    ``IDENTITY_HEADER``; virtual machines use the instance metadata service.
    ``AZURE_CLIENT_ID`` selects a user-assigned identity.
    """
    client_id = environ.get("AZURE_CLIENT_ID")
    endpoint = environ.get("IDENTITY_ENDPOINT")
    if endpoint and environ.get("IDENTITY_HEADER"):
        params = {"api-version": "2019-08-01", "resource": KEY_VAULT_RESOURCE}
        if client_id:
            params["client_id"] = client_id
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        headers = {"X-IDENTITY-HEADER": environ["IDENTITY_HEADER"]}
    else:
        params = {"api-version": "2018-02-01", "resource": KEY_VAULT_RESOURCE}
        if client_id:
            params["client_id"] = client_id
        url = f"{IMDS_TOKEN_URL}?{urllib.parse.urlencode(params)}"
        headers = {"Metadata": "true"}
    token = http_get(url, headers).get("access_token")
    if not token:
        raise KeyProviderError("managed identity returned no access token")
    return str(token)


def load_from_azure_key_vault(
    vault_url: str,
    secret_name: str,
    *,
    http_get: Optional[HttpGet] = None,
    environ: Optional[dict[str, str]] = None,
) -> nacl.signing.SigningKey:
    """Read the Ed25519 seed stored as a Key Vault secret, with the managed identity."""
    get = http_get or _http_get_json
    env = dict(os.environ) if environ is None else environ
    parsed = urllib.parse.urlsplit(vault_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise KeyProviderError("AZURE_KEY_VAULT_URL must be an https URL")
    try:
        token = _managed_identity_token(get, env)
        url = (
            f"https://{parsed.netloc}/secrets/{urllib.parse.quote(secret_name, safe='')}"
            f"?api-version={KEY_VAULT_API_VERSION}"
        )
        secret = get(url, {"Authorization": f"Bearer {token}"})
    except KeyProviderError:
        raise
    except Exception as exc:  # network, HTTP or JSON errors: fail closed with context
        raise KeyProviderError(f"could not read the signing key from Key Vault: {type(exc).__name__}") from exc
    value = secret.get("value")
    if not isinstance(value, str) or not value:
        raise KeyProviderError("Key Vault secret has no value")
    return _seed_from_text(value)


@dataclass(frozen=True)
class KeyProviderConfig:
    provider: str = "file"
    key_id: str = "na-2025-q1"
    key_file: Optional[str] = None
    seed_env_var: str = "NA_PRIVATE_KEY_SEED"
    vault_url: Optional[str] = None
    secret_name: Optional[str] = None


def load_signer(
    config: KeyProviderConfig,
    *,
    http_get: Optional[HttpGet] = None,
    environ: Optional[dict[str, str]] = None,
) -> Signer:
    """Load the NA signing key from the configured provider."""
    env = dict(os.environ) if environ is None else environ
    if config.provider == "file":
        if not config.key_file:
            raise KeyProviderError("the file key provider needs NA_PRIVATE_KEY_FILE")
        return Signer(load_private_key(config.key_file), config.key_id, "file")
    if config.provider == "env":
        seed = env.get(config.seed_env_var)
        if not seed:
            raise KeyProviderError(f"the env key provider needs {config.seed_env_var}")
        return Signer(_seed_from_text(seed), config.key_id, "env")
    if config.provider == "azure-keyvault":
        if not config.vault_url or not config.secret_name:
            raise KeyProviderError(
                "the azure-keyvault key provider needs AZURE_KEY_VAULT_URL and NA_KEY_SECRET_NAME"
            )
        key = load_from_azure_key_vault(config.vault_url, config.secret_name, http_get=http_get, environ=env)
        return Signer(key, config.key_id, "azure-keyvault")
    raise KeyProviderError(f"unknown key provider {config.provider!r}; expected one of {KEY_PROVIDERS}")


def as_signer(key: "Signer | nacl.signing.SigningKey", key_id: str) -> Signer:
    """Wrap a raw signing key (tests, CLI, legacy callers) as a file-provider signer."""
    if isinstance(key, Signer):
        return key
    if isinstance(key, nacl.signing.SigningKey):
        return Signer(key, key_id, "file")
    raise TypeError("na_private_key must be a Signer or nacl.signing.SigningKey")
