Status: accepted design for Phase C of `ops/plan-architecture.md` (2026-10-16). Implementation is in progress; the Maintainer's decisions are at the end (no bot for now; core 1.7.1 is the first bundle).

# Phase C implementation contract: versioned contract bundle and the new release model

Status: design only. Nothing in any repository was changed. Everything below is checked against `main` of all six repos as of 2026-10-16. Core is at `da0f22d`: Phase A is merged, and Phase B (`chore/ratchets`, `docs/architecture`) is not. Sandbox `main` is `865584c`; the live smoke work is still on the unmerged branch `test/live-smoke-1.4`.

## 0. Decisions this contract takes

1. **A bundle is a set of files from the core repository, listed with hashes in a committed `contract/MANIFEST.json`.**
   - A release tarball of that set is attached to every core GitHub release.
   - Bundle paths are the core repo paths, so the same tool can read a release tarball, a core commit, or a local checkout.
   - `bundle_version` equals the core version. A `contract_digest` identifies the content, so patch releases with an identical contract are visibly the same.
2. **There is one stdlib-only tool, `scripts/gm_contract.py`.** Its source of truth is the core. It ships inside the bundle, and consumers vendor it byte for byte; CI checks the vendored copy's hash against the pinned bundle.
3. **Every consumer pins its bundle in `contract-bundle/bundle.lock`.**
   - On consumer `main` the pin may be a core release or a commit on core `main`.
   - A consumer release must pin a released bundle.
   - Every "live" CI job checks out the core at the pinned commit. Nothing a consumer requires reads core `main` any more.
4. **Running the vectors fails closed through receipts.**
   - Each conformance runner writes a receipt saying which vectors of which kinds it ran.
   - `gm_contract.py` checks the receipts against the tier requirements in the manifest.
   - A missing suite, a skipped required kind, or a vector the runner never selected fails the check.
5. **The core is decoupled the same way.** The core no longer reads consumer branches. Interop and the container job use consumer tags pinned in `contract/consumer-pins.json`, bumped by pull request.
6. **The version rule is checked locally, with no call to the core.**
   - A component's `major.minor` must be ≤ the `major.minor` of the released bundle it pins. Since the bundle is a core release, that keeps it ≤ the core.
   - Patch numbers are independent.
   - A release with nothing in it is refused.
   - A component with its own major (the Go and .NET 2.0s) declares a `supports` range instead.
7. **The Rust verifier and edge agent get their own tag streams:** `genesis-mesh-verify-vX.Y.Z` and `genesis-mesh-edge-vX.Y.Z`. These prefixes deliberately do not start with `v`. Today's `tags: ["v*"]` filters and the `refs/tags/v*` ruleset would otherwise match `verify-...`.
8. **Early warning moves into scheduled jobs that are never required checks:** a nightly canary per consumer against core `main`, and a nightly compatibility table in the core.

---

## Part A: shared specification (every agent reads this)

### A1. Bundle contents (v1)

| Bundle path (= core repo path) | Role | Notes |
|---|---|---|
| `conformance/vectors/*.json` (18 suites) | suite | Exact bytes as committed |
| `conformance/fixtures/audit-pack-1.5.0/**` | fixture | The frozen pack Rust and published-artifacts use |
| `contract/public-surface.json` | contract | Routes, levels and `error_codes` (334 today) |
| `contract/kinds.json` | contract | **New**: per-kind metadata (A3) |
| `scripts/gm_contract.py` | tool | **New**: the shared tool (A5) |
| `contract/MANIFEST.json` | manifest | **New**: generated, committed |
| `contract/routes.json` | contract | Reserved for Phase D; `null` in v1 |

Deliberately not in v1:
- the verification corpus (`scripts/export_reference_corpus.py` output; Rust runs it from the pinned core commit);
- SDK-owned generated fixtures (`sdk-typescript/tests/fixtures/python-vectors.json`, `sdk-rust/tests/fixtures/{anchors.json,python_*.json}`, `gateway/tests/reference/python-evidence-vectors.json`).

### A2. Core source files

**`contract/bundle.json`** is hand-edited and is a flagged path. It says what goes in the bundle and who must run what.

```json
{
  "schema": "gm.contract.spec/1",
  "include": ["conformance/vectors/*.json", "conformance/fixtures/audit-pack-1.5.0/**",
              "contract/public-surface.json", "contract/kinds.json", "scripts/gm_contract.py"],
  "tiers": {
    "verifier": "Offline verifier plus thin client (decision 0002): sdk-go",
    "governed": "Governed client: sdk-typescript, sdk-rust, sdk-dotnet (decision 0008, in progress)",
    "edge": "Edge agent: sdk-rust genesis-mesh-edge",
    "gateway": "Trust gateway console: gateway"
  },
  "suites": {
    "admin_auth":     {"required": {"verifier": "all", "governed": "all", "gateway": "all"}},
    "canonical":      {"required": {"verifier": "all", "governed": "all"}},
    "field_registry": {"required": {"verifier": ["unknown_fields", "verify_decision", "verify_agreement"], "governed": "all"}},
    "interop":        {"required": {"verifier": "all"}},
    "consensus":      {"required": {"verifier": "all"}},
    "audit":          {"required": {"verifier": ["canonical_form", "key_history", "key_at", "decision_at_record_time", "record_time"], "governed": "all"}},
    "grants":         {"na_only_kinds": ["issuance"], "required": {"verifier": ["canonical_form", "verify_record"], "governed": "all"}},
    "out_of_band":    {"na_only_kinds": ["time_bounds", "policy_history"], "required": {"governed": "all"}},
    "remediation":    {"required": {"governed": "all"}},
    "node":           {"required": {"edge": "all"}},
    "signatures": {"required": {}}, "treaties": {"required": {}}, "attestations": {"required": {}},
    "revocation": {"required": {}}, "ibct": {"required": {}}, "trust_evidence": {"required": {}},
    "selective_disclosure": {"required": {}}, "data_usage": {"required": {}}
  }
}
```

