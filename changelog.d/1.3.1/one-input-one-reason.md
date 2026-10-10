### Fixed

- A number that breaks off after its point or exponent letter (`-0.`, `1e`,
  `100000000000000000000.`) is refused as `invalid_json`, as the Go, .NET and
  Rust SDKs refuse it; it was `negative_zero` or `integer_out_of_range`.
- The license policy of a data access intent check is checked whole, as the
  intent is: a policy leaving out a field the reference always writes is
  `Not in canonical form: policy`, as in the SDKs. Only its timestamps were
  checked.
- An agreement whose `signatures` holds one signature object rather than a
  list has no signature (`missing_offerer_signature`), as the SDKs read it.
- The conformance suites carry the cases: number grammar, floats halfway
  between two shortest spellings (the even digit is written), timestamps
  without an offset, the policy form, the export checks above, and the
  guard the Network Authority applies to an observation's and a break-glass
  record's own values (`metadata_problem` cases: sizes counted on the
  canonical JSON with non-ASCII escaped, the justification, `actor`,
  `source_event_id` and `version_id` included).
