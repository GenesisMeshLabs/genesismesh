# Client

The client itself: what each sub-client wraps, how admin requests are signed
and errors reported, and how the client works with several NA instances.

- {doc}`sub-clients`: every sub-client's methods and the key tier each needs
- {doc}`auth`: admin signatures, raw admin calls, errors and types
- {doc}`high-availability` (v0.60): failover across NA instances, readiness,
  and retryable conflicts

```{toctree}
:maxdepth: 1
:hidden:

sub-clients
auth
high-availability
```
