### Security

- **An allowed break-glass change the NA cannot tie to its attestation is
  flagged for review.** A break-glass record is judged as the evaluation of
  the attestation it names would have gone, but any executor key could name
  any attestation and be judged allowed with no operator involved. The
  judgement now says so and is flagged, unless the store holds execution
  evidence from the same executor under a decision for that attestation,
  recorded before the record. The verdict itself is unchanged: in the
  governed flow the executor and the attestation's subject differ.

### Fixed

- **Authentic observations and break-glass records refused after the fact
  are quarantined.** A record signed by a retired key, or outside its key's
  role or prefix (`*_key_retired`, `*_out_of_scope`), was refused without a
  trace in the store. It is now kept as a `quarantine` entry, named in the
  refusal's `error.details.quarantine_id` (and in a batch result's
  `error.details`), as execution evidence already was; never one that may
  carry secret material. The codes are unchanged.
