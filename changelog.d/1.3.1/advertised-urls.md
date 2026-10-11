### Fixed

- `NA_PUBLIC_URL` is validated strictly at start: `http` or `https`, a DNS
  name or IP address (IPv6 in brackets), an optional port of 1 to 65535 and
  nothing after it but a `/`. A value such as `https://na.example.org:abc`, or
  one with a space in it, was accepted and advertised.
- Without `NA_PUBLIC_URL`, a request whose host is not a valid origin gets
  `400 bad_request` from `/sovereign.json` and `/swagger.json`; a host such as
  `na.example:8443@evil.example` advertised the URL `https:`.
- The reference HA load balancer (`deploy/compose/ha`) forwarded the client's
  `Host`, port included, so a client chose the URLs the NA advertised. The NA
  there now advertises `NA_PUBLIC_URL` (default `http://localhost:8443`), and
  nginx overwrites `X-Forwarded-Host` with its own server name. The
  configuration and upgrade guides no longer suggest
  `proxy_set_header X-Forwarded-Host $host`, which passes on the client's
  `Host`: use `$server_name` and set `NA_PUBLIC_URL`.