These requirements equal what the SDKs run today:
- Go and .NET do not run `audit`'s pack/export kinds, `grants`' envelope/use/export kinds, or `field_registry`'s `entry_kind`/`export` (`sdk-go/genesismesh/strict_test.go:190`, `FieldRegistryConformanceTests.cs:139`).
- TS and Rust run everything except the NA-only `out_of_band` kinds (`tests/out-of-band.test.ts:24-28`, `tests/out_of_band.rs:43`) and `grants`' `issuance`.

Rules:
- `"all"` means every kind in the file except `na_only_kinds`. So a new kind in an `"all"` suite becomes required automatically, while a new kind in a listed suite is opt-in.
- A suite file with no entry fails the build. Every new suite therefore forces a tier decision.
- A listed kind that is not in the file also fails.
- `grants.json`'s own `na_only_kinds` must equal the spec's.
- A vector with no `kind` counts under `"*"`.

**`contract/kinds.json`** is generated. Build it with `genesis_mesh/trust/kinds.py::kind_registry()`. It must live in `trust`, not `models`: the Phase B layer table (`origin/chore/ratchets:genesis_mesh/tests/test_architecture.py`) lets `trust` import `models` but not the reverse. Its sources are the existing tables:
- `_PAYLOAD_MODELS`, `_RECORD_ID`, `_KEY_SIGNED_KINDS`, `_ENVELOPE_FIELDS` and `CARRIED_KINDS` in `genesis_mesh/trust/evidence_store.py:125,514-603`;
- `NA_RECORD_TIME_FIELDS` in `genesis_mesh/models/key_succession.py:67`;
- a new small `_SINCE` table.

```json
{"schema": "gm.contract.kinds/1",
 "kinds": {
   "grant_execution": {"since": "1.6.0", "model": "GrantExecutionEvidence", "payload_path": [],
                       "id_field": "use_id", "signer": "registered_key", "time_field": null,
                       "envelope": {"record_id": "use_id", "subject_id": "grant_id", "...": "..."},
                       "carried_by_retention": false},
   "decision": {"model": "BoundaryDecision", "payload_path": ["decision"], "...": "..."}}}
```

- `signer` is one of `na`, `registered_key`, or `root_and_outgoing_na_key` (key_succession).
- `time_field` is `NA_RECORD_TIME_FIELDS[model]` for NA-signed kinds and `null` otherwise.
- A test asserts that the key set equals `typing.get_args(EntryKind)`, so a new kind without metadata fails.

**`contract/MANIFEST.json`** is generated and committed:

```json
{
  "schema": "gm.contract.manifest/1",
  "bundle_version": "1.7.1", "core_version": "1.7.1",
  "contract_digest": "sha256:<hex>",
  "tiers": {"verifier": "...", "governed": "...", "edge": "...", "gateway": "..."},
  "files": {"conformance/vectors/audit.json": {"sha256": "<hex>", "bytes": 1060810}, "...": {}},
  "suites": {
    "audit": {"file": "conformance/vectors/audit.json", "suite_version": "1.5.0", "vectors": 108,
              "kinds": {"canonical_form": 3, "key_history": 19, "...": 0}, "na_only_kinds": [],
              "required": {"verifier": ["canonical_form", "key_history", "key_at", "decision_at_record_time", "record_time"],
                           "governed": ["...every non-NA-only kind, expanded..."]}}
  },
  "fixtures": {"audit-pack-1.5.0": {"dir": "conformance/fixtures/audit-pack-1.5.0/"}},
  "contract": {"public_surface": "contract/public-surface.json", "error_codes": "/error_codes",
               "kinds": "contract/kinds.json", "routes": null},
  "format_level": null,
  "tool": {"path": "scripts/gm_contract.py", "sha256": "<hex>"}
}
```

- `contract_digest` is the sha256 of the canonical JSON (sort_keys, `(",", ":")`) of the manifest with `bundle_version`, `core_version`, `contract_digest` and `tool` removed.
- `format_level` is reserved for decision 0004.
- `core_version` comes from `VERSION`, so the release PR must regenerate the manifest; the check catches a stale one.

### A3. Build, check and publish (core)

- **Regenerate.** `python conformance/generate_vectors.py [suite...]` keeps its behaviour. At the end it also writes `contract/kinds.json` and runs `python scripts/gm_contract.py manifest`. Running it with a subset of suites refreshes both as well.
- **Check (CI).** The new core job `contract-bundle`, named **"Contract bundle"**, in `ci.yml` runs:
  - `python scripts/gm_contract.py manifest --check`: fails on a stale manifest, a suite without a tier entry, unknown kinds, or a non-stdlib import in the tool.
  - `pytest genesis_mesh/tests/test_contract_bundle.py`: kinds.json equals `kind_registry()`, EntryKind coverage, the archive builds identically twice, and tool round-trips.
- **Archive.** `python scripts/gm_contract.py archive --out DIR` writes:
  - `genesis-mesh-contract-X.Y.Z.tar.gz`, with top directory `genesis-mesh-contract-X.Y.Z/`, MANIFEST.json, and files at their core paths. Entries are sorted, uid/gid 0, empty uname, mode 0644/0755, mtime = `SOURCE_DATE_EPOCH` (the commit time), and gzip mtime 0.
  - `SHA256SUMS-contract`.
- **Publish.** A new workflow, `.github/workflows/contract-bundle.yml`:
  - Triggers: `on: release: types: [published]` (the same event as `publish-pypi.yml:3-5`), plus `workflow_dispatch` that must be run on the tag ref.
  - It builds the archive, signs it with cosign (`sign-blob`, giving `.sigstore.json` for both files), uploads the assets to the existing release, then downloads them anonymously and re-verifies the hashes and signatures.
  - It must **not** create the release. A release created with `GITHUB_TOKEN` would not trigger PyPI.
  - Identity: `https://github.com/GenesisMeshLabs/genesismesh/.github/workflows/contract-bundle.yml@refs/tags/vX.Y.Z`.
  - On push to `main` it builds and uploads the archive as a workflow artifact only, for inspection.

