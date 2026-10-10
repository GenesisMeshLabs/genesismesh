### Security

- **Requests forged from a shared address no longer lock an operator out.**
  Behind a gateway or NAT, 30 forged admin requests naming an operator's key
  refused that operator's own requests for a minute, and enough junk from the
  address reached the address-wide cap and refused every key there. The
  failed-authentication throttle now refuses only requests that fail: a
  request correctly signed by an active operator key is served, throttled or
  not. A throttled request that fails gets `429 admin_auth_throttled` at its
  first failed check (headers, key, timestamp and nonce before the
  signature) and is neither counted nor audited again. The per-address admin
  request limit (`NA_RATE_LIMIT_ADMIN_PER_MINUTE`) is unchanged and still
  counts every admin request from the address.
