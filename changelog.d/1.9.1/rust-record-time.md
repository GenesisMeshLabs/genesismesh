### Security

- **The Rust SDK: a record without its own time is signed by no key of the
  NA's key history** (sdk-rust 1.9.1, GHSA-cwf5-mqxw-75hq). Given the key
  history, `verify_record` for an attestation or a policy, and
  `verify_store_anchors`, took every key of the history for a record whose
  time was absent or null. A succeeded NA key's signature over such a record
  therefore verified forever, past the key's vouching horizon. The Network
  Authority never signs such a record; whoever holds a succeeded key could.
  - The TypeScript SDK had the same flaw, fixed in 1.9.0
    (GHSA-rx24-98gh-f8mc).
  - Not affected: the Go and .NET SDKs, the edge agent and
    `genesis-mesh-verify`.