Release asset URL: `https://github.com/GenesisMeshLabs/genesismesh/releases/download/vX.Y.Z/genesis-mesh-contract-X.Y.Z.tar.gz`. Core releases are not immutable (`immutable: false`), so uploading after publication works.

### A4. Consumer files

| Path in the consumer | Edited by | Purpose |
|---|---|---|
| `contract-bundle/consumer.json` | hand (flagged) | Tiers, file mapping, regenerate and conformance commands, streams, version policy |
| `contract-bundle/bundle.lock` | tool | The pin |
| `contract-bundle/MANIFEST.json` | tool | Exact bytes of the pinned manifest, so checks work offline |
| `scripts/gm_contract.py` (gateway: `tools/gm_contract.py`) | tool | The vendored tool |

Mark every mapped destination, the lock and the manifest `-text linguist-generated=true` in `.gitattributes`. Byte-exactness on Windows checkouts depends on it.

```json
{
  "schema": "gm.contract.consumer/1",
  "component": "sdk-rust",
  "tiers": ["governed", "edge"],
  "tool_path": "scripts/gm_contract.py",
  "files": {
    "conformance/vectors/admin_auth.json": "tests/fixtures/admin_auth.json",
    "conformance/fixtures/audit-pack-1.5.0/": "tests/fixtures/audit-pack-1.5.0/"
  },
  "regenerate": [["python3", "scripts/sync_canonical_registry.py"]],
  "conformance": [["cargo", "test", "--locked", "--workspace", "--all-targets"]],
  "streams": {
    "sdk":      {"tag_prefix": "v", "version_from": "VERSION", "changelog_root": ".",
                 "release_branch": "release/", "paths": ["src/", "tests/", "Cargo.toml", "Cargo.lock"]},
    "verifier": {"tag_prefix": "genesis-mesh-verify-v", "version_from": "verifier/Cargo.toml#package.version",
                 "changelog_root": "verifier", "release_branch": "release/verify-", "paths": ["verifier/", "src/", "Cargo.lock"]},
    "edge":     {"tag_prefix": "genesis-mesh-edge-v", "version_from": "edge/Cargo.toml#package.version",
                 "changelog_root": "edge", "release_branch": "release/edge-", "paths": ["edge/", "src/", "Cargo.lock"]}
  },
  "version_policy": {"kind": "follow-core"}
}
```

- Single-stream repos have one stream, `"default"`.
- Own-major components use `{"kind": "own-major", "supports": ">=1.8.0,<2.0.0"}`.
- A directory mapping (trailing `/`) copies every manifest file under that prefix. Extra local files under the destination fail `verify`.

Lock:

```json
{
  "schema": "gm.contract.lock/1",
  "source": "release",
  "bundle_version": "1.7.1", "core_tag": "v1.7.1", "core_commit": "<40 hex>",
  "archive": {"name": "genesis-mesh-contract-1.7.1.tar.gz", "sha256": "<hex>"},
  "manifest_sha256": "<hex>", "contract_digest": "sha256:<hex>",
  "files": {"tests/fixtures/audit.json": {"from": "conformance/vectors/audit.json", "sha256": "<hex>"}},
  "tool_sha256": "<hex>"
}
```

- `source` is one of `release`, `commit` or `path`.
- For a `commit` pin, `core_tag` and `archive` are `null`, and the tool shows the version as `1.7.1+g<sha12>`.
- A `path` lock is never valid in CI.

### A5. `gm_contract.py` CLI

Python 3.11 or newer, stdlib only. Exit codes: 0 ok, 1 check failed, 2 usage error.

| Command | Does |
|---|---|
| `sync (--version X.Y.Z \| --latest \| --core-ref <40-hex> \| --core-path DIR \| --from-archive FILE) [--no-lock] [--verify-signature] [--repo DIR]` | Fetches the bundle and verifies every file against the manifest; for a release also the archive against `SHA256SUMS-contract`, and the signature when `cosign` is on PATH and `--verify-signature` is set. Writes the mapped copies, runs `regenerate`, refreshes the vendored tool, the manifest copy and the lock. Release archives are read with `tarfile` `filter="data"`; only listed paths are accepted. Commit pins fetch `raw.githubusercontent.com/GenesisMeshLabs/genesismesh/<sha>/<path>`. Cache: `$GM_CONTRACT_CACHE` (default `~/.cache/genesis-mesh/contract/`); `--offline` uses only the cache, an archive or a path. |
| `verify [--online]` | Offline: every copy matches the lock; lock equals the manifest copy; tool hash matches; every suite required by `tiers` is mapped; `source != "path"`. Online: a release's `SHA256SUMS-contract` lists the lock's archive hash; a commit's manifest at that sha hashes to `manifest_sha256` and the commit is an ancestor of core `main` (`GET /repos/.../compare/<sha>...main`, status `ahead` or `identical`). A token is sent only to `api.github.com`. |
| `conformance [--receipts DIR] [--json-out FILE] [--repo DIR] [--no-lock-check]` | Runs each `conformance` command with `GM_CONFORMANCE_RECEIPTS=<tmpdir>`, then `receipt-check`. |
| `receipt-check --receipts DIR` | See A6. |
| `release-check --stream S --version V [--tag T] [--release]` | See Part C1. |
| `core-ref` | Prints `lock.core_commit`, for workflows. |
| `latest [--json] [--if-newer]` | Newest released bundle, via GitHub releases with the asset present. |
| `fragment --write` | Writes `changelog.d/<next>/contract-bundle-<v>.md`; `<next>` is the stream version with patch+1. |
| `status [--json]` | Pin, source, and drift against the latest bundle. |
| `manifest [--check]`, `archive --out DIR` | Core-only; refuse to run outside a core checkout. |

### A6. Receipts (language-agnostic)

When `GM_CONFORMANCE_RECEIPTS` is set, every vector runner writes one file `<dir>/<suite>.<runner-slug>.json`. It writes after its vectors ran; for xUnit `[Theory]`, from the `[Fact]` that enumerates and asserts kinds. With the variable unset, nothing changes. One file per runner avoids concurrent appends from parallel test processes.

