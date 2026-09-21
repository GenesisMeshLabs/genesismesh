# Sanitized public reference dashboard

The public deployment uses `examples/public_dashboard`, an isolated read-only
overlay over Genesis Mesh v0.56.0 protocol models. It has its own fresh database
and `gm-demo-public-na` genesis. Old signed records are archived offline, not
renamed. The new dataset contains ten neutral demo identities and nine treaties;
no revoked legacy identity is migrated.

The web process never loads private keys and opens SQLite with `mode=ro`. It
registers only public GET/HEAD routes. The generic authority API, enrollment,
signing, backups and full audit exports are not registered on this origin.
Protocol APIs used by other deployments retain their existing contracts.

## Console surfaces

The overlay keeps the shared operator-console pages rather than replacing them.
Navigation runs current state first, then reference: `/` and `/dashboard` are the
sanitized trust dashboard, `/connectome` and `/atlas` the graph views, and
`/surfaces`, `/api-reference`, `/cli-reference` and `/swagger.json` the generated
protocol references. `/surfaces` is a grouped preview of the API and CLI
references, so it sits beside them instead of on the landing page. Each page carries the public-instance notice, and the surface tables
link only to routes this instance actually serves — documented signed POST,
admin and unregistered GET surfaces render as plain paths instead of dead links.

## Status and privacy

Service readiness is separate from trust posture. Only expected active,
non-retired relationships contribute required feeds. An expected treaty that
expires degrades posture; retired history and revoked treaties do not create
current warnings. Missing/stale required feeds deny the local sensitive
authorization policy. This site itself never authorizes an operation.

Feed age is calculated from the signed issue timestamp: less than 24 hours is
fresh, 24 through 72 hours is warning, and more than 72 hours is stale. Repeated
downloads cannot reset it. An unchanged-content heartbeat has the same sequence
but a later signed issue time. Lower sequences, repeated timestamps, changed
content at the same sequence, and revocation rollback are rejected.

All public data conforms to a typed snapshot allowlist. Nested signed protocol
records additionally have strict identity, metadata, scope and identifier
checks. Unsafe records cause the public app to fail closed with a generic error.
The signed snapshot binds expected-active flags, imports and canary results.
Historical evidence can be included only after it meets the same neutral schema.

## Local setup

Run from a checkout with the package and requirements installed:

```bash
python -m examples.public_dashboard.seed /var/lib/genesis-mesh-public
python -m examples.public_dashboard.publisher /var/lib/genesis-mesh-public/published
# In a second terminal:
python -m examples.public_dashboard.maintenance /var/lib/genesis-mesh-public
PUBLIC_DEMO_DIR=/var/lib/genesis-mesh-public GENESIS_BUILD_SHA=$(git rev-parse HEAD) \
  gunicorn --bind 127.0.0.1:28443 'examples.public_dashboard.app:configured_app()'
```

Seed refuses an existing directory. The public app reads the installed package
version automatically and deployment passes the actual Git commit. It never
uses the network protocol version as the product version.

## Maintenance and alerts

The systemd timer imports all required feeds hourly. A local publisher serves
signed files over loopback HTTP. Keys belong to the maintenance user and are
inaccessible to the web and publisher users. The daily canary issues a demo
attestation, fetches it over HTTP, verifies acceptance, publishes a revocation,
imports it, and verifies rejection. The sequence increases only for that changed
revocation content; hourly heartbeats preserve it.

These are separately signed authorities on one host. The canary verifies
cross-authority communication and verification, not independent infrastructure.
It can be fresh while another authority's revocation feed is stale.

Successful and failed imports are recorded in the local `imports.jsonl` log.
Warnings at 24 hours appear in the dashboard and systemd journal. Failed jobs
trigger a local systemd alert unit. External email or messaging is not configured.
The public event list is capped at 1,000 records; local full history is preserved.

## Offline verification

Download `/evidence.json`. From the same source checkout, disconnect networking
and run the command displayed by the dashboard:

```bash
python -m examples.public_dashboard.verify evidence.json --root-key '<pinned-root-public-key>'
```

The verifier checks the root, signed snapshot, every authority, treaty and feed,
plus current required-feed freshness. Obtain the root fingerprint through a
separately trusted channel. A root downloaded with the evidence is not an
independent trust anchor. Valid signatures do not imply independent operators.

## Deployment and rollback

`infrastructure/scripts/deploy-public-dashboard.sh` prepares a separate checkout
and service, validates it, takes a SQLite online backup and offline configuration
archive, then switches only the target Nginx virtual host. The old authority and
its old scheduled canary are stopped. Existing unrelated virtual hosts remain
unchanged. Backups are root-only and never served by HTTP.

The app has CSP, HSTS, nosniff, generic errors and short public cache lifetimes.
Nginx adds a shared rate limit and response cache. Access logs on this vhost omit
client addresses; its error logs rotate daily with one-day retention. There are
no full audit or backup HTTP endpoints.

Rollback requires an operator to restore the saved vhost configuration and start
the old authority service. Doing so restores the old public data too; review the
privacy implications before rollback.

## Validation

```bash
python -m pytest genesis_mesh/tests/test_public_reference_dashboard.py -q
python -m pip_audit -r requirements.txt -r requirements-dev.txt
```

Live acceptance must check HTML and JSON, not just the health endpoint. Verify
the timer's next run, repeated heartbeat sequence stability, rejection of POST,
headers, stale-feed denial tests, and a downloaded bundle against the pinned root.
