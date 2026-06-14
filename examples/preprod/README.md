# Preprod References

**Not for production.** This directory holds credential-bearing, environment-
specific *worked examples* for maintainers — distinct from the clean, public
verification artifacts under `examples/official-operators/`,
`examples/founding-community-operators/`, and `examples/nba-demo-operators/`,
which contain declarative data only (no executable logic, no secrets).

## `install-miraos-na.reference.sh`

A worked example that stands up a second Network Authority (MiraOS-NA on `:8543`)
beside an existing EPICAL-NA (`:8443`), federates them, and links to the USG NA
via recognition treaties (systemd-based, Linux).

It embeds **public** material inline (the signed genesis block and the operator
public key — both are verification data, safe to share). The **private** keys are
**not committed**. Supply them at run time one of two ways:

1. Environment variables:

   ```bash
   export MIRAOS_NA_KEY_B64='<base64 of the NA private key file>'
   export MIRAOS_OPERATOR_KEY_B64='<base64 of the operator private key file>'
   sudo -E bash examples/preprod/install-miraos-na.reference.sh
   ```

2. A local, gitignored secrets file (`examples/preprod/miraos-na.secrets.sh`):

   ```bash
   cat > examples/preprod/miraos-na.secrets.sh <<'EOF'
   export MIRAOS_NA_KEY_B64='...'
   export MIRAOS_OPERATOR_KEY_B64='...'
   EOF
   sudo bash examples/preprod/install-miraos-na.reference.sh
   ```

`*.secrets.sh` and `*.key` are gitignored here. Treat any preprod keys as
disposable and rotate them at production cutover.