```json
{"schema": "gm.contract.receipt/1", "suite": "audit",
 "file": "genesismesh/testdata/conformance/audit.json",
 "runner": "genesismesh/key_history_test.go:TestConformanceAuditVectors",
 "run": {"canonical_form": 3, "key_history": 19, "key_at": 8, "decision_at_record_time": 2, "record_time": 17},
 "not_run": {"pack": 22, "verify_export": 13, "...": 0}}
```

`receipt-check` merges the files per suite, summing `run`, and fails when:
- `file` is not a lock destination of that suite, or its bytes differ from the lock;
- a suite required for any of the component's tiers has no receipt;
- for a required kind, `run[k]` is less than `manifest.kinds[k]`;
- `run[k] + not_run[k]` does not equal `manifest.kinds[k]` for any kind (a kind left unaccounted);
- a kind the receipt names is not in the manifest.

Suites that are not required may be receipted. They are byte-checked the same way and shown in the capability matrix.

---

## Part B: work packages per repository

### B1. genesismesh (core)

**C1 `feat(contract)`**, flagged:
- `scripts/gm_contract.py`, `contract/bundle.json`, `genesis_mesh/trust/kinds.py`, generated `contract/kinds.json` and `contract/MANIFEST.json`.
- The `generate_vectors.py` hook.
- `genesis_mesh/tests/test_contract_bundle.py`.
- The `ci.yml` job "Contract bundle".
- `.gitattributes`: both generated files `linguist-generated`.
- `test_canonical_registry.py:65`: change "copy it to the SDKs" to "regenerate; consumers pick it up by bumping their bundle pin".

**C2 `ci(contract)`:** `.github/workflows/contract-bundle.yml` (A3).

**C3 `ci: pin the consumers; release streams`**, flagged. This must merge before the core 1.7.1 release and before any Rust stream tag.
- **`contract/consumer-pins.json`**: `{"schema":"gm.consumer-pins/1","sdk-go":{"ref":"v1.7.0"},"sdk-typescript":{"ref":"v1.7.0"},"sdk-dotnet":{"ref":"v1.7.0"},"gateway":{"ref":"v1.7.0"}}`. A ref is a release tag or a commit on that repo's `main`.
- **`interop.yml`:**
  - delete "Choose the SDK revision" (`:28-44`), the Rust checkout, the "Conformance vectors are current" cmp step (`:99-127`, keeping `python conformance/runner.py`) and "Go verifier conformance";
  - check out each SDK at its pinned ref;
  - `run_all.sh` is unchanged.
- **`ci.yml` container job (`:81-119`):** the gateway at its pinned ref instead of the same-named branch.
- **`publish-image.yml:134-160`:** the gateway at its pinned ref.
- **`scripts/container_smoke.py`:** a new `--gateway-version`. The gateway label is compared with it, not `--version` (`:745-746`). Without it, only label equals binary is checked.
- **`contract/components.json`:** component id, repo, `tag_prefix`, tiers, package. The verify and edge streams carry `"legacy_tag_prefix": "v", "legacy_until": "1.7.0"`.
- **New `scripts/release_streams.py`:**
  - `latest <id> [--major N]`
  - `resolve --core V --format env`, which emits `GM_PUBLISHED_SDK_GO_VERSION`, `..._TS_...`, `..._DOTNET_...`, `GM_PUBLISHED_GATEWAY_VERSION`, `GM_PUBLISHED_VERIFY_TAG` and `GM_PUBLISHED_EDGE_TAG`
  - `compat-matrix --format json`
  - `audit-ceiling`
- **`scripts/check_release_train.py`:**
  - on PRs and publish it checks only that core `VERSION` is not behind a core `v*` tag;
  - the component ceiling audit moves to `release_streams.py audit-ceiling`, which runs nightly, never on PRs. A consumer's release can then never turn core CI red.
- **`published-artifacts.yml`:**
  - resolves the versions per component, with legacy fallback for the verifier and edge;
  - `interop/run_all.sh` reads the `GM_PUBLISHED_SDK_*_VERSION` overrides, defaulting to `--published`;
  - images: NA at core V, gateway at its own latest release, with identity `distribution.yml@refs/tags/v<gw>`; `image_tags.py` gains `--tags-from-remote GenesisMeshLabs/gateway` for the gateway's floating tags;
  - verifier and edge: download from `releases/download/<stream-tag>/`, with identity `verifier.yml|edge.yml@refs/tags/<stream-tag>`; the `--version` check uses the stream version; the edge image tag is the edge version.
- **`consumer-pins.yml`** (weekly and dispatch): opens a pin-bump PR when newer consumer releases exist; Interop re-runs on it.

**C4 `ci: compatibility table`:** `compatibility.yml`, nightly and dispatch, in a public repo so it costs nothing.
- **plan**: rows are each consumer's latest release and `main`; bundles are core `main` and the latest core release.
- **cell matrix** (max-parallel 6):
  - check out the consumer at the ref and the core at the bundle ref, and set up the toolchain for that consumer;
  - run `python core/scripts/gm_contract.py --repo consumer sync --core-path core --no-lock`, then `... conformance --no-lock-check --json-out`;
  - a release without `contract-bundle/consumer.json` gives `n/a (pre-bundle)`.
- **table**: `scripts/render_compatibility.py` writes:
  - `docs/reference/compatibility.json` (`{"schema":"gm.compatibility/1","bundles":{...},"rows":[{"component","version","pinned_bundle","tiers","results":{"<bundle>":{"status":"pass|fail|n/a|error","suites":{...}}}}]}`);
  - `docs/reference/compatibility.md`;
  - optionally `docs/reference/capabilities.md` (decision 0002), from the manifest `required` sets and the receipts' `run` kinds.
- If those change, a bot PR (docs only, auto-merge) updates them.
- A regression in the cell "latest release × latest bundle" opens or updates an issue.
- The job also runs `release_streams.py audit-ceiling`.

**C5 docs:**
- `docs/development/versioning.md` rewrite (C4 below);
- `conformance/CONFORMANCE.md` "Regenerating vectors" and a new "Contract bundle" section;
- `docs/development/interoperability.md:39` ("Each SDK keeps a copy");
- AGENTS.md/CONTRIBUTING recipe: "adding a suite or kind" (spec entry, regenerate, name the tiers affected in the PR).

