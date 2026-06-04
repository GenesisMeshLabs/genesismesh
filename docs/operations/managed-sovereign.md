# Managed Sovereign Operations

A managed sovereign is a Genesis Mesh Network Authority operated on behalf of a
customer or design partner. The customer may delegate day-to-day hosting, but the
trust boundary must stay explicit.

## Minimum Managed Surface

A managed sovereign is pilot-ready only when these are in place:

- signed Genesis block and NA key custody model;
- operator key ownership and rotation procedure;
- durable SQLite storage;
- tested backup and restore procedure;
- audit export procedure;
- health, readiness, metrics, and external uptime probes;
- incident runbooks for key, treaty, feed, and DB failures;
- written responsibility matrix.

## Responsibility Matrix

| Area | Genesis Mesh managed operator | Customer / sovereign owner |
|---|---|---|
| VM/container hosting | Operates runtime, systemd/Gunicorn, ingress, logs | Approves hosting region and availability needs |
| Genesis block | Stores and deploys approved signed genesis | Owns sovereign name, root trust decision, and policy intent |
| NA private key | Custody depends on selected model | Approves custody model and rotation policy |
| Operator keys | Installs approved operator public keys | Owns who can perform admin actions |
| SQLite database | Backs up, restores, monitors disk and locks | Defines retention and incident disclosure needs |
| Recognition treaties | Executes approved treaty operations | Decides which sovereigns to recognize |
| Revocation feeds | Imports approved feeds and verifies results | Decides which issuer feeds are trusted |
| Audit exports | Produces redacted exports and incident bundles | Reviews trust decisions and compliance evidence |
| Incident response | Executes runbooks and preserves evidence | Makes authority and disclosure decisions |

## Key Custody Models

### Customer-Held NA Key

The customer keeps the NA private key and signs trust material through their own
process. Genesis Mesh operates hosting and verification infrastructure.

Use this when sovereignty and compliance requirements dominate convenience.

### Managed NA Key

Genesis Mesh stores the NA private key in the deployment secret store and
operates signing workflows for the customer.

Use this only with explicit customer approval, backup procedure, and incident
response expectations.

### Split Operation

Genesis Mesh operates the Network Authority service, but the customer controls
operator keys and approves treaty/revocation actions.

This is the preferred pilot model because it proves managed operation without
blurring policy ownership.

## Pilot-Readiness Checklist

- [ ] Customer sovereign name and policy intent are written down.
- [ ] NA key custody model is selected.
- [ ] Operator public keys are installed and private keys are not shared.
- [ ] `/healthz`, `/readyz`, `/metrics`, and `/connectome.json` are reachable
      from the operator network.
- [ ] `genesis-mesh managed backup` has produced a backup.
- [ ] `genesis-mesh managed restore` has been tested against a non-production
      DB.
- [ ] `genesis-mesh managed audit-export` has produced a redacted export.
- [ ] Incident response contacts are known.
- [ ] The customer understands that billing, multi-tenancy, and active-active HA
      are not part of v0.16.
