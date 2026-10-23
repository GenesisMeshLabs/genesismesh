### Fixed

- **A restarted Network Authority no longer stalls on its first remediation
  sweeps.** With `EVIDENCE_REMEDIATION=on`, the sweep looks again, once per
  instance, at the authorized decisions that have no remediation state. For
  each one it read the newest 5000 audit events to find who asked for the
  decision. A batch of 200 therefore took about 30 seconds on a busy store,
  inside the request that triggered the sweep, and a restart repeated it
  until every such decision had been looked at again. On the public
  mesh.genesismesh.org stack, that made the demo job's calls time out after
  the 1.8.0 upgrade. A batch now reads the audit log once.