### B2. Every consumer (TS, Rust, Go, .NET, gateway): common changes

1. **X1 `test: conformance receipts`.** This has no dependency and can start now. Add receipt writing to every runner of a mapped suite (A6), plus one helper per language under tests.
2. **X2 `ci(contract): pin the contract bundle`.**
   - Vendor the tool and add `contract-bundle/*`. Run `sync` from the C1 core commit, or `--version 1.7.1` once released.
   - **Expected copy diff: none.** Core vectors are unchanged since v1.7.0 (`git diff v1.7.0..main -- conformance contract` is empty).
   - **New job `contract-bundle`, named "Contract bundle"**, on `pull_request`, `merge_group` and `push`: set up the toolchain, then run `verify --online` and `conformance`.
   - **Every "Choose the core revision" step** becomes `echo "CORE_REF=$(python3 scripts/gm_contract.py core-ref)" >> "$GITHUB_ENV"`. That covers tag builds too: a tag is tested against its pinned release.
   - **`release-train` job** (keep the id and name; it is a required check). It replaces the curl of core `VERSION` (for example `sdk-go/.github/workflows/ci.yml` release-train) with:
     ```
     python3 scripts/gm_contract.py release-check --stream default --version "$(cat VERSION)" \
       ${IS_RELEASE:+--release}
     ```
     `IS_RELEASE` is set when the head ref starts with a release branch prefix, or on a tag; pass it via `env`. Use `fetch-depth: 0`.
   - **Publish gates** (`publish.yml` / `distribution.yml` "Verify release train"): `release-check --release --tag "$GITHUB_REF_NAME"`. Delete the core-tag `ls-remote` checks.
   - **New `canary.yml`** (nightly and dispatch; never on PRs; never required), job "Against core main":
     - check out core `main` and run `sync --core-path core --no-lock`, then `conformance --no-lock-check`;
     - run the repo's live e2e against `pip install -e ./core`;
     - on failure, open or update the issue "Canary: core main breaks <repo>".
   - **New `contract-pin.yml`** (daily, dispatch, and `repository_dispatch: contract-bundle-published`):
     - run `latest --if-newer`, then `sync --version V --verify-signature` and `fragment --write`;
     - branch `bot/contract-bundle-<V>`, PR titled "chore(contract): pin contract bundle V", auto-merge;
     - it acts only when `contract_digest` changed or `major.minor` rose;
     - it needs the bot token (Q1). Without it, it opens an issue instead.
   - **Docs:** CONTRIBUTING/AGENT(S).md "Contract bundle" (sync, local `--core-path ../genesismesh`, commit pins, receipts) and "Releasing" (C3).
3. **Optional in C, required in D:** a contract test that the SDK's routes and error-code literals are in the bundle's `public-surface.json`.

### B3. Consumer specifics

| Repo | Tiers | `files` (source → destination) | `regenerate` | `conformance` | CI renames |
|---|---|---|---|---|---|
| sdk-typescript | governed | `conformance/vectors/{admin_auth,audit,canonical,consensus,field_registry,grants,interop,out_of_band,remediation}.json` → `tests/fixtures/conformance/<same>`; `contract/kinds.json` → `tests/fixtures/conformance/kinds.json` | `["node","scripts/sync-canonical-registry.mjs"]` | `["npm","test","--","--ci"]` (after `npm ci`) | `sdk-e2e` "SDK against core main" → **"SDK against core"** |
| sdk-rust | governed, edge | `.../{admin_auth,audit,canonical,field_registry,grants,node,out_of_band,remediation}.json` → `tests/fixtures/<same>`; `conformance/fixtures/audit-pack-1.5.0/` → `tests/fixtures/audit-pack-1.5.0/`; kinds.json → `tests/fixtures/kinds.json` | `["python3","scripts/sync_canonical_registry.py"]` | `["cargo","test","--locked","--workspace","--all-targets"]` | same rename. In `sdk-e2e`, delete "The signing vectors are the core's" (`ci.yml:118-130`) and "The frozen audit pack is the core's" (`:139-144`); the corpus step stays, against the pinned core |
| sdk-go | verifier | `.../{admin_auth,audit,canonical,consensus,field_registry,grants,interop}.json` → `genesismesh/testdata/conformance/<same>` | `["python3","scripts/sync_canonical_registry.py"]` | `["go","test","-count=1","./genesismesh"]` | "Live contract" unchanged |
| sdk-dotnet | verifier | same 7 → `tests/GenesisMesh.Sdk.Tests/testdata/conformance/<same>` | `["python3","scripts/sync_canonical_registry.py"]` | `["dotnet","test","tests/GenesisMesh.Sdk.Tests","-c","Release"]` | "Live contract" unchanged |
| gateway | gateway | `conformance/vectors/admin_auth.json` → `tests/reference/admin_auth.json`; `contract/public-surface.json` → `tests/reference/public-surface.json` | none | `[["cargo","test","--locked","admin_auth"],["node","tools/test_ui_signing.mjs"]]`; `tool_path` = `tools/gm_contract.py` | "Authority catalog and signing vectors match the core" keeps its name; it runs `build_service_catalog.py --core core --check` at the pinned core and drops the cmp. The NA image in "Network Authority end-to-end" is built from the pinned core. The canary also runs the catalog drift check against core `main`. |

Per-repo notes:
- **TS:** the new kind-table test asserts that the verifier's kind tables equal `kinds.json` (model, id field, envelope map). TS has these tables (`src/canonical-registry.ts` `ENTRY_KINDS`).
- **Rust:** same kind-table test. The synthesis says the duplicated signer-role tables "already disagree".
- **Go and .NET:** today's "not run" lists (`grants_test.go:30`, `key_history_test.go:32`, `GrantsTests.cs:22`, `KeyHistoryTests.cs:27`) become the receipts' `not_run`. The `entry_kind`/`export` cases in the registry tests (silently passing today) must be reported as `not_run`.
- **Gateway:** no changelog exists, so its release-check relies on the path diff for "no empty releases". Adopting `changelog.d` and `scripts/changelog.py` is recommended in the same PR.
- **.NET:** `sdk-dotnet/sandbox/sdk-smoke-dotnet` duplicates the sandbox app; delete it and point to the sandbox.

