"""1.11.0: the container jobs test the gateway release pinned in ``contract/consumer-pins.json``.

``scripts/consumer_pins.py gateway`` resolves the pinned tag on GitHub and
prints the image by digest, the version and commit it must report and the
identity its signature must carry. ``ci.yml`` and ``publish-image.yml`` verify
that signature, pull the image by digest and run ``container_smoke.py`` with
``--gateway-version`` / ``--gateway-revision``: no gateway is built from a
branch or from ``main``. These tests stub GitHub and Docker; no network access.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
_spec = importlib.util.spec_from_file_location("consumer_pins", REPO_ROOT / "scripts" / "consumer_pins.py")
assert _spec and _spec.loader
pins = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pins)

DIGEST = "sha256:" + "ab" * 32
REVISION = "d3db678a1a56e8af7f55cf45fd8d8ffa20d94ff9"


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "consumer-pins.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _valid(gateway: object | None = None) -> dict[str, object]:
    data: dict[str, object] = {"schema": pins.SCHEMA}
    data["gateway"] = {"ref": "v1.10.1", "image": DIGEST} if gateway is None else gateway
    for name in pins.CONSUMERS:
        data[name] = {"ref": "v1.10.1"}
    return data


# -- the pin ------------------------------------------------------------------

def test_the_committed_gateway_pin_is_a_release_and_its_image_digest() -> None:
    gateway = pins.load_gateway()
    assert pins.TAG.fullmatch(gateway.ref)
    assert pins.DIGEST.fullmatch(gateway.digest)
    assert gateway.image == f"ghcr.io/genesismeshlabs/genesis-mesh-gateway@{gateway.digest}"
    assert gateway.version == gateway.ref.removeprefix("v")
    # Signed by the gateway's own release workflow at the pinned tag, nothing else.
    assert gateway.identity == ("https://github.com/GenesisMeshLabs/gateway/.github/workflows/distribution.yml"
                                f"@refs/tags/{gateway.ref}")


def test_a_valid_gateway_pin_loads(tmp_path: Path) -> None:
    gateway = pins.load_gateway(_write(tmp_path, _valid()))
    assert (gateway.ref, gateway.digest, gateway.version) == ("v1.10.1", DIGEST, "1.10.1")


@pytest.mark.parametrize("ref", ["main", REVISION, "1.10.1", "v1.10", "v1.10.1-rc1", "", "v1.10.1\n"])
def test_the_gateway_is_pinned_to_a_release_tag_only(tmp_path: Path, ref: str) -> None:
    # A commit has no published image: the gateway pin names a release.
    with pytest.raises(pins.PinError, match="not a release tag"):
        pins.load_gateway(_write(tmp_path, _valid({"ref": ref, "image": DIGEST})))


@pytest.mark.parametrize("image", ["", "latest", "1.10.1", "ab" * 32, "sha256:" + "AB" * 32, "sha256:" + "ab" * 31,
                                   "sha512:" + "ab" * 64, f"ghcr.io/genesismeshlabs/genesis-mesh-gateway@{DIGEST}",
                                   DIGEST + "\n"])
def test_the_gateway_image_is_an_index_digest_only(tmp_path: Path, image: str) -> None:
    # Never a tag that can move, never a whole reference that could name another registry.
    with pytest.raises(pins.PinError, match="not an image digest"):
        pins.load_gateway(_write(tmp_path, _valid({"ref": "v1.10.1", "image": image})))


@pytest.mark.parametrize("entry", [
    {"ref": "v1.10.1"},
    {"image": DIGEST},
    {"ref": "v1.10.1", "image": DIGEST, "note": "x"},
    {"ref": "v1.10.1", "image": 1},
    "v1.10.1",
    [],
])
def test_a_malformed_gateway_entry_is_refused(tmp_path: Path, entry: object) -> None:
    with pytest.raises(pins.PinError, match="gateway must be"):
        pins.load_gateway(_write(tmp_path, _valid(entry)))


def test_a_file_without_the_gateway_is_refused_for_the_sdks_too(tmp_path: Path) -> None:
    data = _valid()
    data.pop("gateway")
    path = _write(tmp_path, data)
    with pytest.raises(pins.PinError, match="expected"):
        pins.load(path)
    with pytest.raises(pins.PinError, match="expected"):
        pins.load_gateway(path)


def test_a_bad_sdk_pin_fails_the_gateway_too(tmp_path: Path) -> None:
    # The file is valid as a whole or not at all.
    data = _valid()
    data["sdk-go"] = {"ref": "main"}
    with pytest.raises(pins.PinError, match="neither a release tag"):
        pins.load_gateway(_write(tmp_path, data))


# -- the command --------------------------------------------------------------

def _github(asked: list[str], sha: str = REVISION) -> Callable[[str], object]:
    def github(path: str) -> object:
        asked.append(path)
        return {"object": {"type": "commit", "sha": sha}}

    return github


@pytest.fixture
def pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = _write(tmp_path, _valid())
    monkeypatch.setattr(pins, "PINS", path)
    yield path


def test_gateway_prints_the_image_by_digest_and_what_it_must_report(
        pinned: Path, capsys: pytest.CaptureFixture[str]) -> None:
    asked: list[str] = []
    assert pins.main(["gateway"], github=_github(asked)) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == [
        f"GATEWAY_IMAGE=ghcr.io/genesismeshlabs/genesis-mesh-gateway@{DIGEST}",
        "GATEWAY_VERSION=1.10.1",
        f"GATEWAY_REVISION={REVISION}",
        "GATEWAY_IDENTITY=https://github.com/GenesisMeshLabs/gateway/.github/workflows/distribution.yml"
        "@refs/tags/v1.10.1",
    ]
    # Only the gateway's tag is resolved, in the gateway repository.
    assert asked == ["/repos/GenesisMeshLabs/gateway/git/ref/tags/v1.10.1"]
    assert f"gateway: v1.10.1 is {REVISION}" in err


def test_an_unresolvable_gateway_tag_prints_no_line_at_all(pinned: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import urllib.error

    def github(path: str) -> object:
        raise urllib.error.HTTPError(path, 404, "Not Found", None, None)  # type: ignore[arg-type]

    assert pins.main(["gateway"], github=github) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "gateway: tag v1.10.1 not found on GitHub" in err


def test_env_does_not_print_or_resolve_the_gateway(pinned: Path, capsys: pytest.CaptureFixture[str]) -> None:
    asked: list[str] = []
    assert pins.main(["env"], github=_github(asked)) == 0
    assert "GATEWAY" not in capsys.readouterr().out
    assert len(asked) == len(pins.CONSUMERS) and not any("/gateway/" in path for path in asked)


def test_check_names_the_gateway_pin_offline(pinned: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def offline(path: str) -> object:
        raise AssertionError("check must not call GitHub")

    assert pins.main(["check"], github=offline) == 0
    assert f"gateway v1.10.1 ({DIGEST})" in capsys.readouterr().out


# -- the workflows ------------------------------------------------------------

def _job(workflow: str, name: str) -> str:
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", text)
    assert match
    return match.group(1)


@pytest.mark.parametrize(("workflow", "job"), [("ci.yml", "container"), ("publish-image.yml", "image")])
def test_the_container_jobs_verify_and_pull_the_pinned_gateway_image(workflow: str, job: str) -> None:
    text = _job(workflow, job)
    read = text.index('python scripts/consumer_pins.py gateway | tee -a "$GITHUB_ENV"')
    step = text[text.rindex("- name:", 0, read):read]
    assert "set -euo pipefail" in step and "GITHUB_TOKEN: ${{ github.token }}" in step
    # The signature is checked against the pinned tag's identity before the image is pulled.
    verify = text.index('cosign verify "$GATEWAY_IMAGE" --certificate-identity "$GATEWAY_IDENTITY"')
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in text[verify:verify + 300]
    pull = text.index('docker pull "$GATEWAY_IMAGE"')
    smoke = text.index("python scripts/container_smoke.py")
    assert read < verify < pull < smoke
    run = text[smoke:text.index("\n\n", smoke) if "\n\n" in text[smoke:] else len(text)]
    for option in ('--gateway-image "$GATEWAY_IMAGE"', '--gateway-version "$GATEWAY_VERSION"',
                   '--gateway-revision "$GATEWAY_REVISION"'):
        assert option in run
    # No gateway built from a checkout: not a branch named like this one, not main, not a tag of the core's version.
    for gone in ("repository: GenesisMeshLabs/gateway", "gateway-src", "GATEWAY_REF", "ls-remote", "head_ref",
                 "genesis-mesh-gateway:ci", "genesis-mesh-gateway:harness"):
        assert gone not in text


def test_published_artifacts_still_checks_the_released_gateway_version() -> None:
    # --version no longer applies to the gateway image: the released set names it explicitly.
    text = _job("published-artifacts.yml", "images")
    smoke = text[text.index("python scripts/container_smoke.py"):]
    assert '--gateway-version "$VERSION_UNDER_TEST"' in smoke.split("\n\n")[0]


# -- the harness --------------------------------------------------------------

@pytest.fixture
def smoke() -> Iterator[object]:
    spec = importlib.util.spec_from_file_location("container_smoke", REPO_ROOT / "scripts" / "container_smoke.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["container_smoke"] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("container_smoke", None)


def _docker(smoke: object, version: str = "1.10.1", revision: str = REVISION,
            binary: str | None = None) -> Callable[..., SimpleNamespace]:
    uid = smoke.UID  # type: ignore[attr-defined]
    config = {"User": f"{uid}:{uid}", "ExposedPorts": {"8080/tcp": {}}, "Healthcheck": {"Test": ["x"]},
              "WorkingDir": "/var/lib/gateway",
              "Labels": {"org.opencontainers.image.source": "https://github.com/GenesisMeshLabs/gateway",
                         "org.opencontainers.image.version": version,
                         "org.opencontainers.image.revision": revision,
                         "org.opencontainers.image.licenses": "Apache-2.0",
                         "org.opencontainers.image.description": "gateway"}}

    def docker(*args: str, check: bool = True, timeout: float = 0, **_: object) -> SimpleNamespace:
        if args[:2] == ("image", "inspect"):
            return SimpleNamespace(stdout=json.dumps(config), stderr="", returncode=0)
        if args[-1] == "--version":
            return SimpleNamespace(stdout=binary or f"genesis-mesh-gateway {version}\n", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="gateway requires GATEWAY_POLICY_FILE", returncode=1)

    return docker


def _context(smoke: object, **kwargs: object) -> object:
    image = f"ghcr.io/genesismeshlabs/genesis-mesh-gateway@{DIGEST}"
    return smoke.Context(image="genesis-mesh:ci", gateway_image=image, **kwargs)  # type: ignore[attr-defined]


def test_gw_metadata_passes_for_the_pinned_release(smoke: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke, "docker", _docker(smoke))
    detail = smoke.gw_metadata(_context(smoke, version="1.11.0", gateway_version="1.10.1",  # type: ignore[attr-defined]
                                        gateway_revision=REVISION))
    # The core's own --version is not the gateway's: a 1.11.0 core runs with the 1.10.1 gateway.
    assert "binary version = 1.10.1" in detail


@pytest.mark.parametrize(("docker_kwargs", "expected", "message"), [
    ({"version": "1.10.0"}, {"gateway_version": "1.10.1"}, "gateway version label '1.10.0', expected '1.10.1'"),
    ({"revision": "0" * 40}, {"gateway_version": "1.10.1", "gateway_revision": REVISION}, "gateway revision label"),
    ({"binary": "genesis-mesh-gateway 1.9.0"}, {"gateway_version": "1.10.1"}, "gateway binary reports"),
])
def test_gw_metadata_refuses_an_image_that_is_not_the_pinned_release(
        smoke: object, monkeypatch: pytest.MonkeyPatch, docker_kwargs: dict[str, str],
        expected: dict[str, str], message: str) -> None:
    monkeypatch.setattr(smoke, "docker", _docker(smoke, **docker_kwargs))
    with pytest.raises(smoke.Failed, match=re.escape(message)):  # type: ignore[attr-defined]
        smoke.gw_metadata(_context(smoke, version=None, **expected))  # type: ignore[attr-defined]


def test_the_gateway_expectations_need_a_gateway_image(smoke: object, monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    def no_docker(*args: object, **kwargs: object) -> object:
        raise AssertionError("argument errors come before Docker")

    monkeypatch.setattr(smoke, "docker", no_docker)
    for option in ("--gateway-version", "--gateway-revision"):
        monkeypatch.setattr(sys, "argv", ["container_smoke.py", "--image", "na:x", option, "1.10.1"])
        with pytest.raises(SystemExit) as exit_info:
            smoke.main()  # type: ignore[attr-defined]
        assert exit_info.value.code == 2
        assert "need --gateway-image" in capsys.readouterr().err
