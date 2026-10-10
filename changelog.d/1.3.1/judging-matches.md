### Fixed

- **Another observer's report of a break-glass change is the same change.**
  1.3.0 judged it afresh, so one change could show `judged_denied` and
  `judged_allowed` at once. It now takes the stricter of the break-glass
  record's verdict and its own facts, like the first observation, as the
  runbook said.
- **A version matches only the change made at that time.** An observation
  was matched to any execution or break-glass record naming its version,
  whenever it was made: a change three days before a decision was judged
  allowed by it, and a resource that reuses a version (an unversioned
  object's `null`) was "the same change" forever. The matched record must
  now have been made within the observed change's time, give or take
  `NA_OBSERVATION_CLOCK_SKEW_SECONDS`.
- **A change window is judged where a policy's own validity starts or ends
  inside it.** Only activations and deactivations were checked, so a freeze
  scheduled to start inside the window was missed.
- **An imported revocation dates from the first feed that listed it.** A
  later cumulative feed listing it again moved the time, so a break-glass
  change made after the first revocation was judged allowed. Judgements also
  read the first import from the feeds when a 1.3.0 row was moved.
- **An observation and a break-glass record can no longer share an id.** A
  break-glass record reusing an observation's id took that observation's
  judgement, so the observation was never judged but counted as judged for
  retention. The second record is now refused (`409 observation_conflict` or
  `409 break_glass_conflict`). In a store where 1.3.0 admitted such a pair,
  each record is judged, counted and kept by retention as its own kind; the
  one that cannot be judged answers `409 judgement_conflict`.
- **A judgement that failed at admission is retried.** It used to wait for an
  operator to judge it by id. The NA now judges records left unjudged at
  every start (up to 100) and, with `NA_JUDGE_ON_ADMISSION=on`, a few more
  on an admission at most every five minutes.