### B4. sdk-rust tag streams (X3)

This can merge after C3. No stream tag may be pushed before C3 is merged and the tag ruleset is updated.
- **`verifier/Cargo.toml` and `edge/Cargo.toml`** own their versions. `scripts/check_release.py` gets `--stream sdk|verifier|edge`:
  - each stream checks its own manifest and `Cargo.lock` agree, and that the tag equals prefix plus version;
  - the core-tag check is removed and delegated to `gm_contract.py release-check --stream ...`.
- **`verifier.yml` and `edge.yml`:**
  - `on.push.tags: ["genesis-mesh-verify-v*"]` and `["genesis-mesh-edge-v*"]` respectively;
  - each creates **its own** GitHub release titled "genesis-mesh-verify X.Y.Z" / "genesis-mesh-edge X.Y.Z", with notes from `verifier/CHANGELOG.md` / `edge/CHANGELOG.md`;
  - asset names are unchanged (`genesis-mesh-verify-$V-$TARGET`, `SHA256SUMS`, `SHA256SUMS-edge`, systemd unit, example config); edge image `ghcr.io/genesismeshlabs/genesis-mesh-edge:$V` (beta, version tag only).
- **`ci.yml`:** `github-release` no longer coordinates with the verifier workflow; `tags: ["v*"]` builds only the crate.
- **Changelogs:** `verifier/changelog.d/<version>/`, `edge/changelog.d/<version>/`, and `scripts/changelog.py --root verifier|edge`. Release branches are `release/verify-<v>` and `release/edge-<v>`.
- **`edge-soak-release.yml`:** runs on any `release/edge-*` PR against the pinned core, not the same-named branch.
- **`RELEASING.md`:** one section per stream (C3).
- **Ruleset (Maintainer):** add `refs/tags/genesis-mesh-verify-v*` and `refs/tags/genesis-mesh-edge-v*` to "release tags are immutable"; today it includes only `refs/tags/v*`.
- **First stream releases:** the next change to each, numbered 1.7.1 or 1.8.0 under the ceiling. Releases up to 1.7.0 stay on `v1.7.0`, and `components.json` records that.

---

## Part C: the release model

### C1. `release-check` semantics (one rule everywhere)

1. Read the stream's version from `version_from`. The lock and the manifest copy must be consistent.
2. With `--release`:
   - `lock.source` must be `release` ("a release pins a released bundle: `gm_contract.py sync --latest`");
   - the stream's changelog section for V exists and is non-empty (gateway: skipped);
   - `git diff --name-only <previous stream tag>..HEAD -- <paths>`, minus the version file, changelog files and fragment directories, must not be empty ("nothing changed since <tag>: no empty releases").
3. Ceiling:
   - `follow-core`: `major(V) == major(lock.bundle)` and `minor(V) <= minor(lock.bundle)`.
   - `own-major`: `lock.bundle_version` must lie within `supports`; there is no ceiling, and the nightly table checks the range.
4. With `--tag`, it must equal `tag_prefix + V`.

Steps 1-4 are local; `--release --tag` also runs `verify --online`, which reads only immutable core release assets. No step reads core `main`.

What the release-train jobs check instead of "VERSION ≤ core main VERSION":
- On PRs: the pin is coherent and the ceiling holds against the pinned bundle.
- On release PRs and tags: also a released pin and a non-empty release.

The core keeps only its own monotonic-version check. The cross-component ceiling is audited nightly by C4.

### C2. How a contract change flows

1. **Core PR.** Change the generator, then run `python conformance/generate_vectors.py`. Suites, kinds.json and MANIFEST change together. "Contract bundle" fails if anything is stale or untiered. It is a flagged PR, and the description names any newly required kinds per tier. Core CI touches no consumer.
2. **Same night.** Consumer canaries go red and file issues. That is the early warning, and no `main` is red.
3. **Before a core release** (optional). A consumer branch pins the core commit with `sync --core-ref <sha>`, implements, and may merge to its `main` with a commit pin. It cannot release yet.
4. **Core release vX.Y.0.** `contract-bundle.yml` attaches the bundle, and each consumer's `contract-pin.yml` opens a bump PR.
   - If the consumer already supports the change, the PR is green and merges.
   - If not, the PR stays red until implemented; the consumer's `main` stays green on the old pin.
5. **Consumer release** whenever it has something to ship, pinned to the released bundle. The nightly table updates, and core `consumer-pins.yml` picks up the new tag for Interop.
6. **Core Interop scenario extensions** that need new SDK behaviour land after that SDK release, as part of the pin bump.

Local development: `python3 scripts/gm_contract.py sync --core-path ../genesismesh`. The devtools sibling layout (`devtools/repos.json`) makes that the default. The resulting `path` lock fails `verify` in CI, so it cannot be merged by accident.

### C3. Documentation changes

