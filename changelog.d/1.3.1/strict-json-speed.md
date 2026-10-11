### Fixed

- Strict JSON reads a valid request body at the standard parser's speed
  again. Since 1.3.0 every body was first scanned in Python, about four
  times slower than in 1.2 (two seconds for a 2 MiB body of small values),
  and before the request was authenticated. The scanner now runs only when
  the parser refuses the text or the text may hold a lone surrogate or
  nesting deeper than 64; it still names the first fault in text order, so
  every input gets the same value or the same reason as before. A body is
  still refused at `NA_MAX_REQUEST_BYTES` before it is read.
