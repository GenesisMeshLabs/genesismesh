"""A governed Network Authority for SDK development, and admin limits (v1.1.0).

A pilot controller built on the TypeScript SDK showed what an SDK developer
hits first: ``na start`` could not run a governed NA (no enforcement, one
operator key, no rate-limit settings), no command created an operator key,
and the admin limit of 30 a minute per address stopped a governed workload
within seconds. 1.1.0 adds ``na start --env-file`` (the production app and
settings), ``init --env-file`` and ``keygen operator``, raises the admin limit
to 300 and holds failed admin authentications to the old 30.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli import ops as cli_ops
from genesis_mesh.cli.env_file import EnvFileError, read_env_file, register_operator_key
from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.na_service.app_factory import build_app
from genesis_mesh.na_service.errors import RETRY_AFTER_SECONDS
from genesis_mesh.na_service.rate_limit import DatabaseRateLimiter, RateLimiter, RateLimits
from genesis_mesh.na_service.settings import load_settings

from .test_na_boundary_policy import _get, _headers, _make_service, _post


def _client(remote_addr: str = "10.0.0.1", **kwargs):
    service = _make_service(**kwargs)
    service.app.config["TESTING"] = True
    client = service.app.test_client()
    client.environ_base["REMOTE_ADDR"] = remote_addr
    setattr(client, "operator_keypair", getattr(service, "_test_operator_keypair"))
    setattr(client, "std_keypair", getattr(service, "_std_keypair"))
    setattr(client, "service", service)
    return client


def _bad_admin(client, nonce: str, key_id: str = "operator-test"):
    return client.get(
        "/admin/boundary-policies",
        headers={
            "X-Admin-Key-Id": key_id,
            "X-Admin-Signature": "AAAA",
            "X-Admin-Timestamp": "2026-01-01T00:00:00Z",
            "X-Admin-Nonce": nonce,
        },
    )


def _audit_types(client) -> list[str]:
    return [e["event_type"] for e in client.service.db.list_audit_events()]


# --- Limits -----------------------------------------------------------------


def test_failed_auth_limit_comes_from_the_environment():
    settings = load_settings(
        {"GENESIS_FILE": "g.json", "NA_RATE_LIMIT_ADMIN_AUTH_FAILURES_PER_MINUTE": "5"}
    )
    assert settings.rate_limits.admin_auth_failures == 5


def test_failed_auth_limit_below_one_is_refused():
    with pytest.raises(ValueError):
        RateLimits(admin_auth_failures=0)


def _one_window(client) -> None:
    """Keep a fixed-window limiter in a single window for the whole test.

    On PostgreSQL the NA counts requests in clock-aligned minutes
    (``DatabaseRateLimiter``), so a test whose requests straddle a minute
    boundary would see the count reset half way.
    """
    if isinstance(client.service.rate_limiter, DatabaseRateLimiter):
        frozen = time.time()
        client.service.rate_limiter = DatabaseRateLimiter(client.service.db, clock=lambda: frozen)


def test_300_signed_admin_requests_a_minute_pass_at_the_default():
    client = _client()
    _one_window(client)
    statuses = [_get(client, "/admin/boundary-policies").status_code for _ in range(300)]
    assert statuses == [200] * 300
    over = _get(client, "/admin/boundary-policies")
    assert over.status_code == 429
    assert over.get_json()["error"]["code"] == "rate_limit_exceeded"


def test_valid_admin_requests_do_not_count_as_failures():
    client = _client(rate_limits=RateLimits(admin_auth_failures=2))
    statuses = [_get(client, "/admin/boundary-policies").status_code for _ in range(5)]
    assert statuses == [200] * 5


def test_an_address_with_too_many_failures_is_refused_before_verification():
    client = _client(rate_limits=RateLimits(admin_auth_failures=3))
    statuses = [_bad_admin(client, f"n{i}").status_code for i in range(3)]
    assert statuses == [401, 401, 401]

    throttled = _bad_admin(client, "n3")
    assert throttled.status_code == 429
    assert throttled.get_json()["error"]["code"] == "admin_auth_throttled"
    assert throttled.headers["Retry-After"] == str(RETRY_AFTER_SECONDS)

    # A correctly signed request with the same key from the same address waits
    # out the window too: the limit is checked before any signature.
    assert _get(client, "/admin/boundary-policies").status_code == 429


def test_one_keys_failures_do_not_lock_out_another_key_at_the_same_address():
    """v1.2.0: an operator behind a shared address (a gateway) keeps working."""
    client = _client()
    _one_window(client)
    statuses = [_bad_admin(client, f"n{i}", key_id="operator-std").status_code for i in range(31)]
    assert statuses == [401] * 30 + [429]
    assert _bad_admin(client, "n31", key_id="operator-std").get_json()["error"]["code"] == "admin_auth_throttled"
    assert _get(client, "/admin/boundary-policies").status_code == 200
    throttled = [e for e in client.service.db.list_audit_events() if e["event_type"] == "admin_auth_throttled"]
    assert [e["details"].get("key_id") for e in throttled] == ["operator-std"]


@pytest.mark.parametrize(
    "key_id", ["someone-else", None, "x" * 300], ids=["unknown key", "no key", "oversized key"]
)
def test_failures_without_an_active_key_throttle_only_requests_without_one(key_id):
    """v1.2.0: an operator who mistypes the key ID does not lock out the others."""
    client = _client(rate_limits=RateLimits(admin_auth_failures=2))
    for i in range(2):
        if key_id is None:
            response = client.get("/admin/boundary-policies")
        else:
            response = _bad_admin(client, f"n{i}", key_id=key_id)
        assert response.status_code == 401
    assert _bad_admin(client, "n2", key_id="anyone").status_code == 429
    assert client.get("/admin/boundary-policies").status_code == 429
    assert _get(client, "/admin/boundary-policies").status_code == 200


def test_a_revoked_key_counts_like_an_unknown_one():
    """v1.2.0: counting a revoked key apart would tell a prober it was revoked (F-21)."""
    client = _client(rate_limits=RateLimits(admin_auth_failures=2))
    client.service.db.revoke_operator_key("operator-std", "test", "operator-test", datetime.now(timezone.utc))
    for i in range(2):
        assert _bad_admin(client, f"n{i}", key_id="operator-std").status_code == 401
    assert _bad_admin(client, "n2", key_id="someone-else").status_code == 429
    assert _get(client, "/admin/boundary-policies").status_code == 200


def test_oversized_headers_count_against_the_address_even_with_an_active_key():
    client = _client(rate_limits=RateLimits(admin_auth_failures=2))
    for i in range(2):
        response = client.get("/admin/boundary-policies", headers={
            "X-Admin-Key-Id": "operator-test", "X-Admin-Signature": "A" * 300,
            "X-Admin-Timestamp": "2026-01-01T00:00:00Z", "X-Admin-Nonce": f"n{i}",
        })
        assert response.status_code == 401
    assert _bad_admin(client, "n2", key_id="someone-else").status_code == 429
    assert _get(client, "/admin/boundary-policies").status_code == 200


def test_all_failures_from_one_address_are_capped(monkeypatch):
    """v1.2.0: per-key scopes do not multiply what one address may cost."""
    from genesis_mesh.na_service import auth

    monkeypatch.setattr(auth, "ADDRESS_FAILURE_MULTIPLE", 1)
    client = _client(rate_limits=RateLimits(admin_auth_failures=3))
    assert [_bad_admin(client, f"s{i}", key_id="operator-std").status_code for i in range(2)] == [401, 401]
    assert _bad_admin(client, "u0", key_id="someone-else").status_code == 401
    # Three failures in three scopes: the address cap is reached, every request waits.
    assert _get(client, "/admin/boundary-policies").status_code == 429
    events = [e for e in client.service.db.list_audit_events() if e["event_type"] == "admin_auth_throttled"]
    assert events[-1]["details"]["scope"] == "all"


def test_a_key_throttled_at_one_address_works_from_another():
    service = _make_service(rate_limits=RateLimits(admin_auth_failures=1))
    service.app.config["TESTING"] = True
    shared = service.app.test_client()
    shared.environ_base["REMOTE_ADDR"] = "10.0.0.66"
    _bad_admin(shared, "n0")
    assert _bad_admin(shared, "n1").status_code == 429
    other = service.app.test_client()
    other.environ_base["REMOTE_ADDR"] = "10.0.0.2"
    setattr(other, "operator_keypair", service._test_operator_keypair)
    assert _get(other, "/admin/boundary-policies").status_code == 200


def test_throttled_requests_write_one_audit_event_per_window():
    client = _client(rate_limits=RateLimits(admin_auth_failures=2))
    for i in range(2):
        _bad_admin(client, f"n{i}")
    for i in range(2, 12):
        assert _bad_admin(client, f"n{i}").status_code == 429
    types = _audit_types(client)
    assert types.count("admin_auth_failed") == 2
    assert types.count("admin_auth_throttled") == 1


def test_insufficient_tier_counts_as_a_failure_of_that_key():
    client = _client(rate_limits=RateLimits(admin_auth_failures=2))
    body = {"policy_id": "p"}
    url = "/admin/boundary-policies/p/deactivate"
    for _ in range(2):
        assert _post(client, url, body, standard=True).status_code == 403
    assert _post(client, url, body, standard=True).status_code == 429
    assert _get(client, "/admin/boundary-policies").status_code == 200


def test_another_address_is_not_throttled():
    service = _make_service(rate_limits=RateLimits(admin_auth_failures=1))
    service.app.config["TESTING"] = True
    attacker = service.app.test_client()
    attacker.environ_base["REMOTE_ADDR"] = "10.0.0.66"
    _bad_admin(attacker, "n0")
    assert _bad_admin(attacker, "n1").status_code == 429

    operator = service.app.test_client()
    operator.environ_base["REMOTE_ADDR"] = "10.0.0.2"
    setattr(operator, "operator_keypair", service._test_operator_keypair)
    assert _get(operator, "/admin/boundary-policies").status_code == 200


def test_the_database_store_throttles_across_instances(tmp_path):
    db_file = str(tmp_path / "na.db")
    first = _client(rate_limits=RateLimits(admin_auth_failures=2), db_path=db_file, rate_limit_store="database")
    for i in range(2):
        assert _bad_admin(first, f"n{i}").status_code == 401
    # A second NA on the same database sees the same failure count.
    second = _client(rate_limits=RateLimits(admin_auth_failures=2), db_path=db_file, rate_limit_store="database")
    assert _bad_admin(second, "n9").status_code == 429


def test_every_429_carries_retry_after():
    client = _client(rate_limits=RateLimits(admin=1))
    _get(client, "/admin/boundary-policies")
    response = _get(client, "/admin/boundary-policies")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


@pytest.mark.parametrize("store", ["memory", "database"])
def test_exceeded_reads_without_counting(store, tmp_path):
    if store == "memory":
        limiter: RateLimiter | DatabaseRateLimiter = RateLimiter()
    else:
        limiter = DatabaseRateLimiter(_make_service(db_path=str(tmp_path / "na.db")).db)
    assert not limiter.exceeded("k", 2, 60)
    for _ in range(5):
        limiter.exceeded("k", 2, 60)
    assert limiter.allow("k", 2, 60) and limiter.allow("k", 2, 60)
    assert limiter.exceeded("k", 2, 60)
    assert not limiter.allow("k", 2, 60)


# --- Settings files -----------------------------------------------------------


def test_read_env_file_resolves_paths_against_the_file(tmp_path):
    env = tmp_path / "local" / "na.env"
    env.parent.mkdir()
    absolute = (tmp_path / "elsewhere" / "na.key").resolve()
    lines = [
        "# comment",
        "",
        "GENESIS_FILE=keys/genesis.json",
        f"NA_PRIVATE_KEY_FILE={absolute}",
        "DB_PATH=:memory:",
        "EVIDENCE_STORE=on",
    ]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    values = read_env_file(env)
    assert Path(values["GENESIS_FILE"]) == (env.parent / "keys" / "genesis.json").resolve()
    assert Path(values["NA_PRIVATE_KEY_FILE"]) == absolute
    assert values["DB_PATH"] == ":memory:"
    assert values["EVIDENCE_STORE"] == "on"


@pytest.mark.parametrize(
    "text, message",
    [("NOT A SETTING\n", "expected KEY=VALUE"), ("A=1\nA=2\n", "set twice"), ("1A=x\n", "invalid setting name")],
)
def test_read_env_file_refuses_ambiguous_files(tmp_path, text, message):
    env = tmp_path / "na.env"
    env.write_text(text, encoding="utf-8")
    with pytest.raises(EnvFileError, match=message):
        read_env_file(env)


def test_register_operator_key_keeps_other_lines(tmp_path):
    env = tmp_path / "na.env"
    env.write_text("# keep me\nEVIDENCE_STORE=on\nOPERATOR_PUBLIC_KEYS_JSON={\"a\":\"pa\"}\n", encoding="utf-8")
    register_operator_key(env, "b", "pb", "standard")
    text = env.read_text(encoding="utf-8")
    assert text.startswith("# keep me\nEVIDENCE_STORE=on\n")
    values = read_env_file(env)
    assert json.loads(values["OPERATOR_PUBLIC_KEYS_JSON"]) == {"a": "pa", "b": "pb"}
    assert json.loads(values["OPERATOR_KEY_TIERS_JSON"]) == {"b": "standard"}


def test_register_operator_key_refuses_an_unknown_tier(tmp_path):
    env = tmp_path / "na.env"
    env.write_text("EVIDENCE_STORE=on" + chr(10), encoding="utf-8")
    with pytest.raises(EnvFileError, match="tier"):
        register_operator_key(env, "a", "pa", "admin")


def test_register_operator_key_refuses_a_different_key_for_a_known_id(tmp_path):
    env = tmp_path / "na.env"
    env.write_text("OPERATOR_PUBLIC_KEYS_JSON={\"a\":\"pa\"}\n", encoding="utf-8")
    with pytest.raises(EnvFileError, match="--replace"):
        register_operator_key(env, "a", "other", "standard")
    register_operator_key(env, "a", "other", "privileged", replace=True)
    assert json.loads(read_env_file(env)["OPERATOR_PUBLIC_KEYS_JSON"]) == {"a": "other"}


# --- CLI ----------------------------------------------------------------------


def _init(runner: CliRunner, *extra: str):
    return runner.invoke(
        cli,
        ["init", "--config", "local/genesis-mesh.toml", "--home", "local/.genesis-mesh",
         "--network-name", "DEV", "--env-file", "local/na.env", *extra],
    )


def test_init_writes_governed_settings_without_private_keys(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = _init(runner)
        assert result.exit_code == 0, result.output
        values = read_env_file(Path("local/na.env"))
        assert values["BOUNDARY_POLICY_ENFORCEMENT"] == "required"
        assert values["EVIDENCE_STORE"] == "on"
        assert values["NA_PROXY_HOPS"] == "0"
        assert values["PORT"] == "8443"
        assert json.loads(values["OPERATOR_KEY_TIERS_JSON"]) == {"operator-local": "privileged"}
        assert Path(values["GENESIS_FILE"]).is_file()
        private = Path("local/.genesis-mesh/keys/operator.key").read_text(encoding="utf-8")
        secret = [line for line in private.splitlines() if not line.startswith("#")][0]
        assert secret not in Path("local/na.env").read_text(encoding="utf-8")

        again = _init(runner)
        assert again.exit_code != 0 and "already exists" in again.output

        forced = _init(runner, "--force", "--na-port", "9444")
        assert forced.exit_code == 0, forced.output
        assert read_env_file(Path("local/na.env"))["PORT"] == "9444"


def test_keygen_operator_registers_a_standard_key(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert _init(runner).exit_code == 0
        result = runner.invoke(
            cli,
            ["keygen", "operator", "--output", "local/keys/controller", "--key-id", "controller",
             "--env-file", "local/na.env"],
        )
        assert result.exit_code == 0, result.output
        values = read_env_file(Path("local/na.env"))
        tiers = json.loads(values["OPERATOR_KEY_TIERS_JSON"])
        assert tiers == {"controller": "standard", "operator-local": "privileged"}
        public = Path("local/keys/controller.pub").read_text(encoding="utf-8").splitlines()[-1]
        assert json.loads(values["OPERATOR_PUBLIC_KEYS_JSON"])["controller"] == public

        again = runner.invoke(
            cli, ["keygen", "operator", "--output", "local/keys/controller", "--key-id", "controller"]
        )
        assert again.exit_code != 0 and "already exists" in again.output

        clash = runner.invoke(
            cli,
            ["keygen", "operator", "--output", "local/keys/other", "--key-id", "controller",
             "--env-file", "local/na.env"],
        )
        assert clash.exit_code != 0 and "--replace" in clash.output
        assert not Path("local/keys/other.key").exists()


def _start(runner: CliRunner, monkeypatch, *args: str):
    captured: dict = {}
    monkeypatch.setattr(
        cli_ops, "run_simple",
        lambda **kwargs: captured.update(kwargs),
    )
    result = runner.invoke(cli, ["na", "start", *args])
    return result, captured


def test_na_start_env_file_serves_the_governed_production_app(tmp_path, monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert _init(runner).exit_code == 0
        assert runner.invoke(
            cli,
            ["keygen", "operator", "--output", "local/keys/controller", "--key-id", "controller",
             "--env-file", "local/na.env"],
        ).exit_code == 0
        # The shell environment is not read: only the file configures the NA.
        monkeypatch.setenv("BOUNDARY_POLICY_ENFORCEMENT", "optional")
        monkeypatch.setenv("NA_RATE_LIMIT_ADMIN_PER_MINUTE", "5")
        result, captured = _start(runner, monkeypatch, "--env-file", "local/na.env")
        assert result.exit_code == 0, result.output
        # PORT from the file; --port still overrides it.
        assert captured["port"] == 8443 and captured["hostname"] == "127.0.0.1"
        _, overridden = _start(runner, monkeypatch, "--env-file", "local/na.env", "--port", "9555")
        assert overridden["port"] == 9555
        service = captured["application"].extensions["genesis_mesh_na"]
        assert service.boundary_policy_enforcement == "required"
        assert service.evidence_store == "on"
        assert service.operator_key_tiers == {"controller": "standard", "operator-local": "privileged"}
        assert service.rate_limits == RateLimits()
        assert "controller (standard)" in result.output


def test_na_start_env_file_refuses_config_options(tmp_path, monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("na.env").write_text("GENESIS_FILE=g.json\n", encoding="utf-8")
        result, captured = _start(runner, monkeypatch, "--env-file", "na.env", "--evidence-store", "on")
        assert result.exit_code != 0 and "--env-file is the whole configuration" in result.output
        assert not captured


def test_na_start_env_file_reports_a_missing_setting(tmp_path, monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("na.env").write_text("EVIDENCE_STORE=on\n", encoding="utf-8")
        result, _ = _start(runner, monkeypatch, "--env-file", "na.env")
        assert result.exit_code != 0
        assert "GENESIS_FILE is required" in result.output
        assert "Traceback" not in result.output


def test_na_start_without_env_file_keeps_the_single_privileged_key(tmp_path, monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert _init(runner).exit_code == 0
        result, captured = _start(runner, monkeypatch, "--config", "local/genesis-mesh.toml")
        assert result.exit_code == 0, result.output
        service = captured["application"].extensions["genesis_mesh_na"]
        assert service.operator_key_tiers == {"operator-local": "privileged"}
        assert service.boundary_policy_enforcement == "optional"


def test_build_app_trusts_exactly_the_configured_proxies(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert _init(runner).exit_code == 0
        values = read_env_file(Path("local/na.env"))
        direct = build_app(load_settings(values))
        assert direct.wsgi_app.__class__.__name__ != "ProxyFix"
        proxied = build_app(load_settings({**values, "NA_PROXY_HOPS": "1", "DB_PATH": ":memory:"}))
        assert proxied.wsgi_app.__class__.__name__ == "ProxyFix"


def test_a_standard_key_from_keygen_operator_cannot_publish_policies(tmp_path, monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert _init(runner).exit_code == 0
        keypair = generate_keypair()
        register_operator_key(Path("local/na.env"), "controller", keypair.public_key_b64, "standard")
        app = build_app(load_settings(read_env_file(Path("local/na.env"))))
        app.config["TESTING"] = True
        client = app.test_client()
        body = {"policy_id": "p"}
        url = "/admin/boundary-policies"
        response = client.post(
            url, json=body,
            headers=_headers(keypair, "controller", body, client=client, method="POST", url=url),
        )
        assert response.status_code == 403
        assert response.get_json()["error"]["code"] == "insufficient_operator_tier"


def test_na_start_env_file_reports_a_key_provider_error_without_traceback(tmp_path, monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert _init(runner).exit_code == 0
        env = Path("local/na.env")
        lines = [
            line for line in env.read_text(encoding="utf-8").splitlines()
            if not line.startswith("NA_PRIVATE_KEY_FILE=")
        ]
        env.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        result, captured = _start(runner, monkeypatch, "--env-file", "local/na.env")
        assert result.exit_code != 0 and not captured
        assert "NA_PRIVATE_KEY_FILE" in result.output
        assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "line, message",
    [
        ("NA_RATE_LIMIT_ADMIN_PER_MINUTE=many", "NA_RATE_LIMIT_ADMIN_PER_MINUTE must be an integer"),
        ("OPERATOR_KEY_TIERS_JSON='{}'", "OPERATOR_KEY_TIERS_JSON is not valid JSON"),
        ("NA_PROXY_HOPS=one", "NA_PROXY_HOPS must be an integer"),
    ],
)
def test_na_start_env_file_names_a_bad_setting(tmp_path, monkeypatch, line, message):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("na.env").write_text("GENESIS_FILE=g.json" + chr(10) + line + chr(10), encoding="utf-8")
        result, _ = _start(runner, monkeypatch, "--env-file", "na.env")
        assert result.exit_code != 0
        assert message in result.output


def test_an_empty_value_counts_as_unset(tmp_path):
    env = tmp_path / "na.env"
    env.write_text("DB_PATH=" + chr(10) + "EVIDENCE_STORE=on" + chr(10), encoding="utf-8")
    assert read_env_file(env) == {"EVIDENCE_STORE": "on"}


def test_keygen_operator_failure_leaves_neither_files_nor_registration(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert _init(runner).exit_code == 0
        Path("local/blocker").write_text("not a directory", encoding="utf-8")
        failed = runner.invoke(
            cli,
            ["keygen", "operator", "--output", "local/blocker/controller", "--key-id", "controller",
             "--env-file", "local/na.env"],
        )
        assert failed.exit_code != 0
        tiers = json.loads(read_env_file(Path("local/na.env"))["OPERATOR_KEY_TIERS_JSON"])
        assert "controller" not in tiers

        retry = runner.invoke(
            cli,
            ["keygen", "operator", "--output", "local/keys/controller", "--key-id", "controller",
             "--env-file", "local/na.env"],
        )
        assert retry.exit_code == 0, retry.output


def test_keygen_operator_refuses_an_empty_key_id(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["keygen", "operator", "--output", "k/op", "--key-id", " "])
        assert result.exit_code != 0 and "must not be empty" in result.output
        assert not Path("k/op.key").exists()


def test_init_refuses_an_env_file_that_is_another_output(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["init", "--config", "local/genesis-mesh.toml", "--home", "local/.genesis-mesh",
             "--network-name", "DEV", "--env-file", "local/genesis-mesh.toml"],
        )
        assert result.exit_code != 0 and "another output of init" in result.output
        assert not Path("local/genesis-mesh.toml").exists()


def test_a_throttled_address_is_recorded_once_per_window(tmp_path):
    client = _client(
        rate_limits=RateLimits(admin_auth_failures=1), db_path=str(tmp_path / "na.db"), rate_limit_store="database"
    )
    _bad_admin(client, "n0")
    for i in range(1, 6):
        assert _bad_admin(client, f"n{i}").status_code == 429
    db = client.service.db
    rows = db.conn.execute(
        "SELECT hits FROM rate_limit_windows WHERE bucket LIKE 'admin_auth_throttled:%'"
    ).fetchall()
    assert [int(r[0]) for r in rows] == [1]