**`docs/development/versioning.md`** is rewritten. It keeps the v0.57 and 1.0 history.
1. Components, tag patterns and packages: a table generated from `contract/components.json`.
2. The contract bundle: what it is, its version (the core version), `contract_digest`, where it is published, and how it is pinned.
3. The version rule: same major → `major.minor` ≤ the pinned released bundle; patches are independent; no empty releases; own major → a `supports` range, checked by the table.
4. Tag streams, including Rust verify and edge (up to 1.7.0, on the SDK's `v` tags).
5. The flow of a contract change (C2), and development before a core release.
6. Gates: core "Contract bundle"; consumer "Contract bundle" and `release-train`; published-artifacts; compatibility nightly; canaries.
7. Changelogs: fragments, plus per-stream roots for Rust.
8. Images: the NA and gateway images carry their own versions and floating tags.
9. Release integrity: rewritten. Drop "all component VERSION files must match". Each component's release is tested against its pinned core release.

Per repo:
- **sdk-rust `RELEASING.md`:** three stream checklists. Steps 1 and 6 lose "update verifier/edge Cargo.toml to the crate's version" and "only once the core release v<VERSION> is tagged". They gain "`gm_contract.py release-check --release`".
- **TS, Go and .NET** (Releasing sections in CONTRIBUTING.md/AGENT.md; no RELEASING.md exists):
  - release when something changed;
  - pin the latest bundle first;
  - pick patch or minor under the ceiling;
  - no waiting for a core tag.
- **gateway** (`CONTRIBUTING.md`, `docs/distribution.md`): the same, plus "a CVE patch ships as X.Y.Z+1 without a core release".
- **core:** release checklist step "after the GitHub release is published, check the four `genesis-mesh-contract-*` assets".

---

## Part D: nightly live smoke in the sandbox (private; minutes cost money)

**S0.** Merge `test/live-smoke-1.4` (6 commits: `live.ts`, `live-local.ts`, public-reference mode) to `main` first. Nothing below works without it.

**S1 `ci: nightly live smoke; repair the Go and .NET smoke apps`.**

- **Move `tests/sdk-smoke-typescript/na.py` to `tests/common/na.py`.** Update the path in `src/harness.ts` (one line).
- **Go app** (`tests/sdk-smoke-go`):
  - `go.mod`: drop `replace ... => ../../sdk-go`, which points to a path that does not exist; require `github.com/GenesisMeshLabs/sdk-go v1.7.0`;
  - `smoke.go`: read `GM_SMOKE_NA_JSON`, the `na.py` connection line (`baseUrl`, `operatorSeed`, `operatorKeyId`, `naPublicKey`), instead of the hard-coded `127.0.0.1:9443` and `001-na` key and genesis files; keep those as a local fallback;
  - local runs against a checkout use an untracked `go.work`, so `go.work` is ignored.
- **.NET app:**
  - csproj: `TargetFramework` `net10.0` (.NET 8 support ends 2026-11-10);
  - `<PackageReference Include="genesismesh-sdk-dotnet" Version="$(GmSdkDotnetVersion)" Condition="'$(GmSdkProject)'==''"/>`, with default `GmSdkDotnetVersion=1.7.0` (up from 0.55.0);
  - `<ProjectReference Include="$(GmSdkProject)" Condition="'$(GmSdkProject)'!=''"/>`;
  - same environment input as Go.
- **Drop `sdk-smoke-python`** (legacy) from the nightly.
- **`.github/workflows/nightly-smoke.yml`:**
  - `schedule: "41 2 * * *"`, plus `workflow_dispatch` with `force`;
  - `permissions: {contents: read, issues: write}`; `concurrency: nightly-smoke`;
  - Linux only. Checkouts mirror the local sibling layout under `$GITHUB_WORKSPACE`; all repos are public, so no token is needed.

| Job | Steps | Est. minutes |
|---|---|---|
| **"Released stack"** | 1. Fingerprint (core latest tag, npm/Go proxy/NuGet latest, sandbox sha); `actions/cache/restore` `lookup-only` key `green-released-<fp>`. On a hit, skip steps 2-4 unless `force` is set or it is Sunday. 2. Core at the latest tag, `pip install -e`; `GM_SDK_VERSION=<npm latest> npm run sdk:pack`; `GM_SMOKE_HA=0 npm run smoke`; `npm run live:local`. 3. Go: `go get .../sdk-go@latest`; start `na.py`; `go run .`. .NET: `dotnet run -p:GmSdkDotnetVersion=<NuGet flat-container latest stable>`. 4. **Always**: the public reference, `GM_LIVE_PUBLIC_EVIDENCE_URL=${{ vars.GM_PUBLIC_EVIDENCE_URL }} npm run live` with no `GM_LIVE_URL`; the default is the Azure public reference (`https://na.genesismesh.org/evidence.json` per `tests/sdk-smoke-typescript/README.md:53`). 5. On success, `actions/cache/save` the key. On failure, open or update the issue "Nightly smoke: released stack failing" (label `nightly-smoke`, run link). Close it with a comment on the next pass. | ~9 (~2 when skipped) |
| **"Main stack"** | The same fingerprint and skip logic on core, sdk-typescript, sdk-go and sdk-dotnet `main` shas. Core `main`; `npm run all` with `GM_SDK_DIR` pointing at the checkout; HA on (postgres service with C collation, nginx from apt); `live:local`; Go with `go mod edit -replace` to the checkout; .NET with `-p:GmSdkProject=...`. Its own issue. | ~12 |

- Budget: about 21 min per night when everything changed, about 600 to 650 min/month in the worst case. That is within the 2,000-minute private allowance of a Free org, and less with skips.
- The released leg proves what users install; the main leg proves what is about to ship.
- The droplet live run is excluded; it needs SSH and smoke-key secrets (Q5).

---

## Part E: migration plan (nothing goes red)

| Wave | PRs | Who merges | Ordering constraints |
|---|---|---|---|
| 0 | Sandbox S0; Q1 decided (bot App); Phase B merged in core (the layer test decides where `kinds.py` lives) | Maintainer | none |
| 1 (one batch) | Core C1, C2, C3, C5 | Maintainer (flagged) | Freeze core vector changes from C1 until every X2 is merged; consumers still compare against core `main` until then. C3 must merge before step 2. |
| 1 (parallel) | X1 in all 5 consumers; sandbox S1; Rust X3 (may merge; no stream tag yet) | auto | X1 has no dependency |
| 2 | **Core 1.7.1 release**: Phase A/B fixes plus C1-C3 = the first bundle | Maintainer | Needs C3: `published-artifacts` and `publish-image` would otherwise fail without SDK 1.7.1 releases (no empty releases), and on the gateway label |
| 3 (one batch) | X2 in all 5 consumers, synced with `--version 1.7.1` (or `--core-ref` if 1.7.1 is not out yet; the bot re-pins later); ruleset edits | Maintainer (workflows) | Remove the required check "SDK against core main" (TS, Rust) just before merging their X2, then add "SDK against core" and "Contract bundle". Add "Contract bundle" in the core after C1. |
| 4 | Core C4 (compatibility), core `consumer-pins.yml`, consumer `contract-pin.yml` (needs the App) | Maintainer | The table has real rows once consumers release with X2 |
| 5 | Rust stream tag ruleset patterns, then the first `genesis-mesh-verify-v*` / `genesis-mesh-edge-v*` releases | Maintainer | After C3 |

Required checks afterwards:
- **Core:** add "Contract bundle"; keep "Interop", now against pinned consumers.
- **Each SDK:** "Contract bundle", `release-train`, and "SDK against core" (TS, Rust) or "Live contract" (Go, .NET).
- **Gateway:** "Contract bundle", `release-train`, "Authority catalog and signing vectors match the core", "Network Authority end-to-end".
- **Never required:** canary, compatibility, contract-pin, consumer-pins, nightly-smoke.

Done when (plan section 7, phase C):
- every consumer's required checks read only its own repo, the pinned core commit and immutable release assets;
- over the 1.8.0 cycle, CI failures classified "caused by another repo" are 0;
- the compatibility table is published.

---

## Open questions for the Maintainer

1. **Bot identity.** Should cross-repo PRs come from a GitHub App ("genesis-mesh-bot"), which is needed because PRs opened with `GITHUB_TOKEN` don't trigger CI? And may bundle-bump PRs that touch only the lock, the copies, generated registries and a fragment auto-merge despite touching vector copies, since the content was already reviewed in the core? **Recommendation:** yes to the App, and yes to auto-merge for those PRs. A changed `consumer.json` still waits for you.
2. **First bundle.** **Recommendation:** release core 1.7.1 (the Phase A/B fixes are on `main`) as the first bundle. The alternative, backfilling a 1.7.0 bundle, is less clean: its signing identity would not be the tag's.
3. **Rust stream tag names:** `genesis-mesh-verify-vX.Y.Z` and `genesis-mesh-edge-vX.Y.Z`, keeping today's version numbers going forward. **Recommendation:** accept. Names starting with `verify-` or `v` would match the existing `v*` triggers and ruleset.
4. **Core Interop against pinned SDK releases** rather than SDK `main`. **Recommendation:** pinned releases, so core `main` cannot go red because of an SDK. SDK `main` × core `main` is covered by the canaries.
5. **Sandbox cost and droplet.** Keep the nightly in the private sandbox (≤~650 min/month, with skip-unchanged), and leave the droplet live run for a later PR with its own smoke-key secrets. **Recommendation:** yes. If the minutes become a problem, move the smoke apps (which hold no secrets) to a public repo.
6. **Compatibility table publication.** Commit it to the docs through a bot PR, so it appears on Pages, rather than keeping it as a workflow artifact only. **Recommendation:** commit via the bot PR.

### Critical files for implementation
- `C:\Source\GenesisMeshLabs\genesismesh\conformance\generate_vectors.py` (generators `:3344-3383`, `gen_field_registry` `:1261`)
- `C:\Source\GenesisMeshLabs\genesismesh\genesis_mesh\trust\evidence_store.py` (kind tables `:125, 511-603`), with `genesis_mesh\models\key_succession.py:67`
- `C:\Source\GenesisMeshLabs\genesismesh\.github\workflows\interop.yml`, `published-artifacts.yml`, `publish-image.yml`, `scripts\check_release_train.py`, `scripts\container_smoke.py`
- `C:\Source\GenesisMeshLabs\sdk-rust\.github\workflows\ci.yml`, `verifier.yml`, `edge.yml`, `scripts\check_release.py`, `RELEASING.md`
- `C:\Source\GenesisMeshLabs\sdk-go\.github\workflows\ci.yml` (the release-train and Live contract pattern repeated in TS, .NET and the gateway), and `C:\Source\GenesisMeshLabs\sandbox\tests\sdk-smoke-typescript\` (`na.py`, `src/harness.ts`, `package.json`)

Other sources:
- **Plan and gate:** `genesismesh\ops\plan-architecture.md`, `ops\quality-gate.md`.
- **Decisions:** `genesismesh\docs\development\decisions\0001-0007`, `docs\development\versioning.md`.
- **Core contract and conformance:** `contract\public-surface.json`, `conformance\CONFORMANCE.md`.
- **SDK sync scripts and conformance tests** in all four SDKs.
- **Gateway:** `.github\workflows\ci.yml`, `distribution.yml`, `tests\reference\build_service_catalog.py`.
- **Sandbox:** `tests\sdk-smoke-go\{go.mod,smoke.go}` and `tests\sdk-smoke-dotnet\{*.csproj,Program.cs}`.
- **Assessment reports:** `*-SYNTHESIS.md`, `godotnet-CRITIC.md`, `godotnet-SKEPTIC.md`, `PHASE-A.md`, `PHASE-B.md` (the per-repository assessment reports).
- **GitHub API:** repo visibility, core release assets and immutability, tag rulesets.
---

## Coordinator decisions (2026-10-16, binding)

1. **No bot for now** (Maintainer). `contract-pin.yml` in each consumer and
   `consumer-pins.yml` in the core open or update an **issue** (label
   `contract-bundle`) when a newer bundle / consumer release exists, with the
   exact `gm_contract.py sync --version V` command; the coordinator opens the
   bump PRs. The compatibility workflow publishes the table as a workflow
   artifact and opens/updates an issue on a regression; the committed docs table
   is refreshed by the coordinator's PRs (the renderer still exists).
2. **First bundle = core 1.7.1** (Maintainer). The core release PR comes after
   the Phase C core PRs merge; tagging needs the Maintainer's approval.
3. Rust stream tags `genesis-mesh-verify-vX.Y.Z` / `genesis-mesh-edge-vX.Y.Z`:
   accepted. 4. Core Interop against pinned consumer releases: accepted.
5. Nightly smoke in the private sandbox, droplet live run later: accepted.
6. Compatibility table: see 1.

Property tests everywhere must be deterministic in CI (fixed seed, env
override for local random runs) — a required check may never fail on a fresh
random seed.
