### Security

- **`NA_PROXY_HOPS` defaults to `0`.** With the old default of `1`, a client
  that reached the Network Authority directly chose the address its rate
  limits applied to by sending `X-Forwarded-For`: 500 forged admin requests
  with a different header each were never throttled, which voided the
  failed-authentication limit. The NA now trusts no forwarded headers unless
  told how many proxies sit in front of it.
- The in-memory rate limiter forgets buckets with no request in the last
  window; every client address seen used to stay in memory for the life of
  the process.

### Upgrading

- **Behind a reverse proxy or load balancer, set `NA_PROXY_HOPS=1`** (the
  number of proxies in front). Without it, every client shares the proxy's
  address for rate limiting, and the advertised URLs follow the proxy's view
  of the scheme and host. The HA compose file, the systemd unit and the VM
  bootstrap script in this repository now set it; the Kubernetes manifest
  sets `0` and says to raise it behind an Ingress. A deployment that already
  sets `NA_PROXY_HOPS` is unaffected.
